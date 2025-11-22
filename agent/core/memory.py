"""
Memory manager providing short-term buffer and long-term persistence (SQLite/JSON placeholder).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict
import logging


class Memory:
    def __init__(self, data_dir: Path):
        self.buffer: List[Dict] = []
        self.long_term_path = data_dir / "memory.json"
        self.long_term_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.long_term_path.exists():
            self.long_term_path.write_text("[]", encoding="utf-8")
        self.logger = logging.getLogger(__name__)

    def add(self, role: str, content: str):
        self.buffer.append({"role": role, "content": content})
        self.logger.debug("Buffered message role=%s", role)

    def summarize_buffer(self) -> str:
        # Placeholder simple join; replace with LLM-based summarization.
        return "\n".join(f"{m['role']}: {m['content']}" for m in self.buffer)

    def persist_summary(self):
        data = json.loads(self.long_term_path.read_text(encoding="utf-8"))
        data.append({"summary": self.summarize_buffer()})
        self.long_term_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.buffer.clear()

    def load_long_term(self) -> List[Dict]:
        return json.loads(self.long_term_path.read_text(encoding="utf-8"))
