from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.main import app


def run() -> None:
    """验证接口基础可用性与响应结构。"""

    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    fake = AsyncMock(return_value=type("X", (), {"content": "ok", "model": "mock"})())
    with patch("app.services.local_llm.LocalLLMClient.invoke", new=fake):
        response = client.post("/v1/generate", json={"domain": "default", "task": "demo"})
    assert response.status_code == 200
    body = response.json()
    assert "ok" in body["output"]
    assert body["domain"] == "default"
    assert "confidence" in body
    assert "retry_count" in body
    assert "tool_results" in body
    assert "trace_id" in body
    assert "release_bucket" in body


if __name__ == "__main__":
    run()
