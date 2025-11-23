# AI Prompt: Integrate Slash Commands into jay-agent

## Task

Integrate the slash command system into the jay-agent chat interface to enable interactive commands like `/model`, `/help`, `/tools`, etc.

---

## Step 1: Copy the Slash Commands Module

Take the file `/Users/jaysettle/Documents/CursAI/3 LLM CLI/slash_commands.py` and copy it to:

```
agent/cli/commands/slash_commands.py
```

**Verification:** The file should be located at `agent/cli/commands/slash_commands.py` in the claudeWannaBe repository.

---

## Step 2: Update chat.py Imports

In `agent/cli/commands/chat.py`, add this import at the top of the file (around line 13-19, after other imports):

```python
from .slash_commands import handle_slash_command, setup_command_completion
```

**Location:** Add after the existing imports:
```python
from ...core.conversation import Conversation
from ...core.llm_client import LLMClient
from ...tools.python_exec import PythonExecutor
from ...rag.index import load_index
from ...rag.search import search as rag_search
from .slash_commands import handle_slash_command, setup_command_completion  # ADD THIS
```

---

## Step 3: Add Tab Completion Setup

In the `run_chat()` function in `agent/cli/commands/chat.py`, add tab completion setup **before the main loop starts**.

**Find this section** (around line 590-592):
```python
    convo.add_system(args.system)

    if not args.no_transcript:
        transcript_dir.mkdir(parents=True, exist_ok=True)
```

**Add this after `convo.add_system(args.system)` and before the transcript setup:**
```python
    convo.add_system(args.system)

    # Setup tab completion for slash commands
    setup_command_completion()

    if not args.no_transcript:
```

---

## Step 4: Update the Chat Loop Welcome Message

**Find this line** (around line 591):
```python
    print("Interactive chat. Type 'exit' or 'quit' (or Ctrl-D) to leave.")
```

**Replace it with:**
```python
    print("Interactive chat. Type 'exit' or 'quit' (or Ctrl-D) to leave.")
    print("Type /help for available commands.")
```

---

## Step 5: Add Slash Command Handling in Main Loop

In the main chat loop in `run_chat()`, **find this section** (around line 593-603):

```python
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("Bye.")
            break
```

**Add slash command handling after the empty input check and before the exit check:**

```python
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not user_input:
            continue

        # Handle slash commands
        if user_input.startswith("/"):
            result = handle_slash_command(user_input, settings, convo, client)
            if result.get("exit"):
                break
            # Update system prompt if changed
            if result.get("system_prompt"):
                args.system = result["system_prompt"]
            continue  # Don't send to LLM

        if user_input.lower() in {"exit", "quit"}:
            print("Bye.")
            break
```

---

## Step 6: Ensure Conversation Has clear() Method

The slash commands expect `convo.clear()` to exist. Verify that `agent/core/conversation.py` has a `clear()` method.

**Check if this method exists in the Conversation class:**
```python
def clear(self):
    """Clear conversation history."""
    self.messages = []
```

**If it doesn't exist, add it to the Conversation class:**

Find the Conversation class in `agent/core/conversation.py` and add:

```python
class Conversation:
    def __init__(self):
        self.messages = []

    # ... existing methods ...

    def clear(self):
        """Clear all messages from conversation history."""
        self.messages = []
```

---

## Step 7: Verify Dependencies

Ensure `requests` is in the dependencies (needed for `/model` command to fetch from Ollama).

**Check `pyproject.toml`:**
```toml
dependencies = [
    "openai>=2.8.0",
    "faiss-cpu>=1.13.0",
    "requests>=2.31.0",  # Should be present
]
```

**If `requests` is missing, add it:**
```bash
pip install requests
```

And update `pyproject.toml`:
```toml
dependencies = [
    "openai>=2.8.0",
    "faiss-cpu>=1.13.0",
    "requests>=2.31.0",
]
```

---

## Step 8: Test the Integration

Run the chat and test each command:

