import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

# Ensure `python eval/run_eval.py` can import project package from repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app


def _load_cases(file_path: Path) -> list[dict]:
    items: list[dict] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        row = line.strip()
        if not row:
            continue
        items.append(json.loads(row))
    return items


def run() -> None:
    dataset = Path("eval/datasets/basic_eval.jsonl")
    report_path = Path("eval/reports/latest_eval_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    cases = _load_cases(dataset)
    client = TestClient(app)
    fake = AsyncMock(return_value=type("X", (), {"content": "{\"summary\":\"ok\"}", "model": "mock-eval"})())
    passed = 0
    details: list[dict] = []
    with patch("app.services.local_llm.LocalLLMClient.invoke", new=fake):
        for case in cases:
            response = client.post(
                "/v1/generate",
                json={"domain": case["domain"], "task": case["task"]},
            )
            ok = response.status_code == 200 and case["expected_contains"] in response.text
            if ok:
                passed += 1
            details.append({"id": case["id"], "ok": ok, "status_code": response.status_code})
    total = len(cases)
    pass_rate = 0.0 if total == 0 else passed / total
    threshold = float(os.getenv("EVAL_PASS_THRESHOLD", "1.0"))
    report = {
        "total": total,
        "passed": passed,
        "pass_rate": pass_rate,
        "threshold": threshold,
        "details": details,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if pass_rate < threshold:
        raise SystemExit(1)


if __name__ == "__main__":
    run()
