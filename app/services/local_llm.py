import asyncio
import logging
import time

import httpx
from pydantic import BaseModel

_LAST_LLM_DEBUG: dict[str, object] = {}


def get_last_llm_debug() -> dict[str, object]:
    return dict(_LAST_LLM_DEBUG)


def _set_last_llm_debug(payload: dict[str, object]) -> None:
    _LAST_LLM_DEBUG.clear()
    _LAST_LLM_DEBUG.update(payload)


class LLMResult(BaseModel):
    """统一的模型输出结构。"""

    content: str
    model: str


class LocalLLMClient:
    """统一 LLM 客户端：支持线上 OpenAI 兼容接口与本地 Ollama。"""

    logger = logging.getLogger(__name__)

    def __init__(self, provider: str, base_url: str, model: str, api_key: str = "", timeout_seconds: int = 180):
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _join_url(base_url: str, path: str) -> str:
        base = base_url.rstrip("/")
        if base.endswith("/v1") and path.startswith("/v1/"):
            path = path[len("/v1") :]
        return f"{base}{path}"

    async def _invoke_ollama(self, prompt: str) -> LLMResult:
        payload = {"model": self.model, "prompt": prompt, "stream": False, "think": False}
        payload["options"] = {"num_predict": 256}
        data = {}
        last_error = ""
        _set_last_llm_debug(
            {
                "ts": time.time(),
                "provider": self.provider,
                "model": self.model,
                "base_url": self.base_url,
                "prompt_preview": prompt[:500],
                "request_payload": payload,
                "status": "started",
                "attempts": 0,
            }
        )
        async with httpx.AsyncClient(timeout=float(self.timeout_seconds)) as client:
            for attempt in range(3):
                try:
                    response = await client.post(self._join_url(self.base_url, "/api/generate"), json=payload)
                    response.raise_for_status()
                    data = response.json()
                    _set_last_llm_debug(
                        {
                            **get_last_llm_debug(),
                            "status": "ok",
                            "attempts": attempt + 1,
                            "http_status": response.status_code,
                            "response_keys": list(data.keys()),
                            "response_preview": str(data.get("response", ""))[:800],
                            "done_reason": data.get("done_reason"),
                            "eval_count": data.get("eval_count"),
                            "prompt_eval_count": data.get("prompt_eval_count"),
                        }
                    )
                    break
                except Exception as exc:
                    last_error = str(exc)
                    _set_last_llm_debug(
                        {
                            **get_last_llm_debug(),
                            "status": "retrying" if attempt < 2 else "failed",
                            "attempts": attempt + 1,
                            "last_error": last_error,
                        }
                    )
                    if attempt >= 2:
                        raise RuntimeError(f"ollama_generate_failed:{last_error}") from exc
                    await asyncio.sleep(0.8 + attempt * 0.7)
        content = str(data.get("response", ""))
        if not content.strip():
            message = data.get("message")
            if isinstance(message, dict):
                content = str(message.get("content", ""))
        if not content.strip():
            content = str(data.get("thinking", ""))
        if not content.strip():
            self.logger.warning(
                "empty_llm_response provider=%s model=%s done_reason=%s eval_count=%s prompt_eval_count=%s",
                self.provider,
                self.model,
                data.get("done_reason"),
                data.get("eval_count"),
                data.get("prompt_eval_count"),
            )
        return LLMResult(content=content, model=data.get("model", self.model))

    async def _invoke_openai_compatible(self, prompt: str) -> LLMResult:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = {}
        _set_last_llm_debug(
            {
                "ts": time.time(),
                "provider": self.provider,
                "model": self.model,
                "base_url": self.base_url,
                "prompt_preview": prompt[:500],
                "request_payload": {"model": self.model, "messages_count": 1},
                "status": "started",
                "attempts": 0,
            }
        )
        async with httpx.AsyncClient(timeout=float(self.timeout_seconds)) as client:
            for attempt in range(3):
                try:
                    response = await client.post(
                        self._join_url(self.base_url, "/v1/chat/completions"),
                        json=payload,
                        headers=headers,
                    )
                    if response.status_code in {401, 403}:
                        raise RuntimeError(f"remote_auth_failed:{response.status_code}")
                    response.raise_for_status()
                    data = response.json()
                    _set_last_llm_debug(
                        {
                            **get_last_llm_debug(),
                            "status": "ok",
                            "attempts": attempt + 1,
                            "http_status": response.status_code,
                            "response_keys": list(data.keys()) if isinstance(data, dict) else [],
                        }
                    )
                    break
                except Exception as exc:
                    _set_last_llm_debug(
                        {
                            **get_last_llm_debug(),
                            "status": "retrying" if attempt < 2 else "failed",
                            "attempts": attempt + 1,
                            "last_error": str(exc),
                        }
                    )
                    if attempt >= 2 or "remote_auth_failed" in str(exc):
                        raise RuntimeError(f"remote_llm_failed:{exc}") from exc
                    await asyncio.sleep(0.8 + attempt * 0.7)
        choices = data.get("choices", []) if isinstance(data, dict) else []
        content = ""
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message")
            if isinstance(msg, dict):
                content = str(msg.get("content", ""))
        if not content.strip():
            raise RuntimeError("remote_empty_response")
        return LLMResult(content=content, model=str(data.get("model", self.model)))

    async def invoke(self, prompt: str) -> LLMResult:
        """调用模型并返回文本结果。"""
        if self.provider == "ollama":
            return await self._invoke_ollama(prompt)
        if self.provider in {"openai_compatible", "openai"}:
            return await self._invoke_openai_compatible(prompt)
        raise ValueError(f"Unsupported llm provider: {self.provider}")
