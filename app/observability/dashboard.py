import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.settings import Settings


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            rows.append(json.loads(text))
        except Exception:
            continue
    return rows


def build_dashboard_summary(settings: Settings) -> dict[str, Any]:
    eval_dir = settings.project_root / "eval"
    trace_rows = _read_jsonl(eval_dir / "trace_events.jsonl")
    audit_rows = _read_jsonl(eval_dir / "audit_events.jsonl")
    total_requests = len([x for x in trace_rows if x.get("path") == "/v1/generate"])
    errors = len([x for x in trace_rows if int(x.get("status_code", 0)) >= 400 and x.get("path") == "/v1/generate"])
    avg_latency = 0.0
    if total_requests:
        latencies = [float(x.get("duration_ms", 0.0)) for x in trace_rows if x.get("path") == "/v1/generate"]
        avg_latency = round(sum(latencies) / max(1, len(latencies)), 2)
    denied = len([x for x in audit_rows if x.get("decision") in {"deny", "blocked"}])
    rollback = len([x for x in audit_rows if x.get("decision") == "rollback"])
    return {
        "total_requests": total_requests,
        "error_count": errors,
        "avg_latency_ms": avg_latency,
        "audit_denied_count": denied,
        "rollback_count": rollback,
        "trace_events": len(trace_rows),
        "audit_events": len(audit_rows),
    }


def build_dashboard_trends(settings: Settings, points: int = 24) -> dict[str, Any]:
    eval_dir = settings.project_root / "eval"
    trace_rows = _read_jsonl(eval_dir / "trace_events.jsonl")
    generate_rows = [x for x in trace_rows if x.get("path") == "/v1/generate"]
    buckets: dict[str, dict[str, float]] = {}
    for row in generate_rows:
        ts = float(row.get("ts", 0.0))
        minute = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
        item = buckets.get(minute, {"count": 0.0, "errors": 0.0, "latency_sum": 0.0})
        item["count"] += 1
        if int(row.get("status_code", 0)) >= 400:
            item["errors"] += 1
        item["latency_sum"] += float(row.get("duration_ms", 0.0))
        buckets[minute] = item
    labels = sorted(buckets.keys())[-points:]
    request_series: list[int] = []
    error_series: list[int] = []
    latency_series: list[float] = []
    for label in labels:
        item = buckets[label]
        request_series.append(int(item["count"]))
        error_series.append(int(item["errors"]))
        avg = 0.0 if item["count"] <= 0 else round(item["latency_sum"] / item["count"], 2)
        latency_series.append(avg)
    return {
        "labels": labels,
        "request_series": request_series,
        "error_series": error_series,
        "latency_series": latency_series,
    }
