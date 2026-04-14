from app.workflow.quality import validate_output


def run() -> None:
    schema = {"type": "object", "required": ["summary"]}
    fenced = """```json
{"type":"object","required":["summary"],"summary":"你好，我可以帮助你完成任务。"}
```"""
    result = validate_output(fenced, schema)
    assert result.valid is True
    assert "你好" in result.normalized.get("summary", "")

    empty_summary = """{"type":"object","required":["summary"],"summary":"   "}"""
    result2 = validate_output(empty_summary, schema)
    assert result2.valid is True
    assert result2.normalized.get("summary") != ""


if __name__ == "__main__":
    run()
