import json
import time
from pathlib import Path
from typing import Any

from app.core.settings import Settings

_RATE_BUCKET: dict[str, list[float]] = {}


def check_rate_limit(client_id: str, limit: int, window_seconds: int = 60) -> bool:
    now = time.time()
    hits = _RATE_BUCKET.get(client_id, [])
    hits = [t for t in hits if now - t <= window_seconds]
    if len(hits) >= limit:
        _RATE_BUCKET[client_id] = hits
        return False
    hits.append(now)
    _RATE_BUCKET[client_id] = hits
    return True


def select_release_bucket(trace_id: str, canary_percent: int) -> str:
    if canary_percent <= 0:
        return "stable"
    bucket = int(trace_id[-2:], 16) % 100
    return "canary" if bucket < canary_percent else "stable"


def checkpoint_path(settings: Settings) -> Path:
    return settings.project_root / "eval" / "checkpoints" / "latest.json"


def persist_checkpoint(settings: Settings, payload: dict[str, Any]) -> None:
    path = checkpoint_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_checkpoint(settings: Settings) -> dict[str, Any] | None:
    path = checkpoint_path(settings)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
