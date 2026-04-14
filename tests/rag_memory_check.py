from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


def run() -> None:
    client = TestClient(app)
    upsert = client.post(
        "/v1/rag/documents",
        json={
            "domain": "default",
            "documents": [
                {
                    "source": "manual",
                    "text": "RAG是一种结合检索与生成的方法，可提升答案可信度。",
                }
            ],
        },
    )
    assert upsert.status_code == 200
    fake = AsyncMock(return_value=type("X", (), {"content": "{\"summary\":\"ok\"}", "model": "mock"})())
    with patch("app.services.local_llm.LocalLLMClient.invoke", new=fake):
        first = client.post(
            "/v1/generate",
            json={
                "domain": "default",
                "task": "什么是RAG",
                "session_id": "s-rag",
                "user_id": "u-rag",
                "use_memory": True,
                "top_k": 4,
            },
        )
        second = client.post(
            "/v1/generate",
            json={
                "domain": "default",
                "task": "继续总结上一次回答",
                "session_id": "s-rag",
                "user_id": "u-rag",
                "use_memory": True,
                "top_k": 4,
            },
        )
    assert first.status_code == 200
    assert second.status_code == 200
    body = second.json()
    assert "memory_meta" in body
    assert body["memory_meta"].get("enabled") is True


if __name__ == "__main__":
    run()
