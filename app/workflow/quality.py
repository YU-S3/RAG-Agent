import json
from typing import Any

from pydantic import BaseModel


class OutputValidationResult(BaseModel):
    valid: bool
    error: str
    normalized: dict[str, Any]


def _try_parse_json(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    if not raw:
        return None
    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3:
            raw = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        return None
    except Exception:
        return None


def _normalize_output(text: str) -> dict[str, Any]:
    parsed = _try_parse_json(text)
    if parsed is not None:
        if "summary" not in parsed:
            parsed["summary"] = ""
        return parsed
    return {"summary": text.strip()}


def ensure_non_empty_summary(data: dict[str, Any], fallback_text: str) -> dict[str, Any]:
    summary = str(data.get("summary", "")).strip()
    if summary:
        data["summary"] = summary
        return data
    for key, value in data.items():
        if key in {"type", "required", "tool_results"}:
            continue
        if isinstance(value, str) and value.strip():
            data["summary"] = value.strip()
            return data
    fallback = fallback_text.strip()
    data["summary"] = fallback or "已完成任务，但模型未提供可读摘要。"
    return data


def _validate_schema(data: dict[str, Any], schema: dict[str, Any]) -> tuple[bool, str]:
    required = schema.get("required", [])
    for key in required:
        if key not in data:
            return False, f"missing_required_field:{key}"
        value = data.get(key)
        if isinstance(value, str) and not value.strip():
            return False, f"empty_required_field:{key}"
    return True, ""


def validate_output(text: str, schema: dict[str, Any]) -> OutputValidationResult:
    normalized = ensure_non_empty_summary(_normalize_output(text), text)
    valid, error = _validate_schema(normalized, schema)
    return OutputValidationResult(valid=valid, error=error, normalized=normalized)


def build_degraded_output(text: str, error: str) -> dict[str, Any]:
    return {
        "summary": text.strip() or "模型输出为空，已触发降级返回",
        "degraded": True,
        "reason": error or "unknown_error",
    }
