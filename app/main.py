import asyncio
import concurrent.futures
import json
import logging
import re
import threading
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.core.domain_config import load_domain_config
from app.core.meta_router import MetaRouter
from app.core.settings import get_settings
from app.observability.dashboard import build_dashboard_summary, build_dashboard_trends
from app.observability.trace import get_trace_id, new_trace_id, set_trace_id, write_trace_event
from app.production.controls import check_rate_limit, load_checkpoint, persist_checkpoint, select_release_bucket
from app.rag.chunker import semantic_chunk_with_sliding_window
from app.rag.file_parser import ALLOWED_UPLOAD_SUFFIXES, read_text_with_meta
from app.schemas import (
    GenerateRequest,
    GenerateResponse,
    RagDocumentItem,
    RagDocumentListResponse,
    RagUploadTaskStartResponse,
    RagUploadTaskStatusResponse,
    RagUpsertRequest,
    RagUpsertResponse,
)
from app.security.guard import detect_blocked_pattern, parse_block_patterns, verify_bearer_token, write_audit_event
from app.services.local_llm import get_last_llm_debug
from app.workflow.graph import get_memory_orchestrator, run_workflow

settings = get_settings()
app = FastAPI(title=settings.app_name)
router = MetaRouter(default_domain="default")
logger = logging.getLogger(__name__)
web_dir = settings.project_root / "web"
if web_dir.exists():
    app.mount("/web", StaticFiles(directory=str(web_dir), html=True), name="web")

UPLOAD_TASK_TTL_SECONDS = 3600
upload_tasks: dict[str, dict[str, Any]] = {}


def _chunk_text(text: str) -> list[str]:
    return semantic_chunk_with_sliding_window(
        text=text,
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
        min_chunk_size=settings.rag_chunk_min_size,
        strategy=settings.rag_chunk_strategy,
        spacy_model_zh=settings.rag_spacy_model_zh,
        spacy_model_en=settings.rag_spacy_model_en,
    )


async def _upsert_document_text(
    domain: str,
    source: str,
    text: str,
    doc_id: str | None = None,
) -> tuple[int, int]:
    chunks = _chunk_text(text)
    if not chunks:
        return 0, 0
    return await _upsert_document_chunks(domain=domain, source=source, chunks=chunks, doc_id=doc_id)


