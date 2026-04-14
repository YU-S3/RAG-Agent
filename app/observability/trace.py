import json
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.settings import get_settings


_trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="")


def new_trace_id() -> str:
    return uuid4().hex


def set_trace_id(trace_id: str) -> None:
    _trace_id_ctx.set(trace_id)


def get_trace_id() -> str:
    return _trace_id_ctx.get()


def _trace_log_path() -> Path:
    settings = get_settings()
    return settings.project_root / "eval" / "trace_events.jsonl"


def write_trace_event(event: dict[str, Any]) -> None:
    payload = {"ts": time.time(), **event}
    path = _trace_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
