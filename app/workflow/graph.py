import json
from typing import Any, Literal

from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from app.core.meta_router import RuntimeContext
from app.core.prompt_loader import render_prompt
from app.core.settings import get_settings
from app.memory.orchestrator import MemoryOrchestrator
from app.services.llm_router import DynamicLLMRouter
from app.services.local_llm import LLMResult
from app.workflow.quality import build_degraded_output, validate_output
from app.workflow.state import AgentState
from app.workflow.tools import ToolRegistry


class WorkflowResult(BaseModel):
    """工作流最终输出。"""

    domain: str
    model: str
    prompt: str
    output: str
    confidence: float
    retry_count: int
    tool_results: list[dict[str, Any]]
    memory_meta: dict[str, Any]
    process: dict[str, Any]


registry = ToolRegistry()
settings = get_settings()
llm_router = DynamicLLMRouter(
    cache_ttl_seconds=settings.llm_cache_ttl_seconds,
    default_budget_tokens=settings.llm_default_budget_tokens,
)
memory_orchestrators: dict[str, MemoryOrchestrator] = {}


def get_memory_orchestrator(embed_base_url: str) -> MemoryOrchestrator:
    orchestrator = memory_orchestrators.get(embed_base_url)
    if orchestrator is not None:
        return orchestrator
    created = MemoryOrchestrator(embed_base_url=embed_base_url, embed_model=settings.rag_embedding_model)
    memory_orchestrators[embed_base_url] = created
    return created


async def planner(state: AgentState) -> AgentState:
    """生成任务计划并构造工具调用列表。"""

    prompt = render_prompt(
        state["domain"],
        "planner.j2",
        {
            "domain": state["domain"],
            "task": state["task"],
            "memory_context": state["memory_context"],
            "rag_context": state["rag_context"],
            "tools_schema": ", ".join(state["analysis"]["tools"]),
            "output_format": state["output_schema"],
        },
    )
    if state["analysis"].get("error"):
        prompt = f"{prompt}\n上轮错误：{state['analysis']['error']}\n请修复该错误并严格满足输出格式。"
    planner_error = ""
    try:
        result, route_meta = await llm_router.invoke(
            task=state["task"],
            prompt=prompt,
            policy=state["analysis"]["model_policy"],
        )
    except Exception as exc:
        planner_error = f"planner_invoke_failed:{str(exc) or 'unknown'}"
        fallback_json = json.dumps({"summary": f"模型暂不可用，已降级返回。任务：{state['task']}"}, ensure_ascii=False)
        result = LLMResult(content=fallback_json, model="degraded-fallback")
        route_meta = {"model": "degraded-fallback", "cache_hit": False, "fallback": True}
    current_calls = [{"name": name, "args": {"task": state["task"], "plan": result.content}} for name in state["analysis"]["tools"]]
    return {
        **state,
        "prompt": prompt,
        "model": result.model,
        "analysis": {**state["analysis"], "route_meta": route_meta, "error": planner_error or state["analysis"].get("error", "")},
        "messages": state["messages"] + [result.content],
        "tool_calls": current_calls,
    }


async def executor(state: AgentState) -> AgentState:
    """执行规划阶段生成的工具调用。"""

    results: list[dict[str, Any]] = []
    allowed_permissions = set(state["analysis"].get("allowed_permissions", ["readonly"]))
    for call in state["tool_calls"]:
        result = registry.run(
            domain=state["domain"],
            name=call["name"],
            args=call["args"],
            allowed_permissions=allowed_permissions,
        )
        results.append(result)
    return {**state, "tool_results": results}


async def analyzer(state: AgentState) -> AgentState:
    """分析结果质量并给出重试决策。"""

    has_error = any("error" in item for item in state["tool_results"])
    output_text = state["messages"][-1] if state["messages"] else ""
    validation = validate_output(output_text, state["output_schema"])
    confidence = 0.90 if validation.valid else 0.40
    error = validation.error or state["analysis"].get("error", "")
    if has_error:
        confidence = min(confidence, 0.35)
        if not error:
            error = "tool_execution_error"
    retry_count = state["retry_count"]
    if confidence < state["confidence_threshold"]:
        retry_count = state["retry_count"] + 1
    breaker_open = confidence < state["confidence_threshold"] and retry_count > state["max_retries"]
    final_payload: dict[str, Any]
    if breaker_open:
        final_payload = build_degraded_output(output_text, error)
    else:
        final_payload = validation.normalized
    summary = str(final_payload.get("summary", "")).strip()
    if not summary:
        final_payload["summary"] = f"已完成任务处理：{state['task']}"
    final_payload["tool_results"] = state["tool_results"]
    final_output = json.dumps(final_payload, ensure_ascii=False)
    return {
        **state,
        "analysis": {**state["analysis"], "confidence": confidence, "error": error, "breaker_open": breaker_open},
        "retry_count": retry_count,
        "final_output": final_output,
    }


