from fastapi.testclient import TestClient

from app.main import app


def run() -> None:
    client = TestClient(app)
    index_resp = client.get("/")
    assert index_resp.status_code == 200
    assert "Meta Agent" in index_resp.text
    js_resp = client.get("/web/app.js")
    assert js_resp.status_code == 200
    vite_resp = client.get("/@vite/client")
    assert vite_resp.status_code == 204
    dashboard_resp = client.get("/v1/dashboard/summary")
    assert dashboard_resp.status_code == 200
    trend_resp = client.get("/v1/dashboard/trends?points=12")
    assert trend_resp.status_code == 200
    docs_resp = client.get("/v1/rag/documents?domain=default")
    assert docs_resp.status_code == 200
    body = dashboard_resp.json()
    assert "total_requests" in body
    assert "avg_latency_ms" in body


if __name__ == "__main__":
    run()
