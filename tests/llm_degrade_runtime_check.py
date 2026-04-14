from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


def run() -> None:
    client = TestClient(app)
    fake_invoke = AsyncMock(side_effect=RuntimeError("llm_down"))
    with patch("app.services.local_llm.LocalLLMClient.invoke", new=fake_invoke):
        response = client.post("/v1/generate", json={"domain": "default", "task": "测试降级"})
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "degraded-fallback"
    assert "summary" in body["output"]


if __name__ == "__main__":
    run()
