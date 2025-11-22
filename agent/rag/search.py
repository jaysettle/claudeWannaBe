"""
Vector similarity search using faiss (cosine similarity).
"""
from __future__ import annotations

from typing import List, Dict

import faiss
import numpy as np


def _normalize(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v, axis=1, keepdims=True)
    norm[norm == 0] = 1
    return v / norm


def search(embeddings: np.ndarray, metadata: List[Dict], query_embedding: List[float], limit: int = 5) -> List[Dict]:
    if embeddings is None or metadata is None or len(metadata) == 0:
        return []
    if embeddings.shape[0] != len(metadata):
        return []

    emb = embeddings.astype(np.float32)
    emb = _normalize(emb)

    q = np.array([query_embedding], dtype=np.float32)
    q = _normalize(q)

    index = faiss.IndexFlatIP(emb.shape[1])
    index.add(emb)
    scores, idxs = index.search(q, min(limit, emb.shape[0]))

    results = []
    for score, idx in zip(scores[0], idxs[0]):
        if idx < 0 or idx >= len(metadata):
            continue
        item = dict(metadata[idx])
        item["score"] = float(score)
        results.append(item)
    return results
