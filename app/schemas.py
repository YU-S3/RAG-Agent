from typing import Any

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    """文本生成请求。"""

    domain: str = Field(default="default")
    task: str
    session_id: str | None = None
    user_id: str | None = None
    use_memory: bool = True
    top_k: int = Field(default=4, ge=1, le=20)


class GenerateResponse(BaseModel):
    """文本生成响应。"""

    domain: str
    model: str
    prompt: str
    output: str
    confidence: float
    retry_count: int
    tool_results: list[dict]
    trace_id: str
    release_bucket: str
    memory_meta: dict
    process: dict[str, Any] = Field(default_factory=dict)


class RagDocument(BaseModel):
    text: str
    source: str = "manual"
    doc_id: str | None = None


class RagUpsertRequest(BaseModel):
    domain: str = Field(default="default")
    documents: list[RagDocument]


class RagUpsertResponse(BaseModel):
    domain: str
    indexed_docs: int
    indexed_chunks: int


class RagDocumentItem(BaseModel):
    doc_id: str
    source: str
    chunks: int
    created_at: float
    updated_at: float


class RagDocumentListResponse(BaseModel):
    domain: str
    total_docs: int
    items: list[RagDocumentItem]


class RagUploadTaskStartResponse(BaseModel):
    task_id: str
    status: str
    stage: str
    progress: int


class RagUploadTaskStatusResponse(BaseModel):
    task_id: str
    status: str
    stage: str
    progress: int
    message: str
    indexed_docs: int
    indexed_chunks: int
    completed: bool
    error: str
    domain: str
    updated_at: float
    debug: dict[str, Any]
