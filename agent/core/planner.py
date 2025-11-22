"""
Planner orchestrates LLM calls, tool execution, and reflection loops.
"""
from __future__ import annotations

from typing import Dict, List
import logging

from .llm_client import LLMClient
from .conversation import Conversation
from .memory import Memory
from ..tools.registry import ToolRegistry


class Planner:
    def __init__(self, llm: LLMClient, tools: ToolRegistry, memory: Memory):
        self.llm = llm
        self.tools = tools
        self.memory = memory
        self.logger = logging.getLogger(__name__)

    def run(self, conversation: Conversation, max_steps: int = 4) -> str:
        for _ in range(max_steps):
            self.logger.debug("Planner step with %d messages", len(conversation.history()))
            resp = self.llm.chat(conversation.history())
            # Streaming handled by caller; here we consume to inspect tool calls.
            final_content = []
            tool_calls: List[Dict] = []
            for chunk in resp:
                choice = chunk.choices[0]
                if choice.delta and choice.delta.content:
                    final_content.append(choice.delta.content)
                if choice.delta and choice.delta.tool_calls:
                    tool_calls.extend(choice.delta.tool_calls)
            if tool_calls:
                for call in tool_calls:
                    self.logger.info("Dispatching tool call %s", call.function.name)
                    result = self.tools.dispatch(call)
                    conversation.add_tool_result(call.id, result)
                continue
            answer = "".join(final_content)
            conversation.add_assistant(answer)
            self.memory.add("assistant", answer)
            self.logger.debug("Planner produced final answer")
            return answer
        return "Max steps reached without final answer."
