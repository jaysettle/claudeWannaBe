from __future__ import annotations

import sys
import logging
import json
from pathlib import Path

from ...core.conversation import Conversation
from ...core.llm_client import LLMClient


DEFAULT_SYSTEM = (
    "You are a concise CLI assistant running in a terminal. "
    "You can call tools to create files, list the current directory, and run python files relative to the CWD. "
    "Ask for missing details only if necessary, and prefer performing the action via the tool rather than just describing it."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create or overwrite a text file relative to the current working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative or absolute path to the file to create."},
                    "content": {"type": "string", "description": "Text content to write to the file."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files/directories in the current working directory.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "Run a python file relative to the current working directory and return its stdout/stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative or absolute path to the python file."},
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional arguments to pass to the script.",
                        "default": [],
                    },
                },
                "required": ["path"],
            },
        },
    },
]


def add_chat(subparsers):
    parser = subparsers.add_parser("chat", help="Interactive chat")
    parser.add_argument("--system", default=DEFAULT_SYSTEM, help="Override default system prompt")
    parser.set_defaults(func=run_chat)


def run_chat(args, settings):
    logger = logging.getLogger(__name__)
    client = LLMClient(settings)
    convo = Conversation()
    convo.add_system(args.system)

    print("Interactive chat. Type 'exit' or 'quit' (or Ctrl-D) to leave.")
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

        convo.add_user(user_input)
        try:
            handle_chat_turn(client, convo)
        except Exception as exc:  # pragma: no cover - interactive path
            logger.error("Chat failed: %s", exc)
            print(f"Error talking to model: {exc}")
            break


def handle_chat_turn(client: LLMClient, convo: Conversation):
    """Send a turn, execute any tool calls, then stream the assistant reply."""
    # First pass: let the model decide on tool use (non-stream for tool detection).
    resp = client.chat(convo.history(), stream=False, tools=TOOLS, tool_choice="auto")
    message = resp.choices[0].message

    # If the model wants to call tools, execute them and inform the conversation.
    if getattr(message, "tool_calls", None):
        tool_outputs = []
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            if name == "create_file":
                result = _handle_create_file(tool_call.function.arguments)
            elif name == "list_dir":
                result = _handle_list_dir()
            elif name == "run_python":
                result = _handle_run_python(tool_call.function.arguments)
            else:
                result = f"Unsupported tool: {name}"
            convo.add_tool_result(tool_call.id, result)
            tool_outputs.append(result)
        # Ask the model to produce a final reply after tool execution.
        follow = client.chat(convo.history(), stream=False, tools=TOOLS, tool_choice="none")
        _emit_message(follow, convo)
    else:
        # No tools used; stream the original response for a better UX.
        follow = client.chat(convo.history(), stream=True, tools=TOOLS, tool_choice="auto")
        if hasattr(follow, "__iter__"):
            _stream_response(follow, convo)
        else:
            _emit_message(follow, convo)


def _handle_create_file(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for create_file: {exc}"

    path_arg = args.get("path")
    content = args.get("content", "")
    if not path_arg:
        return "create_file failed: 'path' is required."

    base = Path.cwd().resolve()
    target = (base / path_arg).resolve() if not Path(path_arg).is_absolute() else Path(path_arg).resolve()

    try:
        target.relative_to(base)
    except ValueError:
        return f"create_file blocked: path outside workspace ({target})."

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        return f"create_file failed: {exc}"

    rel_path = target.relative_to(base)
    return f"create_file success: wrote {rel_path} (abs: {target})"


def _stream_response(resp, convo: Conversation):
    sys.stdout.write("agent> ")
    sys.stdout.flush()
    assistant_text = ""
    for chunk in resp:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            token = delta.content
            assistant_text += token
            sys.stdout.write(token)
            sys.stdout.flush()
    print()
    convo.add_assistant(assistant_text)


def _emit_message(resp, convo: Conversation):
    """Handle a non-stream response object."""
    msg = resp.choices[0].message
    content = (msg.content or "").strip() or "(no response text)"
    sys.stdout.write("agent> ")
    sys.stdout.write(content)
    sys.stdout.write("\n")
    sys.stdout.flush()
    convo.add_assistant(content, getattr(msg, "tool_calls", None))


def _handle_run_python(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for run_python: {exc}"

    path_arg = args.get("path")
    extra_args = args.get("args") or []
    if not path_arg:
        return "run_python failed: 'path' is required."

    base = Path.cwd().resolve()
    target = (base / path_arg).resolve() if not Path(path_arg).is_absolute() else Path(path_arg).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return f"run_python blocked: path outside workspace ({target})."

    if not target.exists():
        return f"run_python failed: file not found ({target.relative_to(base)})."

    import subprocess
    try:
        result = subprocess.run(
            ["python3", str(target), *map(str, extra_args)],
            capture_output=True,
            text=True,
            cwd=base,
            timeout=30,
        )
    except Exception as exc:
        return f"run_python failed: {exc}"

    out = result.stdout.strip()
    err = result.stderr.strip()
    status = result.returncode
    snippet = []
    if out:
        snippet.append(f"stdout:\n{out}")
    if err:
        snippet.append(f"stderr:\n{err}")
    body = "\n\n".join(snippet) or "(no output)"
    return f"run_python exit={status}\n{body}"


def _handle_list_dir() -> str:
    base = Path.cwd().resolve()
    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        return f"list_dir failed: {exc}"

    lines = []
    for entry in entries:
        marker = "/" if entry.is_dir() else ""
        lines.append(f"{entry.name}{marker}")
    listing = "\n".join(lines) or "(empty directory)"
    return f"list_dir success for {base}:\n{listing}"
