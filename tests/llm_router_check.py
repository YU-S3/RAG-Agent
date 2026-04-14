import asyncio
from unittest.mock import patch

from app.core.domain_config import LocalModelPolicy
from app.services import llm_router as llm_router_module
from app.services.llm_router import DynamicLLMRouter
from app.services.local_llm import LLMResult


async def run() -> None:
    """验证降级、缓存与预算路由逻辑。"""

    router = DynamicLLMRouter(cache_ttl_seconds=600, default_budget_tokens=4096)

    async def fallback_invoke(self, prompt: str):
        if self.model == "m1":
            raise RuntimeError("m1_down")
        return LLMResult(content=f"ok:{self.model}", model=self.model)

    with patch("app.services.local_llm.LocalLLMClient.invoke", new=fallback_invoke):
        fallback_policy = LocalModelPolicy(
            provider="ollama",
            model="m1",
            base_url="http://127.0.0.1:11434",
            fallback_models=["m2"],
            budget_tokens=4096,
        )
        result, meta = await router.invoke("任务", "测试fallback", fallback_policy)
        assert result.model == "m2"
        assert meta["model"] == "m2"

    remote_models: list[str] = []

    async def remote_fallback_invoke(self, prompt: str):
        remote_models.append(f"{self.provider}:{self.model}")
        if self.provider == "openai_compatible":
            raise RuntimeError("remote_auth_failed:401")
        return LLMResult(content=f"ok:{self.model}", model=self.model)

    prev_remote_enabled = llm_router_module.settings.remote_llm_enabled
    prev_remote_provider = llm_router_module.settings.remote_llm_provider
    prev_remote_base_url = llm_router_module.settings.remote_llm_base_url
    prev_remote_api_key = llm_router_module.settings.remote_llm_api_key
    prev_remote_model = llm_router_module.settings.remote_llm_model
    try:
        llm_router_module.settings.remote_llm_enabled = True
        llm_router_module.settings.remote_llm_provider = "openai_compatible"
        llm_router_module.settings.remote_llm_base_url = "https://example-remote-llm.com"
        llm_router_module.settings.remote_llm_api_key = "k-test"
        llm_router_module.settings.remote_llm_model = "remote-model"
        with patch("app.services.local_llm.LocalLLMClient.invoke", new=remote_fallback_invoke):
            remote_policy = LocalModelPolicy(
                provider="ollama",
                model="local-main",
                base_url="http://127.0.0.1:11434",
                fallback_models=["local-fallback"],
                budget_tokens=4096,
            )
            result, meta = await router.invoke("任务", "远程优先失败后本地降级", remote_policy)
            assert result.model in {"local-main", "local-fallback"}
            assert remote_models[0].startswith("openai_compatible:")
            assert meta["source"] == "local"
    finally:
        llm_router_module.settings.remote_llm_enabled = prev_remote_enabled
        llm_router_module.settings.remote_llm_provider = prev_remote_provider
        llm_router_module.settings.remote_llm_base_url = prev_remote_base_url
        llm_router_module.settings.remote_llm_api_key = prev_remote_api_key
        llm_router_module.settings.remote_llm_model = prev_remote_model

    call_models: list[str] = []

    async def cache_invoke(self, prompt: str):
        call_models.append(self.model)
        return LLMResult(content=f"ok:{self.model}", model=self.model)

    with patch("app.services.local_llm.LocalLLMClient.invoke", new=cache_invoke):
        cache_policy = LocalModelPolicy(
            provider="ollama",
            model="cache-model",
            base_url="http://127.0.0.1:11434",
            budget_tokens=4096,
        )
        _, meta1 = await router.invoke("任务", "相同提示词", cache_policy)
        _, meta2 = await router.invoke("任务", "相同提示词", cache_policy)
        assert meta1["cache_hit"] is False
        assert meta2["cache_hit"] is True
        assert call_models.count("cache-model") == 1

    budget_models: list[str] = []

    async def budget_invoke(self, prompt: str):
        budget_models.append(self.model)
        return LLMResult(content=f"ok:{self.model}", model=self.model)

    with patch("app.services.local_llm.LocalLLMClient.invoke", new=budget_invoke):
        budget_policy = LocalModelPolicy(
            provider="ollama",
            model="big-model",
            lite_model="small-model",
            base_url="http://127.0.0.1:11434",
            budget_tokens=10,
        )
        await router.invoke("任务", "这是一段较长的提示词用于触发预算规则并优先尝试轻量模型", budget_policy)
        assert budget_models[0] == "small-model"


if __name__ == "__main__":
    asyncio.run(run())
