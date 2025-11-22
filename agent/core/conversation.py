"""
Conversation utilities: message store, role helpers, and tool-call parsing/formatting.
"""
from __future__ import annotations

from typing import List, Dict


SYSTEM_ROLE = "system"
USER_ROLE = "user"
ASSISTANT_ROLE = "assistant"
TOOL_ROLE = "tool"


class Conversation:
    def __init__(self):
        self.messages: List[Dict] = []

    def add_system(self, content: str):
        self.messages.append({"role": SYSTEM_ROLE, "content": content})

    def add_user(self, content: str):
        self.messages.append({"role": USER_ROLE, "content": content})

    def add_assistant(self, content: str, tool_calls=None):
        msg = {"role": ASSISTANT_ROLE, "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)

    def add_tool_result(self, tool_call_id: str, content: str):
        self.messages.append({"role": TOOL_ROLE, "tool_call_id": tool_call_id, "content": content})

    def history(self) -> List[Dict]:
        return list(self.messages)