async def _upsert_document_chunks(
    domain: str,
    source: str,
    chunks: list[str],
    doc_id: str | None = None,
    progress_hook: Callable[[int, int, str], None] | None = None,
) -> tuple[int, int]:
    cfg = load_domain_config(domain)
    memory = get_memory_orchestrator(embed_base_url=cfg.model_policy.base_url)
    if not chunks:
        return 0, 0
    embeddings = []
    total_chunks = len(chunks)
    for idx, chunk in enumerate(chunks, start=1):
        vec = await memory.embedder.embed(chunk)
        embeddings.append(vec)
        if progress_hook and (idx == 1 or idx == total_chunks or idx % max(1, total_chunks // 20) == 0):
            progress_hook(idx, total_chunks, "embedding")
    if progress_hook:
        progress_hook(total_chunks, total_chunks, "upserting")
    info = memory.rag_store.upsert_chunks(
        domain=domain,
        chunks=chunks,
        source=source,
        embeddings=embeddings,
        doc_id=doc_id,
        kind="doc",
        user_id="",
    )
    return 1, int(info.get("chunks", 0))


def _cleanup_upload_tasks() -> None:
    now = time.time()
    expired = [task_id for task_id, row in upload_tasks.items() if now - float(row.get("updated_at", 0.0)) > UPLOAD_TASK_TTL_SECONDS]
    for task_id in expired:
        upload_tasks.pop(task_id, None)


def _new_upload_task(domain: str, total_files: int) -> str:
    _cleanup_upload_tasks()
    task_id = f"upload-{uuid4().hex}"
    upload_tasks[task_id] = {
        "task_id": task_id,
        "status": "pending",
        "stage": "已接收上传请求",
        "progress": 0,
        "message": "等待后端处理",
        "indexed_docs": 0,
        "indexed_chunks": 0,
        "completed": False,
        "error": "",
        "domain": domain,
        "total_files": total_files,
        "updated_at": time.time(),
        "debug": {
            "current_file": "",
            "file_index": 0,
            "total_files": total_files,
            "chunk_total": 0,
            "chunk_done": 0,
            "start_at": time.time(),
            "last_event": "task_created",
            "elapsed_ms": 0,
        },
    }
    return task_id


def _update_upload_task(task_id: str, **kwargs: Any) -> None:
    row = upload_tasks.get(task_id)
    if row is None:
        return
    if "debug" in kwargs and isinstance(kwargs["debug"], dict):
        debug_obj = row.get("debug") if isinstance(row.get("debug"), dict) else {}
        debug_obj.update(kwargs["debug"])
        kwargs["debug"] = debug_obj
    row.update(kwargs)
    debug_obj = row.get("debug") if isinstance(row.get("debug"), dict) else {}
    start_at = float(debug_obj.get("start_at", row.get("updated_at", time.time())))
    debug_obj["elapsed_ms"] = int((time.time() - start_at) * 1000)
    row["debug"] = debug_obj
    row["updated_at"] = time.time()


def _task_status_response(task_id: str) -> RagUploadTaskStatusResponse:
    row = upload_tasks.get(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="upload_task_not_found")
    return RagUploadTaskStatusResponse.model_validate(row)


async def _run_upload_task(
    task_id: str,
    domain: str,
    source: str,
    files_meta: list[dict[str, str]],
) -> None:
    total_files = len(files_meta)
    total_steps = max(1, total_files * 3)
    done_steps = 0
    indexed_docs = 0
    indexed_chunks = 0
    _update_upload_task(
        task_id,
        status="running",
        stage="正在解析文档",
        progress=5,
        message="开始处理文件",
        debug={"last_event": "task_started"},
    )
    logger.info("rag_upload_task started task_id=%s domain=%s total_files=%s", task_id, domain, total_files)
    try:
        for idx, item in enumerate(files_meta, start=1):
            file_path = Path(item["tmp_path"])
            file_name = item["filename"]
            stage_prefix = f"文件 {idx}/{total_files}: {file_name}"
            file_start_ts = time.time()
            file_progress_start = 5 + int((idx - 1) * 90 / total_files)
            file_progress_end = 5 + int(idx * 90 / total_files)
            _update_upload_task(
                task_id,
                stage="正在解析文档",
                message=f"{stage_prefix} - 解析中",
                progress=max(file_progress_start, min(95, int(done_steps / total_steps * 100))),
                debug={"current_file": file_name, "file_index": idx, "last_event": "parsing_started"},
            )
            text, parse_meta = read_text_with_meta(file_path)
            text = text.strip()
            done_steps += 1
            if not text:
                _update_upload_task(
                    task_id,
                    message=f"{stage_prefix} - 无有效文本，已跳过",
                    debug={"last_event": "parsing_empty", "parse_meta": parse_meta},
                )
                done_steps += 2
                continue
            _update_upload_task(
                task_id,
                debug={"parse_meta": parse_meta, "pdf_layout_used": bool(parse_meta.get("layout_used", False))},
            )

            _update_upload_task(
                task_id,
                stage="正在分块",
                message=f"{stage_prefix} - 分块中",
                progress=min(95, int(done_steps / total_steps * 100)),
                debug={"last_event": "chunking_started"},
            )
            chunks = _chunk_text(text)
            done_steps += 1
            if not chunks:
                _update_upload_task(
                    task_id,
                    message=f"{stage_prefix} - 分块为空，已跳过",
                    debug={"last_event": "chunking_empty"},
                )
                done_steps += 1
                continue
            _update_upload_task(
                task_id,
                debug={"chunk_total": len(chunks), "chunk_done": 0, "last_event": "chunking_done"},
            )

            _update_upload_task(
                task_id,
                stage="正在上传向量",
                message=f"{stage_prefix} - 上传中",
                progress=min(95, int(done_steps / total_steps * 100)),
                debug={"last_event": "vector_upload_started"},
            )
            resolved_source = f"{source}:{file_name}" if source else file_name

            def _hook(done: int, total: int, phase: str) -> None:
                local_ratio = 0.0 if total <= 0 else done / total
                local_progress = file_progress_start + int((file_progress_end - file_progress_start) * local_ratio)
                phase_text = "向量编码" if phase == "embedding" else "写入向量库"
                _update_upload_task(
                    task_id,
                    progress=max(5, min(95, local_progress)),
                    message=f"{stage_prefix} - {phase_text} {done}/{total}",
                    debug={"chunk_done": done, "chunk_total": total, "last_event": f"{phase}_{done}_{total}"},
                )

            docs, chunks_count = await _upsert_document_chunks(
                domain=domain,
                source=resolved_source,
                chunks=chunks,
                doc_id=f"upload:{uuid4().hex}",
                progress_hook=_hook,
            )
            indexed_docs += docs
            indexed_chunks += chunks_count
            done_steps += 1
            _update_upload_task(
                task_id,
                indexed_docs=indexed_docs,
                indexed_chunks=indexed_chunks,
                progress=min(95, int(done_steps / total_steps * 100)),
                message=f"{stage_prefix} - 完成",
                debug={
                    "last_event": "file_done",
                    "file_elapsed_ms": int((time.time() - file_start_ts) * 1000),
                    "chunk_done": len(chunks),
                    "chunk_total": len(chunks),
                    "parse_meta": parse_meta,
                },
            )
            logger.info(
                "rag_upload_task file_done task_id=%s file=%s chunks=%s elapsed_ms=%s parser=%s layout_used=%s",
                task_id,
                file_name,
                len(chunks),
                int((time.time() - file_start_ts) * 1000),
                parse_meta.get("pdf_parser") or parse_meta.get("parser") or "",
                bool(parse_meta.get("layout_used", False)),
            )
        _update_upload_task(
            task_id,
            status="completed",
            stage="处理完成",
            progress=100,
            message="文档上传与向量化已完成",
            completed=True,
            indexed_docs=indexed_docs,
            indexed_chunks=indexed_chunks,
            error="",
            debug={"last_event": "task_completed"},
        )
        logger.info(
            "rag_upload_task completed task_id=%s indexed_docs=%s indexed_chunks=%s",
            task_id,
            indexed_docs,
            indexed_chunks,
        )
    except Exception as exc:
        _update_upload_task(
            task_id,
            status="failed",
            stage="处理失败",
            progress=100,
            message="文档处理失败",
            completed=True,
            error=str(exc),
            indexed_docs=indexed_docs,
            indexed_chunks=indexed_chunks,
            debug={"last_event": "task_failed"},
        )
        logger.exception("rag_upload_task failed task_id=%s err=%s", task_id, exc)
    finally:
        for item in files_meta:
            Path(item["tmp_path"]).unlink(missing_ok=True)


def _run_upload_task_in_thread(
    task_id: str,
    domain: str,
    source: str,
    files_meta: list[dict[str, str]],
) -> None:
    asyncio.run(_run_upload_task(task_id=task_id, domain=domain, source=source, files_meta=files_meta))


def _build_rag_doc_items(domain: str) -> list[RagDocumentItem]:
    cfg = load_domain_config(domain)
    memory = get_memory_orchestrator(embed_base_url=cfg.model_policy.base_url)
    rows = memory.rag_store.list_document_collections(domain=domain)
    items = [
        RagDocumentItem(
            doc_id=str(row.get("doc_id") or "unknown"),
            source=str(row.get("source") or "unknown"),
            chunks=int(row.get("chunks") or 0),
            created_at=float(row.get("created_at") or 0.0),
            updated_at=float(row.get("updated_at") or 0.0),
        )
        for row in rows
    ]
    items.sort(key=lambda x: x.updated_at, reverse=True)
    return items


def _extract_summary(output_text: str) -> str:
    def _strip_code_fence(text: str) -> str:
        t = text.strip()
        if t.startswith("```"):
            t = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", t)
            t = re.sub(r"\n?```$", "", t)
        return t.strip()

    def _extract_json_object(text: str) -> str | None:
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    current = _strip_code_fence(str(output_text or ""))
    for _ in range(4):
        if not current:
            return ""
        candidate = current
        parsed = None
        try:
            parsed = json.loads(candidate)
        except Exception:
            obj = _extract_json_object(candidate)
            if obj:
                try:
                    parsed = json.loads(obj)
                except Exception:
                    parsed = None
        if parsed is None:
            break
        if isinstance(parsed, dict):
            summary = str(parsed.get("summary", "")).strip()
            if summary:
                current = _strip_code_fence(summary)
                continue
            break
        if isinstance(parsed, str):
            current = _strip_code_fence(parsed)
            continue
        break
    return current.strip()


def _tokenize_text(text: str) -> list[str]:
    if not text:
        return []
    tokens = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\s]", text)
    return tokens if tokens else [text]


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or new_trace_id()
    set_trace_id(trace_id)
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except asyncio.CancelledError:
        return Response(status_code=499)
    duration_ms = (time.perf_counter() - started_at) * 1000
    response.headers["x-trace-id"] = trace_id
    write_trace_event(
        {
            "trace_id": trace_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
        }
    )
    return response


@app.get("/health")
async def health() -> dict:
    """存活检查。"""

    return {"status": "ok", "service": settings.app_name}


@app.get("/ready")
async def ready() -> dict:
    """就绪检查。"""

    return {"status": "ready", "env": settings.app_env}


@app.get("/v1/dashboard/summary")
async def dashboard_summary() -> dict:
    return build_dashboard_summary(settings)


@app.get("/v1/dashboard/trends")
async def dashboard_trends(points: int = 24) -> dict:
    safe_points = max(6, min(points, 120))
    return build_dashboard_trends(settings, points=safe_points)


@app.get("/@vite/client")
async def vite_client_stub() -> Response:
    return Response(status_code=204)


@app.get("/favicon.ico")
async def favicon_stub() -> Response:
    # Browser probes favicon by default; return 204 to avoid noisy 404 logs.
    return Response(status_code=204)


@app.get("/v1/debug/llm-last")
async def debug_llm_last(request: Request) -> dict:
    if not settings.debug_local_enabled:
        raise HTTPException(status_code=404, detail="debug_disabled")
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "localhost", "::1", "testclient"}:
        raise HTTPException(status_code=403, detail="debug_local_only")
    return {"debug_enabled": True, "last_llm": get_last_llm_debug()}


