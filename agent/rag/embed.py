"""
Embedding helper using LLM client.
"""
from __future__ import annotations

from typing import List
import numpy as np

from ..core.llm_client import LLMClient


def embed_texts(llm: LLMClient, texts: List[str]) -> np.ndarray:
    vecs = llm.embed(texts)
    return np.array(vecs, dtype=np.float32)
