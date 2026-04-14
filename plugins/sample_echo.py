import json
import sys


def main() -> int:
    task = " ".join(sys.argv[1:]).strip()
    print(json.dumps({"plugin": "sample.echo", "task": task, "message": f"echo:{task}"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
