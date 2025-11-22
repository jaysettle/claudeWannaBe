"""
Vector index persistence using numpy arrays plus metadata.
Embeddings are stored in .npy, metadata in .meta.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict, Tuple

import numpy as np


def save_index(base_path: Path, embeddings: np.ndarray, metadata: List[Dict]):
    """
    Save embeddings and metadata.
    Files:
      - <base_path>.npy
      - <base_path>.meta.json
    """
    base_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(base_path.with_suffix(".npy"), embeddings.astype(np.float32))
    meta_path = base_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def load_index(base_path: Path) -> Tuple[np.ndarray, List[Dict]] | Tuple[None, None]:
    emb_path = base_path.with_suffix(".npy")
    meta_path = base_path.with_suffix(".meta.json")
    if not emb_path.exists() or not meta_path.exists():
        return None, None
    embeddings = np.load(emb_path)
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    return embeddings, metadata
