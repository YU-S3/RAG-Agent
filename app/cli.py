import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import httpx
from app.rag.file_parser import read_text_from_file as _shared_read_text_from_file


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _collect_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    files: list[Path] = []
    for ext in ("*.txt", "*.md", "*.rst", "*.py", "*.pdf", "*.docx", "*.doc"):
        files.extend(target.rglob(ext))
    return sorted(set(files))


def _read_pdf_text(file_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        return ""
    try:
        reader = PdfReader(str(file_path))
        chunks: list[str] = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
        return "\n".join(chunks).strip()
    except Exception:
        return ""


def _read_docx_text(file_path: Path) -> str:
    try:
        from docx import Document
    except Exception:
        return ""
    try:
        doc = Document(str(file_path))
        rows = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
        return "\n".join(rows).strip()
    except Exception:
        return ""


def _read_doc_text(file_path: Path) -> str:
    # Legacy .doc best-effort parser: try decoding document bytes with common encodings.
    data = file_path.read_bytes()
    for encoding in ("utf-16le", "utf-8", "gb18030", "latin1"):
        try:
            text = data.decode(encoding, errors="ignore")
        except Exception:
            continue
        cleaned = text.replace("\x00", " ").strip()
        if len(cleaned) >= 40:
            return cleaned
    return ""


def _read_text_from_file(file_path: Path) -> str:
    # Reuse server-side parser to keep CLI/API ingestion behavior consistent.
    return _shared_read_text_from_file(file_path)


class AgentCLI:
    def __init__(self, base_url: str, token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(f"{self.base_url}{path}", headers=self._headers(), json=body)
            resp.raise_for_status()
            return resp.json()

    def run_once(
        self,
        task: str,
        domain: str,
        session_id: str | None,
        user_id: str | None,
        use_memory: bool,
        top_k: int,
    ) -> dict[str, Any]:
        return self._post(
            "/v1/generate",
            {
                "domain": domain,
                "task": task,
                "session_id": session_id,
                "user_id": user_id,
                "use_memory": use_memory,
                "top_k": top_k,
            },
        )

    def rag_upsert(self, domain: str, documents: list[dict[str, Any]]) -> dict[str, Any]:
        return self._post("/v1/rag/documents", {"domain": domain, "documents": documents})


def _session_store_path() -> Path:
    return Path(__file__).resolve().parents[1] / "eval" / "memory" / "sessions.json"


def cmd_session_list() -> int:
    data = _load_json(_session_store_path())
    rows = [{"session_id": sid, "last_ts": v.get("last_ts", 0), "turns": len(v.get("turns", []))} for sid, v in data.items()]
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def cmd_session_show(session_id: str) -> int:
    data = _load_json(_session_store_path())
    print(json.dumps(data.get(session_id, {}), ensure_ascii=False, indent=2))
    return 0


def cmd_session_clear(session_id: str) -> int:
    path = _session_store_path()
    data = _load_json(path)
    data.pop(session_id, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cleared": session_id}, ensure_ascii=False))
    return 0


def cmd_run(args: argparse.Namespace, cli: AgentCLI) -> int:
    if _needs_approval(args.task, args.approval_mode):
        print("任务命中高风险关键词，审批未通过。")
        return 1
    result = cli.run_once(
        task=args.task,
        domain=args.domain,
        session_id=args.session_id,
        user_id=args.user_id,
        use_memory=not args.no_memory,
        top_k=args.top_k,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_chat(args: argparse.Namespace, cli: AgentCLI) -> int:
    print("进入 chat 模式，输入 /exit 结束")
    while True:
        task = input("> ").strip()
        if not task:
            continue
        if task == "/exit":
            break
        if _needs_approval(task, args.approval_mode):
            print("任务命中高风险关键词，审批未通过。")
            continue
        result = cli.run_once(
            task=task,
            domain=args.domain,
            session_id=args.session_id,
            user_id=args.user_id,
            use_memory=not args.no_memory,
            top_k=args.top_k,
        )
        print(result.get("output", ""))
        print(f"trace={result.get('trace_id','')} | bucket={result.get('release_bucket','')}")
    return 0


def cmd_rag_import(args: argparse.Namespace, cli: AgentCLI) -> int:
    target = Path(args.path).resolve()
    files = _collect_files(target)
    docs: list[dict[str, Any]] = []
    for file_path in files:
        text = _read_text_from_file(file_path).strip()
        if not text:
            continue
        docs.append({"source": str(file_path), "text": text})
    if not docs:
        print(json.dumps({"indexed_docs": 0, "indexed_chunks": 0}, ensure_ascii=False))
        return 0
    result = cli.rag_upsert(domain=args.domain, documents=docs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_plugin_list(args: argparse.Namespace) -> int:
    plugin_dir = Path(args.dir).resolve()
    plugin_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for item in plugin_dir.glob("*.json"):
        payload = _load_json(item)
        payload["file"] = str(item)
        rows.append(payload)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def cmd_plugin_run(args: argparse.Namespace) -> int:
    plugin_dir = Path(args.dir).resolve()
    plugin_file = plugin_dir / f"{args.plugin_id}.json"
    payload = _load_json(plugin_file)
    if not payload:
        print(json.dumps({"error": f"plugin_not_found:{args.plugin_id}"}, ensure_ascii=False))
        return 1
    command_template = str(payload.get("command", "")).strip()
    if not command_template:
        print(json.dumps({"error": f"plugin_no_command:{args.plugin_id}"}, ensure_ascii=False))
        return 1
    if _needs_approval(args.task, args.approval_mode):
        print("任务命中高风险关键词，审批未通过。")
        return 1
    command = command_template.replace("{task}", args.task).replace("{base_url}", args.base_url)
    timeout_sec = int(payload.get("timeout_sec", 30))
    try:
        completed = subprocess.run(
            command,
            cwd=str(Path(__file__).resolve().parents[1]),
            shell=True,
            capture_output=True,
            text=True,
            timeout=max(5, min(timeout_sec, 300)),
            check=False,
        )
    except Exception as exc:
        print(json.dumps({"plugin": args.plugin_id, "error": str(exc)}, ensure_ascii=False))
        return 1
    result = {
        "plugin": args.plugin_id,
        "exit_code": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if completed.returncode == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meta-agent")
    parser.add_argument("--base-url", default=os.getenv("AGENT_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--token", default=os.getenv("AGENT_TOKEN", ""))
    parser.add_argument("--domain", default="default")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--no-memory", action="store_true")
    parser.add_argument("--approval-mode", choices=["off", "strict"], default="off")

    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run")
    run_parser.add_argument("task")

    sub.add_parser("chat")

    rag_parser = sub.add_parser("rag-import")
    rag_parser.add_argument("path")

    session_parser = sub.add_parser("session")
    session_sub = session_parser.add_subparsers(dest="session_command", required=True)
    session_sub.add_parser("list")
    show_parser = session_sub.add_parser("show")
    show_parser.add_argument("session_id")
    clear_parser = session_sub.add_parser("clear")
    clear_parser.add_argument("session_id")

    plugin_parser = sub.add_parser("plugin-list")
    plugin_parser.add_argument("--dir", default="plugins")

    plugin_run_parser = sub.add_parser("plugin-run")
    plugin_run_parser.add_argument("plugin_id")
    plugin_run_parser.add_argument("task")
    plugin_run_parser.add_argument("--dir", default="plugins")
    return parser


def _needs_approval(task: str, mode: str) -> bool:
    if mode != "strict":
        return False
    lower = task.lower()
    risk_words = ["rm -rf", "drop table", "shutdown", "format"]
    return any(word in lower for word in risk_words)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cli = AgentCLI(base_url=args.base_url, token=args.token)
    if args.command == "run":
        return cmd_run(args, cli)
    if args.command == "chat":
        return cmd_chat(args, cli)
    if args.command == "rag-import":
        return cmd_rag_import(args, cli)
    if args.command == "plugin-list":
        return cmd_plugin_list(args)
    if args.command == "plugin-run":
        return cmd_plugin_run(args)
    if args.command == "session":
        if args.session_command == "list":
            return cmd_session_list()
        if args.session_command == "show":
            return cmd_session_show(args.session_id)
        if args.session_command == "clear":
            return cmd_session_clear(args.session_id)
    raise SystemExit(2)


if __name__ == "__main__":
    raise SystemExit(main())
