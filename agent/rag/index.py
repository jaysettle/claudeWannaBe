"""
Stub index builder using on-disk JSON to represent a vector store placeholder.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict


def save_index(path: Path, entries: List[Dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def load_index(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))
