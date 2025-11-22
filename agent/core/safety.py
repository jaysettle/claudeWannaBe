"""
Safety and sandbox checks for tool execution.
"""
from __future__ import annotations

import re
from pathlib import Path


class Safety:
    def __init__(self, workspace: Path, strict: bool = True):
        self.workspace = workspace.resolve()
        self.strict = strict
        self.block_patterns = [
            r"rm -rf /",
            r":\s*>/dev/sd",
        ]

    def check_path(self, path: Path):
        path = path.resolve()
        if self.strict and not str(path).startswith(str(self.workspace)):
            raise PermissionError(f"Path {path} is outside workspace {self.workspace}")

    def check_command(self, cmd: str):
        for pat in self.block_patterns:
            if re.search(pat, cmd):
                raise PermissionError(f"Command blocked by safety rule: {pat}")
