"""
Tool registry with JSON-schema metadata and safe dispatch.
"""
from __future__ import annotations

from typing import Callable, Dict, Any
import logging

from ..core.safety import Safety


class ToolRegistry:
    def __init__(self, safety: Safety):
        self.safety = safety
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.logger = logging.getLogger(__name__)

    def register(self, name: str, schema: Dict[str, Any], handler: Callable[[Dict[str, Any]], str], danger: str = "low"):
        self.tools[name] = {"schema": schema, "handler": handler, "danger": danger}
        self.logger.debug("Registered tool %s", name)

    def dispatch(self, tool_call) -> str:
        name = tool_call.function.name
        args = tool_call.function.arguments
        if name not in self.tools:
            raise ValueError(f"Unknown tool {name}")
        handler = self.tools[name]["handler"]
        self.logger.info("Executing tool %s", name)
        return handler(args)

    def schemas(self) -> Dict[str, Any]:
        return {name: meta["schema"] for name, meta in self.tools.items()}
