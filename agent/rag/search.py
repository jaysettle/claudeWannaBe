"""
Simple search over stub index; replace with vector similarity later.
"""
from __future__ import annotations

from typing import List, Dict


def search(index: List[Dict], query: str, limit: int = 5) -> List[Dict]:
    # Placeholder: naive substring filter
    results = [item for item in index if query.lower() in item.get("text", "").lower()]
    return results[:limit]
