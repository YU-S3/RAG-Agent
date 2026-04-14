from typing import Any, TypedDict


class AgentState(TypedDict):
    """LangGraph 节点之间共享的状态对象。"""

    task: str
    domain: str
    session_id: str
    user_id: str
    use_memory: bool
    top_k: int
    memory_context: str
    rag_context: str
    memory_meta: dict[str, Any]
    prompt: str
    model: str
    messages: list[str]
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    analysis: dict[str, Any]
    retry_count: int
    max_retries: int
    confidence_threshold: float
    output_schema: dict[str, Any]
    final_output: str