def route_after_analysis(state: AgentState) -> Literal["planner", END]:
    """根据置信度和重试次数决定下一步。"""

    if state["analysis"]["confidence"] < state["confidence_threshold"] and state["retry_count"] <= state["max_retries"]:
        return "planner"
    return END


def build_graph():
    """构建并编译 LangGraph 工作流。"""

    graph = StateGraph(AgentState)
    graph.add_node("planner", planner)
    graph.add_node("executor", executor)
    graph.add_node("analyzer", analyzer)
    graph.add_edge("planner", "executor")
    graph.add_edge("executor", "analyzer")
    graph.add_conditional_edges("analyzer", route_after_analysis)
    graph.set_entry_point("planner")
    return graph.compile()


app_graph = build_graph()


async def run_workflow(ctx: RuntimeContext) -> WorkflowResult:
    """执行完整工作流并返回结构化结果。"""

    memory = get_memory_orchestrator(embed_base_url=ctx.domain_config.model_policy.base_url)
    retrieved = await memory.retrieve(
        domain=ctx.domain,
        query=ctx.task,
        session_id=ctx.session_id,
        user_id=ctx.user_id,
        top_k=ctx.top_k,
        use_memory=ctx.use_memory,
    )
    initial_state: AgentState = {
        "task": ctx.task,
        "domain": ctx.domain,
        "session_id": retrieved["session_id"],
        "user_id": ctx.user_id,
        "use_memory": ctx.use_memory,
        "top_k": ctx.top_k,
        "memory_context": retrieved["memory_context"],
        "rag_context": retrieved["rag_context"],
        "memory_meta": retrieved["memory_meta"],
        "prompt": "",
        "model": "",
        "messages": [],
        "tool_calls": [],
        "tool_results": [],
        "analysis": {
            "confidence": 0.0,
            "error": "",
            "model_policy": ctx.domain_config.model_policy,
            "tools": ctx.domain_config.tools,
            "allowed_permissions": ["readonly"],
        },
        "retry_count": 0,
        "max_retries": ctx.domain_config.retry_policy.max_retries,
        "confidence_threshold": ctx.domain_config.retry_policy.confidence_threshold,
        "output_schema": ctx.output_format,
        "final_output": "",
    }
    final_state = await app_graph.ainvoke(initial_state)
    await memory.persist(
        domain=ctx.domain,
        session_id=final_state["session_id"],
        user_id=ctx.user_id,
        task=ctx.task,
        output=final_state["final_output"],
        use_memory=ctx.use_memory,
    )
    route_meta = dict(final_state["analysis"].get("route_meta", {}))
    route_meta["retrieval"] = {
        "reranker_type": final_state["memory_meta"].get("reranker_type", ""),
        "doc_candidates": final_state["memory_meta"].get("doc_candidates", 0),
        "long_candidates": final_state["memory_meta"].get("long_candidates", 0),
        "doc_rerank": final_state["memory_meta"].get("doc_rerank", {}),
        "long_rerank": final_state["memory_meta"].get("long_rerank", {}),
    }
    return WorkflowResult(
        domain=ctx.domain,
        model=final_state["model"],
        prompt=final_state["prompt"],
        output=final_state["final_output"],
        confidence=float(final_state["analysis"]["confidence"]),
        retry_count=final_state["retry_count"],
        tool_results=final_state["tool_results"],
        memory_meta=final_state["memory_meta"],
        process={
            "thinking_steps": [
                f"已检索短期记忆回合: {final_state['memory_meta'].get('short_turns', 0)}",
                f"已召回知识库片段: {final_state['memory_meta'].get('rag_hits', 0)}",
                f"已召回长期记忆片段: {final_state['memory_meta'].get('long_hits', 0)}",
                f"已完成任务规划并选择模型: {final_state['model']}",
                f"已执行工具调用: {len(final_state['tool_calls'])} 个",
            ],
            "tool_calls": final_state["tool_calls"],
            "tool_results": final_state["tool_results"],
            "route_meta": route_meta,
            "confidence": float(final_state["analysis"]["confidence"]),
            "retry_count": final_state["retry_count"],
        },
    )