```bash
cd ~/projects/claudeWannaBe  # or wherever the repo is
source venv/bin/activate
jay-agent chat
```

**Test commands:**
```
you> /help
# Should display all available commands

you> /model
# Should list available models from Ollama

you> /model 2
# Should switch to model #2

you> /config
# Should show current configuration

you> /tools
# Should list all available tools

you> create a file test.txt with hello
# Should use AI tool calling

you> /history
# Should show conversation history

you> /save test-session.jsonl
# Should save conversation

you> /clear
# Should clear conversation (with confirmation)

you> /load test-session.jsonl
# Should load conversation

you> /transcripts
# Should list saved transcripts

you> /exit
# Should exit chat
```

---

## Expected Behavior After Integration

### Before Integration:
```
you> /help
AI: I'm not sure what you mean by "/help"...
```

### After Integration:
```
you> /help

Slash Commands:
  /help              Show this help message
  /model             List available models
  /model <name>      Switch to a specific model
  /config            Show current configuration
  /tools             List all available tools
  ...
```

### Model Switching Example:
```
you> /model

Fetching available models from Ollama...

Available models (current: gpt-oss:20b):

→ 1. gpt-oss:20b           (12.3GB, modified: 2024-11-20)
  2. llama3:latest         (4.7GB, modified: 2024-11-18)
  3. deepseek-coder:6.7b   (3.8GB, modified: 2024-11-15)

To switch: /model <name> or /model <number>

you> /model 2
✓ Model switched: gpt-oss:20b → llama3:latest
  Next message will use llama3:latest

you> Hello
AI: [responds using llama3:latest model]
```

---

## Troubleshooting

### Error: "ModuleNotFoundError: No module named 'slash_commands'"

**Cause:** File not in correct location or import path wrong.

**Fix:** Ensure file is at `agent/cli/commands/slash_commands.py` and import is:
```python
from .slash_commands import handle_slash_command, setup_command_completion
```

---

### Error: "AttributeError: 'Conversation' object has no attribute 'clear'"

**Cause:** Conversation class missing `clear()` method.

**Fix:** Add to `agent/core/conversation.py`:
```python
def clear(self):
    """Clear all messages from conversation history."""
    self.messages = []
```

---

### Error: "No module named 'requests'"

**Cause:** `requests` library not installed.

**Fix:**
```bash
pip install requests
```

---

### Slash commands don't work but no error

**Cause:** Code might not be reaching slash command handler.

**Fix:** Verify the `if user_input.startswith("/"):` block is **before** the AI sends the message and has `continue` at the end to skip LLM processing.

---

## Summary of Changes

**Files Modified:**
1. `agent/cli/commands/chat.py` - Added import, setup call, and slash command handling
2. `agent/core/conversation.py` - Added `clear()` method (if missing)

**Files Added:**
1. `agent/cli/commands/slash_commands.py` - New module with all slash command logic

**Total Lines Added:** ~400 lines (all in separate module, minimal changes to existing code)

**Breaking Changes:** None (fully backward compatible)

---

## Verification Checklist

After integration, verify:

- [ ] `/help` displays all commands
- [ ] `/model` lists models from Ollama server
- [ ] `/model <number>` switches models successfully
- [ ] `/config` shows current settings
- [ ] `/tools` lists all available tools
- [ ] `/history` shows conversation
- [ ] `/clear` resets conversation (with confirmation)
- [ ] `/save` saves to file
- [ ] `/load` loads from file
- [ ] `/transcripts` lists saved sessions
- [ ] `/exit` quits chat
- [ ] Regular AI messages still work normally
- [ ] Tool calling still works (e.g., "create a file test.txt")

---

## Final Notes

- All slash commands execute **instantly** without LLM inference
- Commands are **not** sent to the AI
- Regular messages (not starting with `/`) work exactly as before
- Model switching happens **immediately** without restart
- Tab completion works on systems with readline (most Unix/Mac, not Windows)

The integration is complete when all commands work and the chat loop remains stable.
