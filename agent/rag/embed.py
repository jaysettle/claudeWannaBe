"""
Embedding helper using Ollama embeddings endpoint via LLM client.
"""
from __future__ import annotations

from typing import List

from ..core.llm_client import LLMClient


def embed_texts(llm: LLMClient, texts: List[str]) -> List[List[float]]:
    return llm.embed(texts)
