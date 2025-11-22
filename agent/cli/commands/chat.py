from __future__ import annotations

import sys
import logging
import json
import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

from ...core.conversation import Conversation
from ...core.llm_client import LLMClient
from ...rag.index import load_index
from ...rag.search import search as rag_search


DEFAULT_SYSTEM = (
    "You are a concise CLI assistant running in a terminal. "
    "You can call tools to create/write/read files, list the current directory, tree view, rename/move/copy files, bulk-rename files, rename based on contents, delete with confirmation, search text, run shell/PowerShell/python commands relative to the CWD, and run SSH commands when requested. "
    "Ask for missing details only if necessary, and prefer performing the action via the tool rather than just describing it. "
    "Use install_package for installs (allowlist) and avoid sudo/apt-get in run_shell."
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
            "name": "read_file",
            "description": "Read a text file (optionally head/tail/line range) relative to the current working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative or absolute path."},
                    "head": {"type": "integer", "description": "Read first N lines (optional)."},
                    "tail": {"type": "integer", "description": "Read last N lines (optional)."},
                    "start": {"type": "integer", "description": "Start line (1-based, optional)."},
                    "end": {"type": "integer", "description": "End line inclusive (optional)."},
                    "max_chars": {"type": "integer", "description": "Maximum characters to return (default 4000)."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite/append to a text file relative to the current working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative or absolute path to the file."},
                    "content": {"type": "string", "description": "Text content to write."},
                    "mode": {
                        "type": "string",
                        "enum": ["overwrite", "append"],
                        "description": "Overwrite (default) or append to the file.",
                        "default": "overwrite",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copy_path",
            "description": "Copy a file or directory within the current working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string", "description": "Existing relative or absolute path."},
                    "dest": {"type": "string", "description": "Destination relative or absolute path."},
                },
                "required": ["src", "dest"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_path",
            "description": "Rename or move a file/directory within the current working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string", "description": "Existing relative or absolute path."},
                    "dest": {"type": "string", "description": "New relative or absolute path."},
                },
                "required": ["src", "dest"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_path",
            "description": "Delete a file or directory within the current working directory (requires confirm=true).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative or absolute path to delete."},
                    "recursive": {"type": "boolean", "description": "Allow deleting directories recursively.", "default": False},
                    "confirm": {"type": "boolean", "description": "Must be true to proceed.", "default": False},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_all",
            "description": "Bulk-rename all non-hidden files in the current working directory using a generated pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prefix": {"type": "string", "description": "Prefix for new filenames (default: file)", "default": "file"},
                    "start": {"type": "integer", "description": "Starting index (default: 1)", "default": 1},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_semantic",
            "description": "Rename non-hidden files in the current working directory to more meaningful names based on content/extension.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prefix": {"type": "string", "description": "Optional prefix for new filenames", "default": ""},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tree",
            "description": "List a tree view of the current working directory up to a depth.",
            "parameters": {
                "type": "object",
                "properties": {
                    "depth": {"type": "integer", "description": "Maximum depth (default 3).", "default": 3},
                },
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
            "name": "search_text",
            "description": "Search for a pattern in files under the current working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text or regex pattern to search for."},
                    "glob": {"type": "string", "description": "Optional glob filter, e.g., '*.py'."},
                    "max_results": {"type": "integer", "description": "Max matches to return (default 20).", "default": 20},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_index",
            "description": "Search the local RAG index stored under data/index.json in the current workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Query text to search for."},
                    "limit": {"type": "integer", "description": "Max results (default 5).", "default": 5},
                },
                "required": ["query"],
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
    {
        "type": "function",
        "function": {
            "name": "run_ssh",
            "description": "Run a command over SSH (user@host), returning stdout/stderr. Supports key or password.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Target in user@host or host form."},
                    "command": {"type": "string", "description": "Command to run remotely."},
                    "port": {"type": "integer", "description": "SSH port (default 22).", "default": 22},
                    "identity": {"type": "string", "description": "Path to identity/key file."},
                    "user": {"type": "string", "description": "Optional username (if not in target)."},
                    "password": {"type": "string", "description": "Optional password (requires sshpass installed)."},
                },
                "required": ["target", "command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a shell command locally in the current working directory (bash/sh).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command string to run via /bin/bash -lc."},
                    "timeout": {"type": "integer", "description": "Timeout seconds (default 30).", "default": 30},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ping_host",
            "description": "Ping a host/IP with a limited count to check reachability.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Hostname or IP to ping."},
                    "count": {"type": "integer", "description": "Number of echo requests (default 4).", "default": 4},
                    "timeout": {"type": "integer", "description": "Timeout seconds for the command (default 10).", "default": 10},
                },
                "required": ["host"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_powershell",
            "description": "Run a PowerShell command locally in the current working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "PowerShell command to run."},
                    "timeout": {"type": "integer", "description": "Timeout seconds (default 30).", "default": 30},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "install_package",
            "description": "Install an allowed package via Homebrew (allowlist only).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Package name (allowlisted)."},
                },
                "required": ["name"],
            },
        },
    },
]


