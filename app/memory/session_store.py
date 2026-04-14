import json
import time
from pathlib import Path
from typing import Any

from app.core.settings import get_settings


class SessionStore:
    def __init__(self):
        settings = get_settings()
        self.window_size = settings.memory_window_size
        self.ttl_seconds = settings.memory_session_ttl_seconds
        self.file_path = settings.project_root / "eval" / "memory" / "sessions.json"
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict[str, Any]:
        if not self.file_path.exists():
            return {}
        try:
            return json.loads(self.file_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        self.file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _prune(self, data: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        out: dict[str, Any] = {}
        for sid, item in data.items():
            last_ts = float(item.get("last_ts", 0))
            if now - last_ts <= self.ttl_seconds:
                out[sid] = item
        return out

    def append_turn(self, session_id: str, role: str, content: str) -> None:
        data = self._prune(self._read())
        row = data.get(session_id, {"summary": "", "turns": [], "last_ts": 0.0})
        turns = row.get("turns", [])
        turns.append({"role": role, "content": content, "ts": time.time()})
        if len(turns) > self.window_size:
            overflow = turns[: len(turns) - self.window_size]
            remain = turns[len(turns) - self.window_size :]
            summary_parts = [f"{x['role']}:{x['content']}" for x in overflow]
            old_summary = row.get("summary", "")
            row["summary"] = (old_summary + " " + " ".join(summary_parts)).strip()[:1000]
            turns = remain
        row["turns"] = turns
        row["last_ts"] = time.time()
        data[session_id] = row
        self._write(data)

    def get_context(self, session_id: str) -> dict[str, Any]:
        data = self._prune(self._read())
        row = data.get(session_id, {"summary": "", "turns": [], "last_ts": 0.0})
        turns = row.get("turns", [])
        turns_text = "\n".join([f"{x['role']}: {x['content']}" for x in turns])
        return {"summary": row.get("summary", ""), "turns": turns, "turns_text": turns_text}