async def _execute_generate(req: GenerateRequest, request: Request) -> GenerateResponse:
    trace_id = get_trace_id()
    blocked = detect_blocked_pattern(req.task, parse_block_patterns(settings.input_block_patterns))
    if blocked:
        write_audit_event(
            settings,
            {"trace_id": trace_id, "action": "generate", "decision": "blocked", "reason": f"blocked_pattern:{blocked}"},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"blocked_pattern:{blocked}")
    if settings.security_enabled:
        ok = verify_bearer_token(request.headers.get("Authorization"), settings.auth_bearer_token)
        if not ok:
            write_audit_event(
                settings,
                {"trace_id": trace_id, "action": "generate", "decision": "deny", "reason": "auth_failed"},
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth_failed")
    client_id = request.client.host if request.client else "unknown"
    if not check_rate_limit(client_id, settings.rate_limit_per_minute, window_seconds=60):
        write_audit_event(
            settings,
            {"trace_id": trace_id, "action": "generate", "decision": "deny", "reason": "rate_limited"},
        )
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate_limited")
    release_bucket = select_release_bucket(trace_id, settings.release_canary_percent)
    resolved_session = req.session_id or f"trace:{trace_id}"
    resolved_user = req.user_id or "anonymous"
    ctx = router.resolve(
        req.domain,
        req.task,
        session_id=resolved_session,
        user_id=resolved_user,
        use_memory=req.use_memory,
        top_k=req.top_k,
    )
    try:
        result = await run_workflow(ctx)
        summary_preview = ""
        try:
            parsed = json.loads(result.output)
            if isinstance(parsed, dict):
                summary_preview = str(parsed.get("summary", ""))[:180]
        except Exception:
            summary_preview = str(result.output)[:180]
        logger.info(
            "generate_result trace_id=%s model=%s confidence=%.3f retry=%s reranker=%s doc_candidates=%s bge_used=%s bge_latency_ms=%s bge_reason=%s bge_backend=%s summary_preview=%s",
            trace_id,
            result.model,
            result.confidence,
            result.retry_count,
            result.memory_meta.get("reranker_type", ""),
            result.memory_meta.get("doc_candidates", 0),
            bool((result.memory_meta.get("doc_rerank", {}) or {}).get("used_bge", False)),
            int((result.memory_meta.get("doc_rerank", {}) or {}).get("bge_latency_ms", 0)),
            str((((result.memory_meta.get("doc_rerank", {}) or {}).get("bge_meta", {}) or {}).get("reason", ""))),
            str((((result.memory_meta.get("doc_rerank", {}) or {}).get("bge_meta", {}) or {}).get("backend", ""))),
            summary_preview,
        )
        response = GenerateResponse(
            domain=result.domain,
            model=result.model,
            prompt=result.prompt,
            output=result.output,
            confidence=result.confidence,
            retry_count=result.retry_count,
            tool_results=result.tool_results,
            trace_id=trace_id,
            release_bucket=release_bucket,
            memory_meta=result.memory_meta,
            process=result.process,
        )
        persist_checkpoint(settings, response.model_dump())
        write_audit_event(
            settings,
            {"trace_id": trace_id, "action": "generate", "decision": "allow", "release_bucket": release_bucket},
        )
        return response
    except Exception as exc:
        if settings.rollback_enabled:
            checkpoint = load_checkpoint(settings)
            if checkpoint:
                checkpoint["trace_id"] = trace_id
                checkpoint["release_bucket"] = "rollback"
                write_audit_event(
                    settings,
                    {"trace_id": trace_id, "action": "generate", "decision": "rollback", "reason": str(exc)},
                )
                return GenerateResponse.model_validate(checkpoint)
        write_audit_event(
            settings,
            {"trace_id": trace_id, "action": "generate", "decision": "error", "reason": str(exc)},
        )
        raise


@app.post("/v1/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest, request: Request) -> GenerateResponse:
    """执行工作流并返回生成结果。"""

    return await _execute_generate(req, request)


@app.post("/v1/generate/stream")
async def generate_stream(req: GenerateRequest, request: Request) -> StreamingResponse:
    async def event_gen():
        yield "event: stage\ndata: {\"stage\":\"thinking\",\"message\":\"正在检索与规划\"}\n\n"
        try:
            response = await _execute_generate(req, request)
        except HTTPException as exc:
            payload = json.dumps({"message": str(exc.detail), "status_code": exc.status_code}, ensure_ascii=False)
            yield f"event: error\ndata: {payload}\n\n"
            yield "event: done\ndata: {\"ok\":false}\n\n"
            return
        except Exception as exc:
            payload = json.dumps({"message": str(exc)}, ensure_ascii=False)
            yield f"event: error\ndata: {payload}\n\n"
            yield "event: done\ndata: {\"ok\":false}\n\n"
            return

        process_payload = json.dumps(response.process or {}, ensure_ascii=False)
        meta_payload = json.dumps(
            {
                "trace_id": response.trace_id,
                "release_bucket": response.release_bucket,
                "model": response.model,
                "memory_meta": response.memory_meta,
            },
            ensure_ascii=False,
        )
        yield f"event: process\ndata: {process_payload}\n\n"
        yield f"event: meta\ndata: {meta_payload}\n\n"
        yield "event: stage\ndata: {\"stage\":\"answering\",\"message\":\"正在生成最终回复\"}\n\n"
        summary = _extract_summary(response.output)
        for token in _tokenize_text(summary):
            payload = json.dumps({"token": token}, ensure_ascii=False)
            yield f"event: token\ndata: {payload}\n\n"
            await asyncio.sleep(0.008)
        final_payload = json.dumps(response.model_dump(), ensure_ascii=False)
        yield f"event: result\ndata: {final_payload}\n\n"
        yield "event: done\ndata: {\"ok\":true}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.post("/v1/rag/documents", response_model=RagUpsertResponse)
async def upsert_rag_documents(req: RagUpsertRequest) -> RagUpsertResponse:
    indexed_docs = 0
    indexed_chunks = 0
    for doc in req.documents:
        docs, chunks = await _upsert_document_text(
            domain=req.domain,
            source=doc.source,
            text=doc.text,
            doc_id=doc.doc_id,
        )
        indexed_docs += docs
        indexed_chunks += chunks
    return RagUpsertResponse(domain=req.domain, indexed_docs=indexed_docs, indexed_chunks=indexed_chunks)


@app.post("/v1/rag/upload", response_model=RagUpsertResponse)
async def upload_rag_documents(
    domain: str = Form(default="default"),
    source: str = Form(default="upload"),
    files: list[UploadFile] = File(default_factory=list),
) -> RagUpsertResponse:
    indexed_docs = 0
    indexed_chunks = 0
    for upload in files:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in ALLOWED_UPLOAD_SUFFIXES:
            continue
        data = await upload.read()
        if not data:
            continue
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            text, _ = read_text_with_meta(tmp_path)
            text = text.strip()
        finally:
            tmp_path.unlink(missing_ok=True)
        if not text:
            continue
        resolved_source = f"{source}:{upload.filename}" if source else (upload.filename or "upload")
        docs, chunks = await _upsert_document_text(
            domain=domain,
            source=resolved_source,
            text=text,
            doc_id=f"upload:{uuid4().hex}",
        )
        indexed_docs += docs
        indexed_chunks += chunks
    return RagUpsertResponse(domain=domain, indexed_docs=indexed_docs, indexed_chunks=indexed_chunks)


@app.post("/v1/rag/upload/tasks", response_model=RagUploadTaskStartResponse)
async def create_upload_rag_task(
    domain: str = Form(default="default"),
    source: str = Form(default="upload"),
    files: list[UploadFile] = File(default_factory=list),
) -> RagUploadTaskStartResponse:
    files_meta: list[dict[str, str]] = []
    for upload in files:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in ALLOWED_UPLOAD_SUFFIXES:
            continue
        data = await upload.read()
        if not data:
            continue
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        files_meta.append(
            {
                "tmp_path": str(tmp_path),
                "filename": upload.filename or f"upload-{uuid4().hex}{suffix}",
            }
        )
    if not files_meta:
        raise HTTPException(status_code=400, detail="no_valid_files")
    task_id = _new_upload_task(domain=domain, total_files=len(files_meta))
    worker = threading.Thread(
        target=_run_upload_task_in_thread,
        kwargs={"task_id": task_id, "domain": domain, "source": source, "files_meta": files_meta},
        daemon=True,
    )
    worker.start()
    row = upload_tasks[task_id]
    return RagUploadTaskStartResponse(
        task_id=task_id,
        status=str(row["status"]),
        stage=str(row["stage"]),
        progress=int(row["progress"]),
    )


@app.get("/v1/rag/upload/tasks/{task_id}", response_model=RagUploadTaskStatusResponse)
async def get_upload_rag_task_status(task_id: str) -> RagUploadTaskStatusResponse:
    return _task_status_response(task_id)


@app.get("/v1/rag/documents", response_model=RagDocumentListResponse)
async def list_rag_documents(domain: str = "default") -> RagDocumentListResponse:
    try:
        list_timeout = max(4.0, float(settings.qdrant_timeout_seconds) + 2.0)
        items = await asyncio.wait_for(asyncio.to_thread(_build_rag_doc_items, domain), timeout=list_timeout)
    except (asyncio.TimeoutError, concurrent.futures.TimeoutError):
        logger.warning("list_rag_documents timeout domain=%s", domain)
        items = []
    except Exception as exc:
        logger.warning("list_rag_documents failed domain=%s err=%s", domain, exc)
        items = []
    return RagDocumentListResponse(domain=domain, total_docs=len(items), items=items)


@app.get("/")
async def web_index():
    if not web_dir.exists():
        raise HTTPException(status_code=404, detail="web_not_built")
    index_file = Path(web_dir) / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="web_index_not_found")
    return FileResponse(str(index_file))
