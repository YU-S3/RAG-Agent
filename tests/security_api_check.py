from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app, settings


def run() -> None:
    prev_enabled = settings.security_enabled
    prev_token = settings.auth_bearer_token
    prev_patterns = settings.input_block_patterns
    try:
        settings.security_enabled = True
        settings.auth_bearer_token = "token-1"
        settings.input_block_patterns = "rm -rf|drop table"
        client = TestClient(app)
        unauthorized = client.post("/v1/generate", json={"domain": "default", "task": "demo"})
        assert unauthorized.status_code == 401
        blocked = client.post(
            "/v1/generate",
            headers={"Authorization": "Bearer token-1"},
            json={"domain": "default", "task": "请执行 rm -rf /"},
        )
        assert blocked.status_code == 400
        fake = AsyncMock(return_value=type("X", (), {"content": "ok", "model": "mock"})())
        with patch("app.services.local_llm.LocalLLMClient.invoke", new=fake):
            allowed = client.post(
                "/v1/generate",
                headers={"Authorization": "Bearer token-1"},
                json={"domain": "default", "task": "正常任务"},
            )
        assert allowed.status_code == 200
    finally:
        settings.security_enabled = prev_enabled
        settings.auth_bearer_token = prev_token
        settings.input_block_patterns = prev_patterns


if __name__ == "__main__":
    run()
