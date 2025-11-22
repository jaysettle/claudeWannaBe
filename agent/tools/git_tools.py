from __future__ import annotations

import subprocess


def make():
    def git_status(args: str) -> str:
        result = subprocess.run(["git", "status", "-sb"], capture_output=True, text=True)
        return result.stdout + result.stderr

    schema = {"type": "object", "properties": {}, "required": []}
    return {"git_status": schema}, {"git_status": git_status}
