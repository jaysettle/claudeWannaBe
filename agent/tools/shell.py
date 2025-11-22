from __future__ import annotations

import json
import subprocess

from ..core.safety import Safety


def make(safety: Safety):
    def run_shell(args: str) -> str:
        payload = json.loads(args)
        cmd = payload["command"]
        safety.check_command(cmd)
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        return result.stdout + result.stderr

    schema = {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    }
    return {"run_shell": schema}, {"run_shell": run_shell}
