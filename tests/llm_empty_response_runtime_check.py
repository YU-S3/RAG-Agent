from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


def run() -> None:
    client = TestClient(app)
    fake_invoke = AsyncMock(return_value=type("X", (), {"content": "   ", "model": "mock"})())
    with patch("app.services.local_llm.LocalLLMClient.invoke", new=fake_invoke):
        response = client.post("/v1/generate", json={"domain": "default", "task": "测试空输出"})
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "degraded-fallback"
    assert "模型暂不可用" in body["output"]


if __name__ == "__main__":
    run()
