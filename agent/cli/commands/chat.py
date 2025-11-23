from __future__ import annotations

import sys
import logging
import json
import os
import shutil
import subprocess
import time
import threading
import tempfile
from pathlib import Path
from datetime import datetime

from ...core.conversation import Conversation
from ...core.llm_client import LLMClient
from ...tools.python_exec import PythonExecutor
from ...rag.index import load_index
from ...rag.search import search as rag_search
from .slash_commands import handle_slash_command, setup_command_completion


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
            "name": "run_bash_script",
            "description": "Run a bash script (multi-line) with optional env/cwd.",
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {"type": "string", "description": "Bash script content."},
                    "timeout": {"type": "integer", "description": "Timeout seconds (default 60).", "default": 60},
                    "cwd": {"type": "string", "description": "Optional working directory."},
                    "env": {"type": "object", "description": "Optional environment variables."}
                },
                "required": ["script"],
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
            "name": "web_search",
            "description": "Web search via SerpAPI (requires JAY_SERPAPI_KEY).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "num": {"type": "integer", "description": "Number of results (default 5, max 10)", "default": 5},
                    "site": {"type": "string", "description": "Optional site/domain filter, e.g., example.com"},
                    "fetch": {"type": "integer", "description": "Fetch and summarize top N results (default 0, max 3)", "default": 0},
                    "max_bytes": {"type": "integer", "description": "Max bytes to download per fetch (default 1_000_000).", "default": 1000000},
                    "max_fetch_time": {"type": "integer", "description": "Max seconds per fetch (default 15).", "default": 15},
                },
                "required": ["query"],
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
            "name": "edit_file",
            "description": "Replace exact string match in a file. Fails if old_string is not unique unless replace_all=true.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative or absolute path to the file to edit"},
                    "old_string": {"type": "string", "description": "Exact string to find and replace"},
                    "new_string": {"type": "string", "description": "String to replace old_string with"},
                    "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)", "default": False},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "http_request",
            "description": "Make an HTTP request with optional headers/body and size/time limits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL (http:// or https://)"},
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
                        "description": "HTTP method",
                        "default": "GET",
                    },
                    "headers": {"type": "object", "description": "HTTP headers", "default": {}},
                    "body": {"type": "string", "description": "Optional request body"},
                    "timeout": {"type": "integer", "description": "Timeout seconds (default 30, max 60)", "default": 30},
                    "max_response_size": {"type": "integer", "description": "Max response bytes (default 1MB)", "default": 1048576},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_add",
            "description": "Stage files for git commit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "File paths to stage"},
                    "all": {"type": "boolean", "description": "Stage all changes (git add -A)", "default": False},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "Create a git commit with staged changes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message"},
                    "amend": {"type": "boolean", "description": "Amend previous commit", "default": False},
                },
                "required": ["message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_push",
            "description": "Push commits to a remote repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "remote": {"type": "string", "description": "Remote name", "default": "origin"},
                    "branch": {"type": "string", "description": "Branch name (defaults to current)"},
                    "force": {"type": "boolean", "description": "Force push (dangerous)", "default": False},
                    "set_upstream": {"type": "boolean", "description": "Set upstream tracking (-u)", "default": False},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Prompt the user for input during execution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Question to ask"},
                    "options": {"type": "array", "items": {"type": "string"}, "description": "Optional list of choices"},
                    "default": {"type": "string", "description": "Default answer if user presses Enter"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob_files",
            "description": "Find files matching a glob pattern under the current working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern, e.g., '**/*.py'"},
                    "max_results": {"type": "integer", "description": "Max results (default 200).", "default": 200},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_env",
            "description": "Read an environment variable.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Environment variable name"},
                    "default": {"type": "string", "description": "Default if not set"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_info",
            "description": "Show basic system info (OS, CPU, memory, disk).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "which_command",
            "description": "Locate an executable in PATH.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Command to locate"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_symbol",
            "description": "Find function/class/variable definitions using ripgrep patterns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {"type": "string", "description": "Symbol to find"},
                    "symbol_type": {
                        "type": "string",
                        "enum": ["function", "class", "variable", "any"],
                        "description": "Type of symbol",
                        "default": "any",
                    },
                    "language": {
                        "type": "string",
                        "enum": ["python", "javascript", "typescript", "go", "rust", "java", "any"],
                        "description": "Language to tailor patterns",
                        "default": "any",
                    },
                    "max_results": {"type": "integer", "description": "Max results", "default": 20},
                },
                "required": ["symbol_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": "Apply a unified diff patch to the current repo using git apply.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {"type": "string", "description": "Unified diff patch content"},
                },
                "required": ["patch"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_background",
            "description": "Run a command in the background and return PID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to run"},
                    "log_file": {"type": "string", "description": "Optional log file path"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "db_query",
            "description": "Execute a SQL query (read-only by default).",
            "parameters": {
                "type": "object",
                "properties": {
                    "connection_string": {"type": "string", "description": "DB connection string"},
                    "query": {"type": "string", "description": "SQL query"},
                    "allow_write": {"type": "boolean", "description": "Allow write operations", "default": False},
                    "max_rows": {"type": "integer", "description": "Max rows to return", "default": 100},
                },
                "required": ["connection_string", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_tests",
            "description": "Generate test cases for a function using the LLM (writes a test file).",
            "parameters": {
                "type": "object",
                "properties": {
                    "function_name": {"type": "string", "description": "Function to test"},
                    "file_path": {"type": "string", "description": "Source file path"},
                    "test_file_path": {"type": "string", "description": "Output test file path"},
                    "framework": {"type": "string", "enum": ["pytest", "unittest"], "default": "pytest"},
                },
                "required": ["function_name", "file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run tests (default pytest) with timeout.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Test command", "default": "pytest"},
                    "timeout": {"type": "integer", "description": "Timeout seconds (default 120).", "default": 120},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_lint",
            "description": "Run lint/format command (default: ruff check).",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Lint command", "default": "ruff check"},
                    "timeout": {"type": "integer", "description": "Timeout seconds (default 120).", "default": 120},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_type_check",
            "description": "Run type checks (default: mypy .).",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Type check command", "default": "mypy ."},
                    "timeout": {"type": "integer", "description": "Timeout seconds (default 120).", "default": 120},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_search",
            "description": "Ripgrep code search with context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Pattern to search for."},
                    "glob": {"type": "string", "description": "Optional glob, e.g., '*.py'."},
                    "context": {"type": "integer", "description": "Context lines (default 2).", "default": 2},
                    "max_results": {"type": "integer", "description": "Max matches (default 20).", "default": 20},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "python_exec",
            "description": "Execute Python code in a sandbox with optional files/requirements.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute."},
                    "timeout": {"type": "number", "description": "Timeout seconds.", "default": 10},
                    "persist": {"type": "boolean", "description": "Persist session state.", "default": False},
                    "globals": {"type": "boolean", "description": "Allow full builtins/globals.", "default": True},
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["path", "content"],
                        },
                    },
                    "requirements": {"type": "array", "items": {"type": "string"}},
                    "session_id": {"type": "string", "description": "Optional session id when persist=true."},
                    "max_memory_mb": {"type": "integer", "description": "Memory limit MB."}
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "docker_ps",
            "description": "List running docker containers.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "docker_images",
            "description": "List local docker images.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "docker_logs",
            "description": "Fetch docker logs for a container.",
            "parameters": {
                "type": "object",
                "properties": {
                    "container": {"type": "string", "description": "Container name or ID."},
                    "tail": {"type": "integer", "description": "Number of lines from the end (default 100).", "default": 100},
                },
                "required": ["container"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "docker_stop",
            "description": "Stop a docker container by name/ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "container": {"type": "string", "description": "Container name or ID."},
                },
                "required": ["container"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "docker_compose",
            "description": "Run a docker-compose command in the current directory (default: ps).",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {"type": "string", "description": "Arguments to pass to docker-compose (default: ps).", "default": "ps"},
                    "timeout": {"type": "integer", "description": "Timeout seconds (default 120).", "default": 120},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Show git status (short).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show git diff for working tree (optional path).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Optional path to diff."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Show recent git log entries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of commits (default 5).", "default": 5},
                    "oneline": {"type": "boolean", "description": "Show oneline format (default true).", "default": True},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pip_install",
            "description": "Install a Python package into the current environment using pip.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Package spec, e.g., requests==2.32.3"},
                    "timeout": {"type": "integer", "description": "Timeout seconds (default 120).", "default": 120},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "npm_install",
            "description": "Install an npm package (global disabled; runs in CWD).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Package name (optionally with version @)."},
                    "timeout": {"type": "integer", "description": "Timeout seconds (default 120).", "default": 120},
                },
                "required": ["name"],
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
    parser.add_argument(
        "--show-thinking",
        dest="show_thinking",
        action="store_true",
        help="Print a thinking notice before responses (default on)",
    )
    parser.add_argument(
        "--no-show-thinking",
        dest="show_thinking",
        action="store_false",
        help="Disable thinking notice",
    )
    parser.set_defaults(show_thinking=True)
    parser.add_argument("--list-transcripts", action="store_true", help="List available transcripts and exit")
    parser.set_defaults(func=run_chat)


