from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ..core.safety import Safety


def make(safety: Safety):
    def run_python(args: str) -> str:
        payload = json.loads(args)
        path = Path(payload["path"])
        safety.check_path(path)
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=30)
        return result.stdout + result.stderr

    schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    return {"run_python": schema}, {"run_python": run_python}
