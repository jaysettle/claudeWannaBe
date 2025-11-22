"""
OpenAI-compatible client targeting remote Ollama server.
Provides chat, completion, and embedding helpers with streaming support.
"""
from __future__ import annotations

from typing import Iterator, List, Optional, Any
import logging

try:
    from openai import OpenAI
except ModuleNotFoundError:  # pragma: no cover - handled at runtime
    OpenAI = None

from .config import Settings


class LLMClient:
    def __init__(self, settings: Settings):
        if OpenAI is None:
            raise RuntimeError("Dependency missing: install the 'openai' package to use LLM features.")
        self.settings = settings
        self.client = OpenAI(base_url=settings.base_url, api_key=settings.api_key)
        self.logger = logging.getLogger(__name__)
        self.logger.info("LLMClient initialized with base_url=%s model=%s", settings.base_url, settings.model)

    def chat(
        self,
        messages: List[dict],
        model: Optional[str] = None,
        stream: bool = True,
        **kwargs: Any,
    ):
        """Send a chat completion request."""
        self.logger.debug("Sending chat with %d messages", len(messages))
        return self.client.chat.completions.create(
            model=model or self.settings.model,
            messages=messages,
            stream=stream,
            temperature=0,
            **kwargs,
        )

    def embed(self, inputs: List[str], model: Optional[str] = None) -> List[List[float]]:
        self.logger.debug("Embedding %d inputs", len(inputs))
        resp = self.client.embeddings.create(model=model or self.settings.embed_model, input=inputs)
        return [item.embedding for item in resp.data]

    def stream_tokens(self, resp) -> Iterator[str]:
        for chunk in resp:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content