def add_chat(subparsers):
    parser = subparsers.add_parser("chat", help="Interactive chat")
    parser.add_argument("--system", default=DEFAULT_SYSTEM, help="Override default system prompt")
    parser.add_argument("--resume", help="Path to a previous transcript JSONL to preload history")
    parser.add_argument("--transcript-dir", help="Directory to write transcripts (default data/sessions)")
    parser.add_argument("--no-transcript", action="store_true", help="Disable transcript logging")
    parser.set_defaults(func=run_chat)


def run_chat(args, settings):
    logger = logging.getLogger(__name__)
    client = LLMClient(settings)
    convo = Conversation()
    transcript = None

    if args.resume:
        convo = _load_transcript(args.resume, logger)
    convo.add_system(args.system)

    if not args.no_transcript:
        transcript_dir = Path(args.transcript_dir or settings.data_dir / "sessions")
        transcript_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        transcript = (transcript_dir / f"session-{ts}.jsonl").resolve()
        logger.info("Writing transcript to %s", transcript)

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
        if transcript:
            _append_transcript(transcript, {"role": "user", "content": user_input})

        try:
            handle_chat_turn(client, convo, settings, transcript, logger)
        except Exception as exc:  # pragma: no cover - interactive path
            logger.error("Chat failed: %s", exc)
            print(f"Error talking to model: {exc}")
            break


def handle_chat_turn(client: LLMClient, convo: Conversation, settings, transcript, logger):
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
            elif name == "read_file":
                result = _handle_read_file(tool_call.function.arguments)
            elif name == "write_file":
                result = _handle_write_file(tool_call.function.arguments)
            elif name == "copy_path":
                result = _handle_copy_path(tool_call.function.arguments)
            elif name == "rename_path":
                result = _handle_rename_path(tool_call.function.arguments)
            elif name == "rename_all":
                result = _handle_rename_all(tool_call.function.arguments)
            elif name == "rename_semantic":
                result = _handle_rename_semantic(tool_call.function.arguments)
            elif name == "delete_path":
                result = _handle_delete_path(tool_call.function.arguments)
            elif name == "list_dir":
                result = _handle_list_dir()
            elif name == "list_tree":
                result = _handle_list_tree(tool_call.function.arguments)
            elif name == "search_text":
                result = _handle_search_text(tool_call.function.arguments)
            elif name == "search_index":
                result = _handle_search_index(tool_call.function.arguments, settings, client)
            elif name == "run_python":
                result = _handle_run_python(tool_call.function.arguments)
            elif name == "run_ssh":
                result = _handle_run_ssh(tool_call.function.arguments)
            elif name == "run_shell":
                result = _handle_run_shell(tool_call.function.arguments)
            elif name == "run_powershell":
                result = _handle_run_powershell(tool_call.function.arguments)
            elif name == "ping_host":
                result = _handle_ping_host(tool_call.function.arguments)
            elif name == "install_package":
                result = _handle_install_package(tool_call.function.arguments)
            else:
                result = f"Unsupported tool: {name}"
            convo.add_tool_result(tool_call.id, result)
            if transcript:
                _append_transcript(transcript, {"role": "tool", "content": result, "tool": name})
            tool_outputs.append(result)
        # Ask the model to produce a final reply after tool execution.
        follow = client.chat(convo.history(), stream=False, tools=TOOLS, tool_choice="none")
        _emit_message(follow, convo, transcript, fallback="\n".join(tool_outputs))
    else:
        # No tools used; stream the original response for a better UX.
        follow = client.chat(convo.history(), stream=True, tools=TOOLS, tool_choice="auto")
        if hasattr(follow, "__iter__"):
            _stream_response(follow, convo, transcript)
        else:
            _emit_message(follow, convo, transcript)


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


