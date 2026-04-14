from fastapi.testclient import TestClient

from app.main import app


def run() -> None:
    client = TestClient(app)
    upload = client.post(
        "/v1/rag/upload",
        data={"domain": "default", "source": "web-test"},
        files={"files": ("sample.txt", "这是用于上传接口测试的文档内容。", "text/plain")},
    )
    assert upload.status_code == 200
    upload_body = upload.json()
    assert upload_body["domain"] == "default"
    assert upload_body["indexed_docs"] >= 1
    assert upload_body["indexed_chunks"] >= 1

    listing = client.get("/v1/rag/documents?domain=default")
    assert listing.status_code == 200
    body = listing.json()
    assert body["domain"] == "default"
    assert "total_docs" in body
    assert isinstance(body.get("items"), list)


if __name__ == "__main__":
    run()
