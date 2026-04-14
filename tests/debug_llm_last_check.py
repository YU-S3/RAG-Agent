from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


class DummyResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http_error:{self.status_code}")

    def json(self) -> dict:
        return self._payload


def run() -> None:
    client = TestClient(app)
    fake_post = AsyncMock(return_value=DummyResponse(200, {"model": "qwen3:8b", "response": "hello", "done_reason": "stop"}))
    with patch("httpx.AsyncClient.post", new=fake_post):
        response = client.post(
            "/v1/generate",
            json={"domain": "default", "task": "debug", "use_memory": False, "top_k": 1},
        )
    assert response.status_code == 200
    debug_resp = client.get("/v1/debug/llm-last")
    assert debug_resp.status_code == 200
    body = debug_resp.json()
    assert body.get("debug_enabled") is True
    assert isinstance(body.get("last_llm"), dict)
    assert body["last_llm"].get("status") in {"ok", "retrying", "failed", "started"}


if __name__ == "__main__":
    run()