def run_chat(args, settings):
    logger = logging.getLogger(__name__)
    client = LLMClient(settings)
    convo = Conversation()
    transcript = None

    transcript_dir = Path(args.transcript_dir or settings.data_dir / "sessions")
    if args.list_transcripts:
        _print_transcripts(transcript_dir)
        return

    if args.resume:
        convo = _load_transcript(args.resume, logger)
    convo.add_system(args.system)
    current_system = args.system

    # Setup tab completion for slash commands
    setup_command_completion()

    if not args.no_transcript:
        transcript_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        transcript = (transcript_dir / f"session-{ts}.jsonl").resolve()
        logger.info("Writing transcript to %s", transcript)

    print("Interactive chat. Type 'exit' or 'quit' (or Ctrl-D) to leave.")
    print("Type /help for slash commands.")
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not user_input:
            continue
        if user_input.startswith("/"):
            result = handle_slash_command(user_input, settings, convo, client)
            if result.get("exit"):
                break
            if result.get("system_prompt"):
                current_system = result["system_prompt"]
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("Bye.")
            break

        convo.add_user(user_input)
        if transcript:
            _append_transcript(transcript, {"role": "user", "content": user_input})

        stop_event = None
        spinner_thread = None
        try:
            start = time.perf_counter()
            if args.show_thinking:
                stop_event = threading.Event()
                spinner_thread = threading.Thread(target=_spinner, args=(stop_event, start), daemon=True)
                spinner_thread.start()

            handle_chat_turn(client, convo, settings, transcript, logger, stop_event=stop_event)
            elapsed = time.perf_counter() - start
            print(f"(completed in {elapsed:.2f}s)")
        except KeyboardInterrupt:
            print("\nRequest cancelled. Ready for next prompt.")
        except Exception as exc:  # pragma: no cover - interactive path
            logger.error("Chat failed: %s", exc)
            print(f"Error talking to model: {exc}")
            break
        finally:
            if stop_event:
                stop_event.set()
            if spinner_thread:
                spinner_thread.join(timeout=1)
                sys.stderr.write("\r")
                sys.stderr.flush()


