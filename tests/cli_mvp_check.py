import json
from pathlib import Path
from unittest.mock import patch

from app.cli import main


def run() -> None:
    with patch("app.cli.AgentCLI._post", return_value={"ok": True, "trace_id": "t1", "output": "done", "release_bucket": "stable"}):
        assert main(["run", "测试任务"]) == 0
    with patch("app.cli.AgentCLI._post", return_value={"indexed_docs": 1, "indexed_chunks": 2}):
        tmp = Path("eval/tmp_cli_doc.txt")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text("hello rag", encoding="utf-8")
        assert main(["rag-import", str(tmp)]) == 0
    plugin_dir = Path("plugins")
    plugin_dir.mkdir(parents=True, exist_ok=True)
    plugin_file = plugin_dir / "check.json"
    plugin_file.write_text(json.dumps({"id": "check.plugin", "version": "0.0.1"}, ensure_ascii=False), encoding="utf-8")
    assert main(["plugin-list", "--dir", str(plugin_dir)]) == 0
    plugin_file.unlink(missing_ok=True)
    assert main(["plugin-run", "sample.echo", "hello-plugin"]) == 0
    assert main(["--approval-mode", "strict", "run", "rm -rf /"]) == 1


if __name__ == "__main__":
    run()
