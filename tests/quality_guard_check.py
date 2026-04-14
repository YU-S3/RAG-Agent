import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.core.domain_config import DomainConfig, LocalModelPolicy, RetryPolicy
from app.core.meta_router import RuntimeContext
from app.workflow.graph import run_workflow


async def run() -> None:
    """验证输出校验与熔断降级行为。"""

    ctx = RuntimeContext(
        domain="default",
        task="触发降级",
        session_id="s-quality",
        user_id="u-quality",
        use_memory=False,
        top_k=4,
        domain_config=DomainConfig(
            domain="default",
            model_policy=LocalModelPolicy(provider="ollama", model="qwen3:8b", base_url="http://127.0.0.1:11434"),
            tools=["not_exists_tool"],
            output_schema={"type": "object", "required": ["summary"]},
            retry_policy=RetryPolicy(max_retries=1, confidence_threshold=0.85),
        ),
        output_format={"type": "object", "required": ["summary"]},
    )
    fake = AsyncMock(return_value=type("X", (), {"content": "", "model": "mock"})())
    with patch("app.services.local_llm.LocalLLMClient.invoke", new=fake):
        result = await run_workflow(ctx)
    payload = json.loads(result.output)
    assert payload.get("degraded") is True
    assert "summary" in payload
    assert isinstance(payload.get("tool_results"), list)


if __name__ == "__main__":
    asyncio.run(run())