def handle_chat_turn(client: LLMClient, convo: Conversation, settings, transcript, logger, stop_event=None):
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
            elif name == "web_search":
                result = _handle_web_search(tool_call.function.arguments)
            elif name == "run_tests":
                result = _handle_run_tests(tool_call.function.arguments)
            elif name == "run_lint":
                result = _handle_run_lint(tool_call.function.arguments)
            elif name == "run_type_check":
                result = _handle_run_type_check(tool_call.function.arguments)
            elif name == "code_search":
                result = _handle_code_search(tool_call.function.arguments)
            elif name == "pip_install":
                result = _handle_pip_install(tool_call.function.arguments)
            elif name == "npm_install":
                result = _handle_npm_install(tool_call.function.arguments)
            elif name == "docker_ps":
                result = _handle_docker_ps()
            elif name == "docker_images":
                result = _handle_docker_images()
            elif name == "docker_logs":
                result = _handle_docker_logs(tool_call.function.arguments)
            elif name == "docker_stop":
                result = _handle_docker_stop(tool_call.function.arguments)
            elif name == "docker_compose":
                result = _handle_docker_compose(tool_call.function.arguments)
            elif name == "git_status":
                result = _handle_git_status()
            elif name == "git_diff":
                result = _handle_git_diff(tool_call.function.arguments)
            elif name == "git_log":
                result = _handle_git_log(tool_call.function.arguments)
            elif name == "python_exec":
                result = _handle_python_exec(tool_call.function.arguments, settings)
            elif name == "run_bash_script":
                result = _handle_run_bash_script(tool_call.function.arguments)
            elif name == "edit_file":
                result = _handle_edit_file(tool_call.function.arguments)
            elif name == "http_request":
                result = _handle_http_request(tool_call.function.arguments)
            elif name == "git_add":
                result = _handle_git_add(tool_call.function.arguments)
            elif name == "git_commit":
                result = _handle_git_commit(tool_call.function.arguments)
            elif name == "git_push":
                result = _handle_git_push(tool_call.function.arguments)
            elif name == "ask_user":
                result = _handle_ask_user(tool_call.function.arguments)
            elif name == "glob_files":
                result = _handle_glob_files(tool_call.function.arguments)
            elif name == "read_env":
                result = _handle_read_env(tool_call.function.arguments)
            elif name == "system_info":
                result = _handle_system_info()
            elif name == "which_command":
                result = _handle_which_command(tool_call.function.arguments)
            elif name == "find_symbol":
                result = _handle_find_symbol(tool_call.function.arguments)
            elif name == "apply_patch":
                result = _handle_apply_patch(tool_call.function.arguments)
            elif name == "run_background":
                result = _handle_run_background(tool_call.function.arguments)
            elif name == "db_query":
                result = _handle_db_query(tool_call.function.arguments)
            elif name == "generate_tests":
                result = _handle_generate_tests(tool_call.function.arguments, client, settings)
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
    try:
        for chunk in resp:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                token = delta.content
                assistant_text += token
                sys.stdout.write(token)
                sys.stdout.flush()
    except KeyboardInterrupt:
        sys.stdout.write("\n(cancelled)\n")
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


def _print_transcripts(transcript_dir: Path):
    if not transcript_dir.exists():
        print(f"No transcript directory found at {transcript_dir}")
        return
    files = sorted(transcript_dir.glob("session-*.jsonl"))
    if not files:
        print(f"No transcripts found in {transcript_dir}")
        return
    print(f"Transcripts in {transcript_dir}:")
    for f in files:
        print(f"- {f.name}")


def _spinner(stop_event: threading.Event, start_time: float):
    chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    i = 0
    while not stop_event.is_set():
        dots = "." * ((i % 3) + 1)
        elapsed = time.perf_counter() - start_time
        msg = f"\r{elapsed:5.1f}s thinking{dots} {chars[i % len(chars)]} "
        sys.stderr.write(msg)
        sys.stderr.flush()
        time.sleep(0.15)
        i += 1


def _status(message: str):
    sys.stderr.write(f"\n{message}\n")
    sys.stderr.flush()


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


