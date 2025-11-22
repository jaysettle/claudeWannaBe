from __future__ import annotations

from pathlib import Path

from ..core.safety import Safety


def make(safety: Safety):
    def write_file(args: str) -> str:
        import json
        payload = json.loads(args)
        path = Path(payload["path"])
        safety.check_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload["content"], encoding="utf-8")
        return f"wrote {path}"

    def read_file(args: str) -> str:
        import json
        payload = json.loads(args)
        path = Path(payload["path"])
        safety.check_path(path)
        return path.read_text(encoding="utf-8")

    schemas = {
        "write_file": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
        "read_file": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    }

    return schemas, {"write_file": write_file, "read_file": read_file}
