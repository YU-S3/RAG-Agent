from app.core.settings import get_settings
from app.production.controls import check_rate_limit, load_checkpoint, persist_checkpoint, select_release_bucket


def run() -> None:
    assert check_rate_limit("cid", limit=2, window_seconds=60) is True
    assert check_rate_limit("cid", limit=2, window_seconds=60) is True
    assert check_rate_limit("cid", limit=2, window_seconds=60) is False
    assert select_release_bucket("abcdef", 0) == "stable"
    bucket = select_release_bucket("abcdef", 100)
    assert bucket == "canary"
    settings = get_settings()
    persist_checkpoint(
        settings,
        {
            "domain": "default",
            "model": "m",
            "prompt": "p",
            "output": "o",
            "confidence": 0.9,
            "retry_count": 0,
            "tool_results": [],
            "trace_id": "t",
            "release_bucket": "stable",
        },
    )
    checkpoint = load_checkpoint(settings)
    assert checkpoint is not None
    assert checkpoint.get("trace_id") == "t"


if __name__ == "__main__":
    run()