def _handle_run_bash_script(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for run_bash_script: {exc}"

    script = args.get("script")
    timeout = int(args.get("timeout", 60))
    cwd = args.get("cwd") or None
    env_overrides = args.get("env") or {}
    if not script:
        return "run_bash_script failed: 'script' is required."

    lowered = script.lower()
    if lowered.strip().startswith("sudo ") or " apt-get" in lowered:
        return "run_bash_script blocked: disallowed sudo/apt-get. Run manually if intended."

    env = os.environ.copy()
    for k, v in env_overrides.items():
        env[str(k)] = str(v)

    try:
        result = subprocess.run(
            ["/bin/bash", "-lc", script],
            capture_output=True,
            text=True,
            cwd=cwd or Path.cwd(),
            env=env,
            timeout=timeout,
        )
    except Exception as exc:
        return f"run_bash_script failed: {exc}"

    out = result.stdout.strip()
    err = result.stderr.strip()
    status = result.returncode
    parts = [f"run_bash_script exit={status}"]
    if out:
        parts.append(f"stdout:\n{out}")
    if err:
        parts.append(f"stderr:\n{err}")
    return "\n".join(parts)


def _handle_edit_file(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for edit_file: {exc}"

    path_arg = args.get("path")
    old_string = args.get("old_string")
    new_string = args.get("new_string")
    replace_all = bool(args.get("replace_all", False))

    if not path_arg or old_string is None or new_string is None:
        return "edit_file failed: 'path', 'old_string', and 'new_string' are required."
    if old_string == new_string:
        return "edit_file failed: old_string and new_string are identical."

    base, target, err = _resolve_path(path_arg)
    if err:
        return f"edit_file blocked: {err}"
    if not target.exists():
        return f"edit_file failed: file not found ({target.relative_to(base)})."
    if target.is_dir():
        return "edit_file failed: target is a directory."

    try:
        content = target.read_text(encoding="utf-8")
    except Exception as exc:
        return f"edit_file failed to read file: {exc}"

    count = content.count(old_string)
    if count == 0:
        return f"edit_file failed: old_string not found in {target.relative_to(base)}."
    if count > 1 and not replace_all:
        return f"edit_file failed: found {count} occurrences (not unique). Set replace_all=true to replace all."

    new_content = content.replace(old_string, new_string, count if replace_all else 1)
    try:
        target.write_text(new_content, encoding="utf-8")
    except Exception as exc:
        return f"edit_file failed to write file: {exc}"

    occurrences = count if replace_all else 1
    return f"edit_file success: replaced {occurrences} occurrence(s) in {target.relative_to(base)}"


def _handle_http_request(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for http_request: {exc}"

    url = (args.get("url") or "").strip()
    method = (args.get("method", "GET") or "GET").upper()
    headers = args.get("headers") or {}
    body = args.get("body")
    timeout = int(args.get("timeout", 30))
    max_size = int(args.get("max_response_size", 1_048_576))

    if not url:
        return "http_request failed: 'url' is required."
    if not url.startswith(("http://", "https://")):
        return "http_request failed: URL must start with http:// or https://"
    if method not in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}:
        return f"http_request failed: unsupported method '{method}'"

    timeout = min(timeout, 60)

    try:
        import requests
    except ImportError:
        return "http_request failed: requests library not installed. Run: pip install requests"

    try:
        resp = requests.request(
            method=method,
            url=url,
            headers=headers,
            data=body,
            timeout=timeout,
            allow_redirects=True,
            stream=True,
        )
        content_chunks = []
        total_size = 0
        for chunk in resp.iter_content(chunk_size=8192):
            total_size += len(chunk)
            if total_size > max_size:
                return f"http_request failed: response exceeds max_response_size ({max_size} bytes)"
            content_chunks.append(chunk)
        content = b"".join(content_chunks).decode("utf-8", errors="replace")

        lines = [
            f"http_request {method} {url}",
            f"Status: {resp.status_code} {resp.reason}",
            f"Content-Length: {len(content)} bytes",
            "",
            "Headers:",
        ]
        for k, v in resp.headers.items():
            lines.append(f"  {k}: {v}")
        lines.append("")
        lines.append("Body:")
        lines.append(content[:10000])
        if len(content) > 10000:
            lines.append(f"... (truncated, {len(content) - 10000} more bytes)")
        return "\n".join(lines)
    except requests.exceptions.Timeout:
        return f"http_request failed: request timed out after {timeout}s"
    except requests.exceptions.RequestException as exc:
        return f"http_request failed: {exc}"
    except Exception as exc:
        return f"http_request failed: {exc}"


def _handle_git_add(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for git_add: {exc}"

    paths = args.get("paths") or []
    add_all = bool(args.get("all", False))

    if not paths and not add_all:
        return "git_add failed: provide 'paths' or set 'all=true'."

    base = Path.cwd()
    if add_all:
        cmd = "git add -A"
    else:
        for p in paths:
            try:
                (base / p).resolve().relative_to(base)
            except ValueError:
                return f"git_add blocked: path outside workspace ({p})"
        cmd = "git add " + " ".join(f'"{p}"' for p in paths)

    try:
        res = subprocess.run(
            ["/bin/bash", "-lc", cmd],
            capture_output=True,
            text=True,
            cwd=base,
            timeout=30,
        )
    except Exception as exc:
        return f"git_add failed: {exc}"

    if res.returncode != 0:
        return f"git_add failed (exit {res.returncode}):\n{res.stderr.strip() or res.stdout.strip()}"

    status = subprocess.run(
        ["git", "diff", "--cached", "--name-status"],
        capture_output=True,
        text=True,
        cwd=base,
        timeout=10,
    )
    staged = status.stdout.strip() or "(no changes staged)"
    return f"git_add success:\n{staged}"


def _handle_git_commit(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for git_commit: {exc}"

    message = (args.get("message") or "").strip()
    amend = bool(args.get("amend", False))
    if not message:
        return "git_commit failed: 'message' is required."

    message_escaped = message.replace('"', '\\"')
    amend_flag = "--amend" if amend else ""
    cmd = f'git commit {amend_flag} -m "{message_escaped}"'

    try:
        res = subprocess.run(
            ["/bin/bash", "-lc", cmd],
            capture_output=True,
            text=True,
            cwd=Path.cwd(),
            timeout=30,
        )
    except Exception as exc:
        return f"git_commit failed: {exc}"

    out = res.stdout.strip()
    err = res.stderr.strip()
    if res.returncode != 0:
        return f"git_commit failed (exit {res.returncode}):\n{err or out}"
    return f"git_commit success:\n{out or err}"


def _handle_git_push(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for git_push: {exc}"

    remote = args.get("remote", "origin")
    branch = args.get("branch")
    force = bool(args.get("force", False))
    set_upstream = bool(args.get("set_upstream", False))

    base = Path.cwd()
    if not branch:
        branch_res = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=base,
            timeout=5,
        )
        branch = branch_res.stdout.strip()
        if not branch:
            return "git_push failed: could not determine current branch."

    if force and branch in {"main", "master"}:
        return f"git_push blocked: force push to {branch} is dangerous. Use git manually if intended."

    cmd_parts = ["git", "push"]
    if set_upstream:
        cmd_parts.append("-u")
    if force:
        cmd_parts.append("--force")
    cmd_parts.extend([remote, branch])
    cmd = " ".join(cmd_parts)

    try:
        res = subprocess.run(
            ["/bin/bash", "-lc", cmd],
            capture_output=True,
            text=True,
            cwd=base,
            timeout=120,
        )
    except Exception as exc:
        return f"git_push failed: {exc}"

    out = res.stdout.strip()
    err = res.stderr.strip()
    if res.returncode != 0:
        return f"git_push failed (exit {res.returncode}):\n{err or out}"
    return f"git_push success to {remote}/{branch}:\n{err or out}"


def _handle_ask_user(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for ask_user: {exc}"
    question = (args.get("question") or "").strip()
    options = args.get("options") or []
    default = args.get("default")
    if not question:
        return "ask_user failed: 'question' is required."
    prompt = question
    if options:
        prompt += f" (options: {', '.join(options)})"
    if default:
        prompt += f" [default: {default}]"
    prompt += "\n> "
    try:
        answer = input(prompt).strip()
    except Exception as exc:
        return f"ask_user failed: {exc}"
    if not answer and default is not None:
        answer = default
    return f"ask_user response: {answer}"


def _handle_glob_files(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for glob_files: {exc}"
    pattern = args.get("pattern")
    max_results = int(args.get("max_results", 200))
    if not pattern:
        return "glob_files failed: 'pattern' is required."
    base = Path.cwd().resolve()
    matches = []
    try:
        for path in base.rglob(pattern):
            if path.is_file():
                rel = path.relative_to(base)
                matches.append(str(rel))
                if len(matches) >= max_results:
                    break
    except Exception as exc:
        return f"glob_files failed: {exc}"
    if not matches:
        return f"glob_files: no matches for pattern '{pattern}'"
    return "glob_files results:\n" + "\n".join(matches)


def _handle_read_env(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for read_env: {exc}"
    name = args.get("name")
    default = args.get("default")
    if not name:
        return "read_env failed: 'name' is required."
    # Block obviously sensitive vars
    forbidden = {"AWS_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY_ID", "GITHUB_TOKEN", "JAY_API_KEY"}
    if name.upper() in forbidden:
        return f"read_env blocked: '{name}' is disallowed."
    value = os.getenv(name, default)
    return f"read_env {name}={value}"


def _handle_system_info() -> str:
    try:
        import platform
        import psutil  # type: ignore
    except ImportError:
        return "system_info failed: psutil not installed. Run: pip install psutil"
    info = {
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "memory_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "disk_gb": round(psutil.disk_usage("/").total / (1024**3), 2),
    }
    return "system_info:\n" + "\n".join(f"{k}: {v}" for k, v in info.items())


def _handle_which_command(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for which_command: {exc}"
    name = (args.get("name") or "").strip()
    if not name:
        return "which_command failed: 'name' is required."
    path = shutil.which(name)
    if not path:
        return f"which_command: '{name}' not found in PATH."
    return f"which_command: {name} -> {path}"


def _handle_find_symbol(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for find_symbol: {exc}"
    symbol_name = (args.get("symbol_name") or "").strip()
    symbol_type = args.get("symbol_type", "any")
    language = args.get("language", "any")
    max_results = int(args.get("max_results", 20))
    if not symbol_name:
        return "find_symbol failed: 'symbol_name' is required."

    patterns = []
    if language in {"python", "any"}:
        if symbol_type in {"function", "any"}:
            patterns.append(f"def {symbol_name}\\(")
        if symbol_type in {"class", "any"}:
            patterns.append(f"class {symbol_name}[\\(:]")
        if symbol_type in {"variable", "any"}:
            patterns.append(f"^{symbol_name}\\s*=")
    if language in {"javascript", "typescript", "any"}:
        if symbol_type in {"function", "any"}:
            patterns.append(f"function {symbol_name}\\(")
            patterns.append(f"const {symbol_name}\\s*=\\s*\\(")
            patterns.append(f"const {symbol_name}\\s*=\\s*async\\s*\\(")
        if symbol_type in {"class", "any"}:
            patterns.append(f"class {symbol_name}\\s*{{")
        if symbol_type in {"variable", "any"}:
            patterns.append(f"(const|let|var) {symbol_name}\\s*=")
    if language in {"go", "any"}:
        if symbol_type in {"function", "any"}:
            patterns.append(f"func {symbol_name}\\(")
        if symbol_type in {"variable", "any"}:
            patterns.append(f"var {symbol_name}\\s")

    if not patterns:
        return f"find_symbol: no patterns for language '{language}' and type '{symbol_type}'"

    pattern_str = "|".join(f"({p})" for p in patterns)
    cmd = [
        "rg",
        "--no-heading",
        "--line-number",
        "--color",
        "never",
        "-e",
        pattern_str,
        "--max-count",
        str(max_results),
        ".",
    ]
    try:
        result = subprocess.run(cmd, cwd=Path.cwd(), capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        return "find_symbol failed: ripgrep (rg) not available."
    except Exception as exc:
        return f"find_symbol failed: {exc}"

    output = result.stdout.strip()
    if not output:
        return f"find_symbol: no matches for '{symbol_name}' (type={symbol_type}, language={language})"
    lines = output.splitlines()[:max_results]
    return f"find_symbol found {len(lines)} match(es):\n" + "\n".join(lines)


def _handle_apply_patch(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for apply_patch: {exc}"
    patch = args.get("patch")
    if not patch:
        return "apply_patch failed: 'patch' is required."
    base = Path.cwd()
    patch_file = None
    try:
        fd, patch_file = tempfile.mkstemp(prefix="agent-patch-", suffix=".patch", dir=base)
        Path(patch_file).write_text(patch, encoding="utf-8")
        res = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", patch_file],
            cwd=base,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if res.returncode != 0:
            return f"apply_patch failed (exit {res.returncode}):\n{res.stderr.strip() or res.stdout.strip()}"
        return "apply_patch success"
    except Exception as exc:
        return f"apply_patch failed: {exc}"
    finally:
        if patch_file:
            try:
                Path(patch_file).unlink()
            except Exception:
                pass


def _handle_run_background(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for run_background: {exc}"
    command = (args.get("command") or "").strip()
    log_file = args.get("log_file")
    if not command:
        return "run_background failed: 'command' is required."
    lowered = command.lower()
    if lowered.startswith("sudo ") or " apt-get" in lowered:
        return "run_background blocked: disallowed sudo/apt-get."

    base = Path.cwd()
    stdout_dest = subprocess.PIPE
    stderr_dest = subprocess.PIPE
    log_handle = None
    if log_file:
        _, log_path, err = _resolve_path(log_file)
        if err:
            return f"run_background blocked: {err}"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = open(log_path, "w")
            stdout_dest = log_handle
            stderr_dest = subprocess.STDOUT
        except Exception as exc:
            return f"run_background failed to open log file: {exc}"
    try:
        proc = subprocess.Popen(
            ["/bin/bash", "-lc", command],
            stdout=stdout_dest,
            stderr=stderr_dest,
            cwd=base,
            start_new_session=True,
        )
        pid = proc.pid
        log_info = f" (logging to {log_file})" if log_file else ""
        return f"run_background: started PID {pid}{log_info}\nCommand: {command}"
    except Exception as exc:
        return f"run_background failed: {exc}"
    finally:
        if log_handle:
            log_handle.close()


def _handle_db_query(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for db_query: {exc}"
    conn_str = (args.get("connection_string") or "").strip()
    query = (args.get("query") or "").strip()
    allow_write = bool(args.get("allow_write", False))
    max_rows = int(args.get("max_rows", 100))
    if not conn_str or not query:
        return "db_query failed: 'connection_string' and 'query' are required."

    query_upper = query.upper().strip()
    write_keywords = {"INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE"}
    is_write = any(query_upper.startswith(kw) for kw in write_keywords)
    if is_write and not allow_write:
        return "db_query blocked: write operation detected. Set allow_write=true to proceed."

    try:
        import sqlalchemy
        from sqlalchemy import create_engine, text
    except ImportError:
        return "db_query failed: sqlalchemy not installed. Run: pip install sqlalchemy"

    try:
        engine = create_engine(
            conn_str,
            connect_args={"timeout": 30} if "sqlite" in conn_str else {},
            pool_pre_ping=True,
        )
        with engine.connect() as conn:
            result = conn.execute(text(query))
            if query_upper.startswith(("SELECT", "SHOW", "DESCRIBE")):
                rows = result.fetchmany(max_rows)
                if not rows:
                    return "db_query: query returned 0 rows"
                columns = list(result.keys())
                lines = [f"db_query: {len(rows)} row(s) returned:"]
                lines.append(" | ".join(columns))
                lines.append("-" * (sum(len(c) for c in columns) + 3 * len(columns)))
                for row in rows:
                    lines.append(" | ".join(str(v) for v in row))
                if len(rows) == max_rows:
                    lines.append(f"(limited to {max_rows} rows)")
                return "\n".join(lines)
            else:
                conn.commit()
                affected = result.rowcount
                return f"db_query success: {affected} row(s) affected"
    except Exception as exc:
        return f"db_query failed: {exc}"


def _handle_generate_tests(raw_args: str, llm_client: LLMClient, settings) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for generate_tests: {exc}"

    function_name = (args.get("function_name") or "").strip()
    file_path = (args.get("file_path") or "").strip()
    test_file_path = args.get("test_file_path")
    framework = args.get("framework", "pytest")
    if not function_name or not file_path:
        return "generate_tests failed: 'function_name' and 'file_path' are required."

    base, source_path, err = _resolve_path(file_path)
    if err:
        return f"generate_tests blocked: {err}"
    if not source_path.exists():
        return f"generate_tests failed: file not found ({file_path})"
    try:
        source_code = source_path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"generate_tests failed to read file: {exc}"

    if not test_file_path:
        test_file_path = f"test_{source_path.name}"
    _, test_path, err2 = _resolve_path(test_file_path)
    if err2:
        return f"generate_tests blocked: {err2}"

    prompt = f"""Generate {framework} test cases for the function `{function_name}` from this code:

```
{source_code[:5000]}
```

Requirements:
- Create comprehensive tests (normal, edge, error cases)
- Use {framework}
- Include docstrings
- Self-contained and runnable
- Return ONLY the test code
Generate the complete test file:"""

    try:
        response = llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            max_tokens=2000,
        )
        test_code = response.choices[0].message.content.strip()
        if test_code.startswith("```"):
            lines = test_code.split("\n")
            test_code = "\n".join(lines[1:-1])
        test_path.write_text(test_code, encoding="utf-8")
        return f"generate_tests success: created {test_path.relative_to(base)} ({len(test_code.splitlines())} lines)"
    except Exception as exc:
        return f"generate_tests failed: {exc}"

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


def _handle_run_tests(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for run_tests: {exc}"
    cmd = args.get("cmd", "pytest")
    timeout = int(args.get("timeout", 120))
    return _run_command(cmd, timeout, label="run_tests")


def _handle_run_lint(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for run_lint: {exc}"
    cmd = args.get("cmd", "ruff check")
    timeout = int(args.get("timeout", 120))
    return _run_command(cmd, timeout, label="run_lint")


def _handle_run_type_check(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for run_type_check: {exc}"
    cmd = args.get("cmd", "mypy .")
    timeout = int(args.get("timeout", 120))
    return _run_command(cmd, timeout, label="run_type_check")


def _handle_pip_install(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for pip_install: {exc}"
    name = args.get("name")
    timeout = int(args.get("timeout", 120))
    if not name:
        return "pip_install failed: 'name' is required."
    cmd = f"pip install {name}"
    return _run_command(cmd, timeout, label="pip_install")


def _handle_npm_install(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for npm_install: {exc}"
    name = args.get("name")
    timeout = int(args.get("timeout", 120))
    if not name:
        return "npm_install failed: 'name' is required."
    cmd = f"npm install {name}"
    return _run_command(cmd, timeout, label="npm_install")


def _handle_docker_ps() -> str:
    return _run_command("docker ps", 30, label="docker_ps")


def _handle_docker_images() -> str:
    return _run_command("docker images", 30, label="docker_images")


def _handle_docker_logs(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for docker_logs: {exc}"
    container = args.get("container")
    tail = int(args.get("tail", 100))
    if not container:
        return "docker_logs failed: 'container' is required."
    cmd = f"docker logs --tail {tail} {container}"
    return _run_command(cmd, 60, label="docker_logs")


def _handle_docker_stop(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for docker_stop: {exc}"
    container = args.get("container")
    if not container:
        return "docker_stop failed: 'container' is required."
    cmd = f"docker stop {container}"
    return _run_command(cmd, 60, label="docker_stop")


def _handle_docker_compose(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for docker_compose: {exc}"
    compose_args = args.get("args", "ps")
    timeout = int(args.get("timeout", 120))
    cmd = f"docker-compose {compose_args}"
    return _run_command(cmd, timeout, label="docker_compose")


def _handle_git_status() -> str:
    return _run_command("git status -sb", 30, label="git_status")


def _handle_git_diff(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for git_diff: {exc}"
    path = args.get("path")
    cmd = "git diff"
    if path:
        cmd = f"git diff -- {path}"
    return _run_command(cmd, 60, label="git_diff")


def _handle_git_log(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for git_log: {exc}"
    limit = int(args.get("limit", 5))
    oneline = bool(args.get("oneline", True))
    fmt = "--oneline" if oneline else ""
    cmd = f"git log {fmt} -{limit}".strip()
    return _run_command(cmd, 60, label="git_log")


def _handle_python_exec(raw_args: str, settings) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for python_exec: {exc}"

    code = args.get("code")
    if not code:
        return "python_exec failed: 'code' is required."

    timeout = float(args.get("timeout", 10))
    persist = bool(args.get("persist", False))
    globals_mode = bool(args.get("globals", True))
    files = args.get("files") or []
    requirements = args.get("requirements") or []
    session_id = args.get("session_id")
    max_memory_mb = args.get("max_memory_mb")

    executor = PythonExecutor(settings)
    result = executor.execute(
        code=code,
        timeout=timeout,
        persist=persist,
        globals_mode=globals_mode,
        files=files,
        requirements=requirements,
        session_id=session_id,
        max_memory_mb=max_memory_mb,
    )
    exc = result.exception
    exc_text = ""
    if exc:
        exc_text = f"\nException: {exc}"
    return (
        f"python_exec stdout:\n{result.stdout}"
        f"\npython_exec stderr:\n{result.stderr}"
        f"\nresult: {result.result}"
        f"\nlocals: {result.locals}"
        f"\nfiles_written: {result.files_written}"
        f"\nexecution_time: {result.execution_time:.3f}s"
        f"{exc_text}"
    )


def _run_command(cmd: str, timeout: int, label: str) -> str:
    log = logging.getLogger(__name__)
    log.info("%s start cmd=%s timeout=%s", label, cmd, timeout)
    try:
        result = subprocess.run(
            ["/bin/bash", "-lc", cmd],
            capture_output=True,
            text=True,
            cwd=Path.cwd(),
            timeout=timeout,
        )
    except FileNotFoundError:
        log.warning("%s failed: command not found", label)
        return f"{label} failed: command not found."
    except Exception as exc:
        log.warning("%s failed: %s", label, exc)
        return f"{label} failed: {exc}"

    out = result.stdout.strip()
    err = result.stderr.strip()
    status = result.returncode
    parts = [f"{label} exit={status}", f"cmd: {cmd}"]
    log.info("%s exit=%s", label, status)
    if out:
        parts.append(f"stdout:\n{out}")
    if err:
        parts.append(f"stderr:\n{err}")
    return "\n".join(parts)
def _handle_web_search(raw_args: str) -> str:
    from ...tools.web_search import serpapi_search, fetch_page, overlap_score, summarize
    log = logging.getLogger(__name__)
    start_time = time.perf_counter()
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for web_search: {exc}"

    query = args.get("query")
    num = max(1, min(int(args.get("num", 5)), 10))
    site = args.get("site")
    fetch_n = max(0, min(int(args.get("fetch", 1)), 3))
    max_bytes = int(args.get("max_bytes", 1_000_000))
    max_fetch_time = int(args.get("max_fetch_time", 15))
    if not query:
        return "web_search failed: 'query' is required."

    log.info("web_search start query=%s num=%s site=%s fetch=%s", query, num, site, fetch_n)
    result = serpapi_search(query, num=num, site=site)
    if "error" in result:
        return f"web_search failed: {result['error']}"

    results = result.get("results", [])
    log.info("web_search: %d results before rerank", len(results))
    _status(f"web_search: search done in {time.perf_counter()-start_time:.2f}s; {len(results)} results; fetching {min(fetch_n,len(results)) if fetch_n else 0}")
    # Rerank by simple overlap
    reranked = sorted(results, key=lambda x: overlap_score(x.get("snippet", "") or "", query), reverse=True)
    lines = []
    to_fetch = reranked[:fetch_n] if fetch_n else []
    fetched = []
    for item in to_fetch:
        link = item.get("link")
        if not link:
            continue
        content = fetch_page(link, max_bytes=max_bytes, timeout=max_fetch_time)
        if not content:
            fetched.append({"link": link, "summary": "(skipped: too large or failed)"})
            continue
        summary = summarize(content)
        fetched.append({"link": link, "summary": summary})
    if fetch_n:
        _status(f"web_search: fetched {len(fetched)}/{len(to_fetch)} links in {time.perf_counter()-start_time:.2f}s; formatting…")
    else:
        _status(f"web_search: skipping fetch (fetch=0); formatting results")

    try:
        for idx, item in enumerate(reranked, 1):
            title = item.get("title") or "(no title)"
            link = item.get("link") or "(no link)"
            snippet = item.get("snippet") or ""
            score = overlap_score(snippet, query)
            score_str = f" (score {score:.2f})" if score else ""
            if link and link != "(no link)":
                lines.append(f"{idx}. [{title}]({link}){score_str}\n   {snippet}")
            else:
                lines.append(f"{idx}. {title}{score_str}\n   {snippet}")

        if fetched:
            lines.append("\nSummaries:")
            for f in fetched:
                lines.append(f"- {f['link']}\n  {f['summary']}")
    except KeyboardInterrupt:
        log.info("web_search cancelled by user")
        return "web_search cancelled."

    header = f"web_search results for '{query}'"
    if site:
        header += f" (site:{site})"
    if lines:
        return header + ":\n" + "\n".join(lines)
    return header + ":\n(no results)"


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


def _handle_code_search(raw_args: str) -> str:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for code_search: {exc}"

    query = args.get("query")
    glob = args.get("glob")
    context = int(args.get("context", 2))
    max_results = int(args.get("max_results", 20))
    if not query:
        return "code_search failed: 'query' is required."

    base = Path.cwd().resolve()
    cmd = [
        "rg",
        "--no-heading",
        f"-C{context}",
        "--line-number",
        "--color",
        "never",
        "--max-count",
        str(max_results),
        query,
        ".",
    ]
    if glob:
        cmd.extend(["--glob", glob])
    try:
        proc = subprocess.run(cmd, cwd=base, capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        return "code_search failed: ripgrep (rg) not available."
    except Exception as exc:
        return f"code_search failed: {exc}"

    output = proc.stdout.strip()
    if not output:
        return f"code_search: no matches for '{query}'{f' with glob {glob}' if glob else ''}."
    lines = output.splitlines()[:max_results]
    return "code_search results:\n" + "\n".join(lines)


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
