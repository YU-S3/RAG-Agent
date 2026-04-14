import time
from dataclasses import dataclass
from typing import Any

from app.core.domain_config import LocalModelPolicy
from app.core.settings import get_settings
from app.services.local_llm import LLMResult, LocalLLMClient

settings = get_settings()


@dataclass
class CachedEntry:
    """缓存项。"""

    value: LLMResult
    expire_at: float


@dataclass
class LLMTarget:
    provider: str
    base_url: str
    model: str
    api_key: str = ""
    source: str = "local"


class DynamicLLMRouter:
    """基于复杂度、预算与可用性的本地模型路由器。"""

    def __init__(self, cache_ttl_seconds: int, default_budget_tokens: int):
        self.cache_ttl_seconds = cache_ttl_seconds
        self.default_budget_tokens = default_budget_tokens
        self._cache: dict[str, CachedEntry] = {}
        self._settings = settings

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """粗略估算 token 数。"""

        return max(1, len(text) // 2)

    def _cache_key(self, provider: str, model: str, base_url: str, prompt: str) -> str:
        return f"{provider}:{model}:{base_url}:{hash(prompt)}"

    def _get_cached(self, provider: str, model: str, base_url: str, prompt: str) -> LLMResult | None:
        key = self._cache_key(provider, model, base_url, prompt)
        entry = self._cache.get(key)
        now = time.time()
        if entry is None:
            return None
        if entry.expire_at <= now:
            self._cache.pop(key, None)
            return None
        return entry.value

    def _set_cached(self, provider: str, model: str, base_url: str, prompt: str, value: LLMResult) -> None:
        key = self._cache_key(provider, model, base_url, prompt)
        self._cache[key] = CachedEntry(value=value, expire_at=time.time() + self.cache_ttl_seconds)

    def _build_candidates(self, task: str, prompt: str, policy: LocalModelPolicy) -> list[LLMTarget]:
        candidates: list[LLMTarget] = []
        # Prefer online provider when configured; fallback to local chain on any failure.
        if (
            self._settings.remote_llm_enabled
            and self._settings.remote_llm_base_url.strip()
            and self._settings.remote_llm_model.strip()
            and self._settings.remote_llm_api_key.strip()
        ):
            candidates.append(
                LLMTarget(
                    provider=self._settings.remote_llm_provider,
                    base_url=self._settings.remote_llm_base_url.strip(),
                    model=self._settings.remote_llm_model.strip(),
                    api_key=self._settings.remote_llm_api_key.strip(),
                    source="remote",
                )
            )
        local_models: list[str] = []
        token_estimate = self.estimate_tokens(prompt)
        budget_tokens = policy.budget_tokens or self.default_budget_tokens
        low_cost_preferred = token_estimate > budget_tokens or len(task) < 24
        if low_cost_preferred and policy.lite_model:
            local_models.append(policy.lite_model)
        local_models.append(policy.model)
        local_models.extend(policy.fallback_models)
        deduped: list[str] = []
        for item in local_models:
            if item and item not in deduped:
                deduped.append(item)
        for model_name in deduped:
            candidates.append(
                LLMTarget(
                    provider=policy.provider,
                    base_url=policy.base_url,
                    model=model_name,
                    source="local",
                )
            )
        return candidates

    async def invoke(self, task: str, prompt: str, policy: LocalModelPolicy) -> tuple[LLMResult, dict[str, Any]]:
        """按规则路由模型，失败时自动降级，命中缓存则直接返回。"""

        last_error = ""
        candidates = self._build_candidates(task, prompt, policy)
        if not candidates:
            raise RuntimeError("all_models_failed:no_candidate_model")
        token_estimate = self.estimate_tokens(prompt)
        for target in candidates:
            cached = self._get_cached(target.provider, target.model, target.base_url, prompt)
            if cached is not None:
                return cached, {
                    "model": target.model,
                    "provider": target.provider,
                    "source": target.source,
                    "cache_hit": True,
                    "token_estimate": token_estimate,
                }
            try:
                llm = LocalLLMClient(
                    provider=target.provider,
                    base_url=target.base_url,
                    model=target.model,
                    api_key=target.api_key,
                    timeout_seconds=self._settings.remote_llm_timeout_seconds,
                )
                result = await llm.invoke(prompt)
                if not result.content.strip():
                    raise RuntimeError("empty_model_response")
                self._set_cached(target.provider, target.model, target.base_url, prompt, result)
                return result, {
                    "model": target.model,
                    "provider": target.provider,
                    "source": target.source,
                    "cache_hit": False,
                    "token_estimate": token_estimate,
                }
            except Exception as exc:
                last_error = str(exc) or exc.__class__.__name__
        raise RuntimeError(f"all_models_failed:{last_error}")
