import asyncio
from unittest.mock import AsyncMock, patch

from app.rag.embedder import HybridEmbedder


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
    embedder = HybridEmbedder("http://127.0.0.1:11434", "nomic-embed-text")
    post = AsyncMock(side_effect=[DummyResponse(200, {"embedding": [0.1, 0.2, 0.3]})])
    with patch("httpx.AsyncClient.post", new=post):
        vec = await embedder.embed("hello")
    assert len(vec) == 3
    assert abs(vec[0] - 0.1) < 1e-6

    embedder_404 = HybridEmbedder("http://127.0.0.1:11434", "nomic-embed-text")
    post_404 = AsyncMock(side_effect=[DummyResponse(404, {}), DummyResponse(404, {})])
    with patch("httpx.AsyncClient.post", new=post_404):
        vec2 = await embedder_404.embed("fallback")
    assert len(vec2) == 256


def run() -> None:
    asyncio.run(run_async())


if __name__ == "__main__":
    run()