def _handle_write_file(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for write_file: {exc}"

    path_arg = args.get("path")
    content = args.get("content", "")
    mode = args.get("mode", "overwrite")
    if not path_arg:
        return "write_file failed: 'path' is required."
    if mode not in {"overwrite", "append"}:
        return "write_file failed: mode must be 'overwrite' or 'append'."

    base = Path.cwd().resolve()
    target = (base / path_arg).resolve() if not Path(path_arg).is_absolute() else Path(path_arg).resolve()

    try:
        target.relative_to(base)
    except ValueError:
        return f"write_file blocked: path outside workspace ({target})."

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append" and target.exists():
            target.write_text(target.read_text(encoding="utf-8") + content, encoding="utf-8")
        elif mode == "append":
            target.write_text(content, encoding="utf-8")
        else:
            target.write_text(content, encoding="utf-8")
    except OSError as exc:
        return f"write_file failed: {exc}"

    rel_path = target.relative_to(base)
    return f"write_file success: wrote {rel_path} (abs: {target}) mode={mode}"


def _handle_read_file(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for read_file: {exc}"

    path_arg = args.get("path")
    if not path_arg:
        return "read_file failed: 'path' is required."

    base, target, err = _resolve_path(path_arg)
    if err:
        return err
    if not target.exists():
        return f"read_file failed: file not found ({target.relative_to(base)})."
    if target.is_dir():
        return "read_file failed: target is a directory."

    head = args.get("head")
    tail = args.get("tail")
    start = args.get("start")
    end = args.get("end")
    max_chars = int(args.get("max_chars", 4000))

    try:
        text = target.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        return f"read_file failed: {exc}"

    lines = text.splitlines()
    if head:
        lines = lines[: int(head)]
    if tail:
        lines = lines[-int(tail) :]
    if start:
        s = max(1, int(start))
        e = int(end) if end else len(lines)
        lines = lines[s - 1 : e]

    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n...[truncated]..."
    return f"read_file success: {target.relative_to(base)}\n{result}"


def _handle_copy_path(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for copy_path: {exc}"

    src_arg = args.get("src")
    dest_arg = args.get("dest")
    if not src_arg or not dest_arg:
        return "copy_path failed: 'src' and 'dest' are required."

    base, src, err = _resolve_path(src_arg)
    if err:
        return err
    _, dest, err2 = _resolve_path(dest_arg)
    if err2:
        return err2
    if not src.exists():
        return f"copy_path failed: source not found ({src.relative_to(base)})."

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dest.exists():
                return "copy_path failed: destination exists for directory copy."
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
    except OSError as exc:
        return f"copy_path failed: {exc}"

    return f"copy_path success: {src.relative_to(base)} -> {dest.relative_to(base)}"


def _handle_delete_path(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for delete_path: {exc}"

    path_arg = args.get("path")
    recursive = bool(args.get("recursive", False))
    confirm = bool(args.get("confirm", False))
    if not confirm:
        return "delete_path blocked: set confirm=true to proceed."
    if not path_arg:
        return "delete_path failed: 'path' is required."

    base, target, err = _resolve_path(path_arg)
    if err:
        return err
    if not target.exists():
        return f"delete_path failed: path not found ({target.relative_to(base)})."

    try:
        if target.is_dir():
            if not recursive:
                return "delete_path blocked: directory deletion requires recursive=true."
            shutil.rmtree(target)
        else:
            target.unlink()
    except OSError as exc:
        return f"delete_path failed: {exc}"

    return f"delete_path success: removed {target.relative_to(base)}"


def _handle_rename_path(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for rename_path: {exc}"

    src_arg = args.get("src")
    dest_arg = args.get("dest")
    if not src_arg or not dest_arg:
        return "rename_path failed: 'src' and 'dest' are required."

    base = Path.cwd().resolve()
    src = (base / src_arg).resolve() if not Path(src_arg).is_absolute() else Path(src_arg).resolve()
    dest = (base / dest_arg).resolve() if not Path(dest_arg).is_absolute() else Path(dest_arg).resolve()

    for path, label in [(src, "src"), (dest, "dest")]:
        try:
            path.relative_to(base)
        except ValueError:
            return f"rename_path blocked: {label} outside workspace ({path})."

    if not src.exists():
        return f"rename_path failed: source not found ({src.relative_to(base)})."

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dest)
    except OSError as exc:
        return f"rename_path failed: {exc}"

    return f"rename_path success: {src.relative_to(base)} -> {dest.relative_to(base)} (abs: {dest})"


def _handle_rename_all(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for rename_all: {exc}"

    prefix = args.get("prefix", "file")
    start = int(args.get("start", 1))

    base = Path.cwd().resolve()
    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        return f"rename_all failed: {exc}"

    files = [p for p in entries if p.is_file() and not p.name.startswith(".")]
    if not files:
        return "rename_all skipped: no non-hidden files found."

    mapping = []
    idx = start
    for f in files:
        ext = f.suffix
        new_name = f"{prefix}{idx}{ext}"
        dest = base / new_name
        # ensure unique by bumping index if needed
        while dest.exists():
            idx += 1
            new_name = f"{prefix}{idx}{ext}"
            dest = base / new_name
        try:
            f.rename(dest)
            mapping.append(f"{f.name} -> {dest.name}")
            idx += 1
        except OSError as exc:
            mapping.append(f"{f.name} -> failed ({exc})")

    summary = "\n".join(mapping)
    return f"rename_all complete in {base}:\n{summary}"


def _handle_rename_semantic(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for rename_semantic: {exc}"

    prefix = args.get("prefix", "")
    base = Path.cwd().resolve()
    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        return f"rename_semantic failed: {exc}"

    files = [p for p in entries if p.is_file() and not p.name.startswith(".")]
    if not files:
        return "rename_semantic skipped: no non-hidden files found."

    mapping = []
    used = set()
    for f in files:
        suggestion = _suggest_name(f)
        if not suggestion:
            mapping.append(f"{f.name} -> skipped (no suggestion)")
            continue
        new_stem = prefix + suggestion
        new_name = _ensure_unique_name(base, new_stem, f.suffix, used)
        dest = base / new_name
        if dest == f:
            mapping.append(f"{f.name} -> unchanged")
            continue
        try:
            f.rename(dest)
            mapping.append(f"{f.name} -> {new_name}")
        except OSError as exc:
            mapping.append(f"{f.name} -> failed ({exc})")
    summary = "\n".join(mapping)
    return f"rename_semantic complete in {base}:\n{summary}"


def _handle_list_tree(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for list_tree: {exc}"
    depth = int(args.get("depth", 3))
    base = Path.cwd().resolve()

    lines = []
    try:
        for root, dirs, files in _walk_limited(base, depth):
            indent = "  " * root.relative_to(base).parts.__len__()
            lines.append(f"{indent}{root.name}/" if indent else f"{root.name}/")
            for f in sorted(files):
                lines.append(f"{indent}  {f}")
    except OSError as exc:
        return f"list_tree failed: {exc}"

    listing = "\n".join(lines) or "(empty)"
    return f"list_tree success (depth {depth}) for {base}:\n{listing}"


def _walk_limited(base: Path, depth: int):
    for root, dirs, files in os.walk(base):
        rel = Path(root).relative_to(base)
        if len(rel.parts) > depth:
            dirs[:] = []  # prune
            continue
        yield Path(root), dirs, files


def _suggest_name(path: Path) -> str | None:
    max_bytes = 4096
    ext = path.suffix.lower()
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")[:max_bytes]
    except Exception:
        content = ""

    def slugify(s: str) -> str:
        import re
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", s.strip().lower()).strip("-")
        return slug[:50] or None

    if ext in {".md", ".markdown"}:
        for line in content.splitlines():
            if line.strip().startswith("#"):
                maybe = line.lstrip("#").strip()
                slug = slugify(maybe)
                if slug:
                    return slug
        # fallback to first non-empty line
        for line in content.splitlines():
            if line.strip():
                slug = slugify(line)
                if slug:
                    return slug
    elif ext in {".py"}:
        first_line = content.splitlines()[0] if content else ""
        if first_line.startswith("#!"):
            first_line = ""
        for line in content.splitlines()[:5]:
            if line.strip().startswith("#") or line.strip().startswith('"""'):
                slug = slugify(line.replace('"', "").replace("#", ""))
                if slug:
                    return slug
        if "import" in content:
            return "python-module"
    elif ext in {".txt"}:
        for line in content.splitlines():
            if line.strip():
                slug = slugify(line)
                if slug:
                    return slug
    elif ext in {".json"}:
        try:
            import json as _json
            data = _json.loads(content or "{}")
            if isinstance(data, dict):
                keys = list(data.keys())
                if keys:
                    return slugify("-".join(keys[:3]))
        except Exception:
            pass
    # generic fallback
    return slugify(path.stem) or "file"


def _ensure_unique_name(base: Path, stem: str, ext: str, used: set[str]) -> str:
    candidate = f"{stem}{ext}"
    idx = 1
    while (base / candidate).exists() or candidate in used:
        candidate = f"{stem}-{idx}{ext}"
        idx += 1
    used.add(candidate)
    return candidate


def _stream_response(resp, convo: Conversation, transcript=None):
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
    if transcript:
        _append_transcript(transcript, {"role": "assistant", "content": assistant_text})


def _emit_message(resp, convo: Conversation, transcript=None, fallback: str | None = None):
    """Handle a non-stream response object."""
    msg = resp.choices[0].message
    content = (msg.content or "").strip() or "(no response text)"
    if content == "(no response text)" and fallback:
        content = fallback
    sys.stdout.write("agent> ")
    sys.stdout.write(content)
    sys.stdout.write("\n")
    sys.stdout.flush()
    convo.add_assistant(content, getattr(msg, "tool_calls", None))
    if transcript:
        _append_transcript(transcript, {"role": "assistant", "content": content})


def _append_transcript(path: Path, record: dict):
    try:
        with Path(path).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass  # best-effort


def _load_transcript(path_str: str, logger) -> Conversation:
    convo = Conversation()
    path = Path(path_str)
    if not path.exists():
        logger.warning("Transcript not found: %s", path)
        return convo
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            role = rec.get("role")
            content = rec.get("content", "")
            if role == "user":
                convo.add_user(content)
            elif role == "assistant":
                convo.add_assistant(content)
            elif role == "system":
                convo.add_system(content)
            elif role == "tool":
                convo.add_tool_result(rec.get("tool_call_id", ""), content)
        logger.info("Loaded transcript from %s", path)
    except Exception as exc:
        logger.warning("Failed to load transcript %s: %s", path, exc)
    return convo


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


def _handle_run_ssh(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for run_ssh: {exc}"

    target = args.get("target")
    command = args.get("command")
    port = args.get("port", 22)
    identity = args.get("identity")
    user = args.get("user")
    password = args.get("password")
    if not target or not command:
        return "run_ssh failed: 'target' and 'command' are required."

    if user and "@" not in target:
        target = f"{user}@{target}"

    ssh_cmd = ["ssh"]
    if identity:
        ssh_cmd.extend(["-i", str(identity)])
    if port:
        ssh_cmd.extend(["-p", str(port)])
    ssh_cmd.extend([str(target), str(command)])

    use_password = password and not identity
    if use_password:
        sshpass = shutil.which("sshpass")
        if not sshpass:
            return "run_ssh failed: password provided but sshpass is not installed. Install sshpass or use a key."
        ssh_cmd = [sshpass, "-p", str(password)] + ssh_cmd

    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return f"run_ssh failed: {exc}"

    out = result.stdout.strip()
    err = result.stderr.strip()
    status = result.returncode
    parts = [f"run_ssh exit={status}"]
    if out:
        parts.append(f"stdout:\n{out}")
    if err:
        parts.append(f"stderr:\n{err}")
    return "\n".join(parts)


def _handle_run_shell(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for run_shell: {exc}"

    command = args.get("command")
    timeout = int(args.get("timeout", 30))
    if not command:
        return "run_shell failed: 'command' is required."

    lowered = command.strip().lower()
    if lowered.startswith("sudo ") or "apt-get" in lowered:
        return "run_shell blocked: disallowed sudo/apt-get. Use install_package tool or run manually."

    try:
        result = subprocess.run(
            ["/bin/bash", "-lc", command],
            capture_output=True,
            text=True,
            cwd=Path.cwd(),
            timeout=timeout,
        )
    except Exception as exc:
        return f"run_shell failed: {exc}"

    out = result.stdout.strip()
    err = result.stderr.strip()
    status = result.returncode
    parts = [f"run_shell exit={status}"]
    if out:
        parts.append(f"stdout:\n{out}")
    if err:
        parts.append(f"stderr:\n{err}")
    return "\n".join(parts)

def _handle_ping_host(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for ping_host: {exc}"

    host = args.get("host")
    count = int(args.get("count", 4))
    timeout = int(args.get("timeout", 10))
    if not host:
        return "ping_host failed: 'host' is required."

    cmd = ["ping", "-c", str(count), host]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return f"ping_host failed: {exc}"

    out = result.stdout.strip()
    err = result.stderr.strip()
    status = result.returncode
    parts = [f"ping_host exit={status} ({host})"]
    if out:
        parts.append(f"stdout:\n{out}")
    if err:
        parts.append(f"stderr:\n{err}")
    return "\n".join(parts)


def _handle_run_powershell(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for run_powershell: {exc}"

    command = args.get("command")
    timeout = int(args.get("timeout", 30))
    if not command:
        return "run_powershell failed: 'command' is required."

    ps = shutil.which("pwsh") or shutil.which("powershell")
    if not ps:
        return "run_powershell failed: PowerShell (pwsh) not found."

    try:
        result = subprocess.run(
            [ps, "-Command", command],
            capture_output=True,
            text=True,
            cwd=Path.cwd(),
            timeout=timeout,
        )
    except Exception as exc:
        return f"run_powershell failed: {exc}"

    out = result.stdout.strip()
    err = result.stderr.strip()
    status = result.returncode
    parts = [f"run_powershell exit={status}"]
    if out:
        parts.append(f"stdout:\n{out}")
    if err:
        parts.append(f"stderr:\n{err}")
    return "\n".join(parts)


def _handle_install_package(raw_args: str) -> str:
    allowlist = {
        "sshpass": "brew install hudochenkov/sshpass/sshpass",
        "ripgrep": "brew install ripgrep",
        "rg": "brew install ripgrep",
        "pwsh": "brew install --cask powershell",
        "powershell": "brew install --cask powershell",
    }
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for install_package: {exc}"

    name = (args.get("name") or "").lower().strip()
    if not name:
        return "install_package failed: 'name' is required."

    if name not in allowlist:
        return f"install_package blocked: '{name}' is not in allowlist {sorted(allowlist.keys())}."

    cmd = allowlist[name]
    brew = shutil.which("brew")
    if not brew:
        return "install_package failed: Homebrew is not installed. Install brew first (see https://brew.sh) or install manually."

    try:
        result = subprocess.run(
            ["/bin/bash", "-lc", cmd],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except Exception as exc:
        return f"install_package failed: {exc}"

    out = result.stdout.strip()
    err = result.stderr.strip()
    status = result.returncode
    parts = [f"install_package {name} exit={status}", f"command: {cmd}"]
    if out:
        parts.append(f"stdout:\n{out}")
    if err:
        parts.append(f"stderr:\n{err}")
    return "\n".join(parts)


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


def _handle_search_text(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for search_text: {exc}"

    query = args.get("query")
    glob = args.get("glob")
    max_results = int(args.get("max_results", 20))
    if not query:
        return "search_text failed: 'query' is required."

    base = Path.cwd().resolve()
    cmd = ["rg", "--no-heading", "--line-number", "--color", "never", "--max-count", str(max_results), query, "."]
    if glob:
        cmd = ["rg", "--no-heading", "--line-number", "--color", "never", "--max-count", str(max_results), "--glob", glob, query, "."]
    try:
        proc = subprocess.run(cmd, cwd=base, capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        return "search_text failed: ripgrep (rg) not available."
    except Exception as exc:
        return f"search_text failed: {exc}"

    output = proc.stdout.strip()
    if not output:
        return f"search_text: no matches for '{query}'{f' with glob {glob}' if glob else ''}."
    lines = output.splitlines()[:max_results]
    return "search_text results:\n" + "\n".join(lines)


def _handle_search_index(raw_args: str, settings, llm_client) -> str:
    from ...rag.index import load_index
    from ...rag.search import search as rag_search
    from ...rag.embed import embed_texts

    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for search_index: {exc}"

    query = args.get("query")
    limit = int(args.get("limit", 5))
    if not query:
        return "search_index failed: 'query' is required."

    base = (Path.cwd() / settings.data_dir / "index").resolve()
    embeddings, metadata = load_index(base)
    if embeddings is None or metadata is None:
        return f"search_index failed: no index found at {base.with_suffix('.npy')}. Run 'jay-agent index' first."

    q_vec = embed_texts(llm_client, [query])[0]
    results = rag_search(embeddings, metadata, q_vec, limit=limit)
    if not results:
        return f"search_index: no matches for '{query}'."

    lines = []
    for item in results:
        path = item.get("path")
        start = item.get("start_line")
        snippet = (item.get("text") or "").splitlines()
        first_line = snippet[0] if snippet else ""
        score = item.get("score")
        score_str = f" (score {score:.3f})" if score is not None else ""
        lines.append(f"{path}:{start}{score_str} -> {first_line}")
    return "search_index results:\n" + "\n".join(lines)


def _resolve_path(path_str: str):
    base = Path.cwd().resolve()
    target = (base / path_str).resolve() if not Path(path_str).is_absolute() else Path(path_str).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return base, target, f"path outside workspace ({target})."
    return base, target, None
