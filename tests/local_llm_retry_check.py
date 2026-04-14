import asyncio
from unittest.mock import AsyncMock, patch

from app.services.local_llm import LocalLLMClient


class DummyResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http_error:{self.status_code}")

    def json(self) -> dict:
        return self._payload


async def run_async() -> None:
    client = LocalLLMClient("ollama", "http://127.0.0.1:11434", "qwen3:8b")
    post = AsyncMock(
        side_effect=[
            DummyResponse(502, {}),
            DummyResponse(200, {"response": "ok", "model": "qwen3:8b"}),
        ]
    )
    with patch("httpx.AsyncClient.post", new=post):
        result = await client.invoke("retry")
    assert result.content == "ok"
    kwargs = post.await_args_list[0].kwargs
    assert kwargs["json"]["think"] is False


def run() -> None:
    asyncio.run(run_async())


if __name__ == "__main__":
    run()
