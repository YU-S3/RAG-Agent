import json
import time
from pathlib import Path
from typing import Any

from app.core.settings import Settings


def parse_block_patterns(raw: str) -> list[str]:
    return [item.strip().lower() for item in raw.split("|") if item.strip()]


def detect_blocked_pattern(task: str, patterns: list[str]) -> str:
    lower_task = task.lower()
    for pattern in patterns:
        if pattern in lower_task:
            return pattern
    return ""


def verify_bearer_token(auth_header: str | None, expected_token: str) -> bool:
    if not auth_header:
        return False
    prefix = "Bearer "
    if not auth_header.startswith(prefix):
        return False
    token = auth_header[len(prefix) :].strip()
    return token == expected_token


def audit_log_path(settings: Settings) -> Path:
    return settings.project_root / "eval" / "audit_events.jsonl"


def write_audit_event(settings: Settings, event: dict[str, Any]) -> None:
    payload = {"ts": time.time(), **event}
    path = audit_log_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
