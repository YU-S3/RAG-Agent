import time

from fastapi.testclient import TestClient

from app.main import app


def run() -> None:
    client = TestClient(app)
    start = client.post(
        "/v1/rag/upload/tasks",
        data={"domain": "default", "source": "progress-test"},
        files={"files": ("progress.txt", "这是上传进度测试文档。包含多句文本以触发处理步骤。", "text/plain")},
    )
    assert start.status_code == 200
    task_id = start.json().get("task_id")
    assert task_id

    done = False
    status_body = {}
    for _ in range(600):
        status_resp = client.get(f"/v1/rag/upload/tasks/{task_id}")
        assert status_resp.status_code == 200
        status_body = status_resp.json()
        assert "stage" in status_body
        assert "progress" in status_body
        if status_body.get("completed"):
            done = True
            break
        time.sleep(0.1)
    assert done is True
    assert status_body.get("status") == "completed"
    assert int(status_body.get("indexed_docs", 0)) >= 1
    assert int(status_body.get("indexed_chunks", 0)) >= 1


if __name__ == "__main__":
    run()
