from app.core.settings import get_settings
from app.security.guard import detect_blocked_pattern, parse_block_patterns, verify_bearer_token, write_audit_event


def run() -> None:
    patterns = parse_block_patterns("rm -rf|drop table")
    assert detect_blocked_pattern("请执行 rm -rf /", patterns) == "rm -rf"
    assert detect_blocked_pattern("正常任务", patterns) == ""
    assert verify_bearer_token("Bearer token123", "token123") is True
    assert verify_bearer_token("Bearer bad", "token123") is False
    settings = get_settings()
    write_audit_event(settings, {"trace_id": "t1", "action": "test", "decision": "allow"})


if __name__ == "__main__":
    run()
