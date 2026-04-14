from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.schemas import GenerateResponse


def run() -> None:
    client = TestClient(app)

    async def fake_execute_generate(req, request):
        return GenerateResponse(
            domain="default",
            model="mock-model",
            prompt="p",
            output='{"summary":"这是流式返回测试"}',
            confidence=0.9,
            retry_count=0,
            tool_results=[],
            trace_id="trace-test",
            release_bucket="stable",
            memory_meta={"enabled": True, "short_turns": 1, "rag_hits": 2, "long_hits": 0},
            process={"thinking_steps": ["step1"], "tool_calls": []},
        )

    with patch("app.main._execute_generate", new=fake_execute_generate):
        resp = client.post(
            "/v1/generate/stream",
            json={"domain": "default", "task": "hello", "use_memory": True, "top_k": 4},
        )
    assert resp.status_code == 200
    text = resp.text
    assert "event: stage" in text
    assert "event: token" in text
    assert "event: result" in text
    assert "event: done" in text


if __name__ == "__main__":
    run()
