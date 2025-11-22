"""
Simple line-based chunker with overlap.
"""
from __future__ import annotations

from typing import List, Tuple


def chunk_lines(text: str, max_lines: int = 60, overlap: int = 10) -> List[Tuple[int, str]]:
    lines = text.splitlines()
    chunks = []
    start = 0
    while start < len(lines):
        end = min(start + max_lines, len(lines))
        chunk = "\n".join(lines[start:end])
        chunks.append((start + 1, chunk))
        start = end - overlap
        if start < 0:
            start = 0
    return chunks
