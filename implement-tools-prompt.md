# AI Implementation Prompt: Enhanced Tools for jay-agent

## Context

You are implementing new tools for **jay-agent**, a terminal-first CLI agent that uses an OpenAI-compatible API (Ollama) to execute tasks through tool-calling. The agent is built in Python and follows a specific architecture pattern.

### Current Architecture

**Project Structure:**
```
agent/
├── cli/
│   ├── main.py                 # CLI entrypoint
│   └── commands/
│       └── chat.py             # Tool definitions and handlers (MAIN FILE TO EDIT)
├── core/
│   ├── llm_client.py          # LLM API wrapper
│   ├── config.py              # Settings management
│   └── safety.py              # Safety constraints
└── tools/
    ├── file_ops.py            # File operation helpers
    ├── shell.py               # Shell execution helpers
    ├── python_exec.py         # Python sandbox
    └── web_search.py          # Web search implementation
```

**Current Tool Count:** 34 tools

**Tool Implementation Pattern:**

Each tool requires **THREE components**:

1. **JSON Schema** in the `TOOLS` list (line 28-544 in chat.py)
2. **Handler function** (e.g., `_handle_edit_file`)
3. **Dispatcher entry** in `handle_chat_turn()` (line 636-731)

**Example Tool Implementation:**
```python
# 1. Schema in TOOLS list
{
    "type": "function",
    "function": {
        "name": "example_tool",
        "description": "Clear description of what this tool does.",
        "parameters": {
            "type": "object",
            "properties": {
                "required_param": {
                    "type": "string",
                    "description": "What this parameter is for"
                },
                "optional_param": {
                    "type": "integer",
                    "description": "Optional parameter",
                    "default": 10
                }
            },
            "required": ["required_param"]
        }
    }
}

# 2. Handler function
def _handle_example_tool(raw_args: str) -> str:
    """Handler for example_tool."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for example_tool: {exc}"

    required_param = args.get("required_param")
    optional_param = args.get("optional_param", 10)

    if not required_param:
        return "example_tool failed: 'required_param' is required."

    # Safety checks
    # ... validation logic ...

    try:
        # Implementation
        result = do_something(required_param, optional_param)
        return f"example_tool success: {result}"
    except Exception as exc:
        return f"example_tool failed: {exc}"

# 3. Dispatcher entry in handle_chat_turn()
elif name == "example_tool":
    result = _handle_example_tool(tool_call.function.arguments)
```

**Safety Principles:**
- All file operations constrained to current working directory (CWD)
- Use Path.resolve() and Path.relative_to() to prevent directory traversal
- Timeouts on all subprocess calls
- Confirm flags for destructive operations
- Allowlists for package installation
- Block sudo/apt-get in shell commands
- Return detailed error messages

---

## Your Task

Implement the following **15 new tools** following the established patterns in `agent/cli/commands/chat.py`. For each tool, you must:

1. Add the JSON schema to the `TOOLS` list
2. Implement the handler function
3. Add the dispatcher entry
4. Follow all safety principles
5. Return descriptive success/error messages

---

## Tool Specifications

### TIER 1: Critical Tools (Implement First)

---

#### 1. edit_file

**Purpose:** Precise string-replacement editing to avoid rewriting entire files

**JSON Schema:**
```python
{
    "type": "function",
    "function": {
        "name": "edit_file",
        "description": "Replace exact string match in a file. Fails if old_string is not unique (unless replace_all=true).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative or absolute path to the file to edit"
                },
                "old_string": {
                    "type": "string",
                    "description": "Exact string to find and replace (must be unique unless replace_all=true)"
                },
                "new_string": {
                    "type": "string",
                    "description": "String to replace old_string with"
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "If true, replace all occurrences. If false, error if not unique.",
                    "default": False
                }
            },
            "required": ["path", "old_string", "new_string"]
        }
    }
}
```

**Handler Implementation:**
```python
def _handle_edit_file(raw_args: str) -> str:
    """Replace exact string in file."""
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

    # Safety: resolve path within CWD
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

    # Check uniqueness
    count = content.count(old_string)
    if count == 0:
        return f"edit_file failed: old_string not found in {target.relative_to(base)}."

    if count > 1 and not replace_all:
        return f"edit_file failed: found {count} occurrences of old_string (not unique). Set replace_all=true to replace all."

    # Perform replacement
    if replace_all:
        new_content = content.replace(old_string, new_string)
    else:
        new_content = content.replace(old_string, new_string, 1)

    try:
        target.write_text(new_content, encoding="utf-8")
    except Exception as exc:
        return f"edit_file failed to write file: {exc}"

    occurrences = count if replace_all else 1
    return f"edit_file success: replaced {occurrences} occurrence(s) in {target.relative_to(base)}"
```

---

#### 2. http_request

**Purpose:** Make HTTP requests for API testing, data fetching

**JSON Schema:**
```python
{
    "type": "function",
    "function": {
        "name": "http_request",
        "description": "Make an HTTP request (GET, POST, PUT, DELETE, etc.) with optional headers and body.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL to request (must start with http:// or https://)"
                },
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
                    "description": "HTTP method",
                    "default": "GET"
                },
                "headers": {
                    "type": "object",
                    "description": "Optional HTTP headers as key-value pairs",
                    "default": {}
                },
                "body": {
                    "type": "string",
                    "description": "Optional request body (for POST/PUT/PATCH)"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Request timeout in seconds",
                    "default": 30
                },
                "max_response_size": {
                    "type": "integer",
                    "description": "Maximum response size in bytes (default 1MB)",
                    "default": 1048576
                }
            },
            "required": ["url"]
        }
    }
}
```

**Handler Implementation:**
```python
def _handle_http_request(raw_args: str) -> str:
    """Make HTTP request with safety limits."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for http_request: {exc}"

    url = args.get("url", "").strip()
    method = args.get("method", "GET").upper()
    headers = args.get("headers") or {}
    body = args.get("body")
    timeout = int(args.get("timeout", 30))
    max_size = int(args.get("max_response_size", 1048576))

    if not url:
        return "http_request failed: 'url' is required."

    if not url.startswith(("http://", "https://")):
        return "http_request failed: URL must start with http:// or https://"

    if method not in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}:
        return f"http_request failed: unsupported method '{method}'"

    # Safety: limit timeout
    timeout = min(timeout, 60)

    try:
        import requests
    except ImportError:
        return "http_request failed: requests library not installed. Run: pip install requests"

    try:
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            data=body,
            timeout=timeout,
            allow_redirects=True,
            stream=True  # Stream to enforce size limit
        )

        # Read response with size limit
        content_chunks = []
        total_size = 0
        for chunk in response.iter_content(chunk_size=8192):
            total_size += len(chunk)
            if total_size > max_size:
                return f"http_request failed: response exceeds max_response_size ({max_size} bytes)"
            content_chunks.append(chunk)

        content = b"".join(content_chunks).decode("utf-8", errors="replace")

        # Format response
        result_lines = [
            f"http_request {method} {url}",
            f"Status: {response.status_code} {response.reason}",
            f"Content-Length: {len(content)} bytes",
            "",
            "Headers:",
        ]

        for key, value in response.headers.items():
            result_lines.append(f"  {key}: {value}")

        result_lines.append("")
        result_lines.append("Body:")
        result_lines.append(content[:10000])  # Truncate display to 10KB
        if len(content) > 10000:
            result_lines.append(f"... (truncated, {len(content) - 10000} more bytes)")

        return "\n".join(result_lines)

    except requests.exceptions.Timeout:
        return f"http_request failed: request timed out after {timeout}s"
    except requests.exceptions.RequestException as exc:
        return f"http_request failed: {exc}"
    except Exception as exc:
        return f"http_request failed: {exc}"
```

**Note:** Add `requests` to `pyproject.toml` dependencies.

---

#### 3. git_add

**Purpose:** Stage files for commit

**JSON Schema:**
```python
{
    "type": "function",
    "function": {
        "name": "git_add",
        "description": "Stage files for commit in the current git repository.",
        "parameters": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to stage (relative to CWD). If empty and all=true, stages all changes."
                },
                "all": {
                    "type": "boolean",
                    "description": "If true, stage all modified/deleted files (git add -A)",
                    "default": False
                }
            }
        }
    }
}
```

**Handler Implementation:**
```python
def _handle_git_add(raw_args: str) -> str:
    """Stage files for git commit."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for git_add: {exc}"

    paths = args.get("paths") or []
    add_all = bool(args.get("all", False))

    if not paths and not add_all:
        return "git_add failed: provide 'paths' or set 'all=true'"

    base = Path.cwd()

    if add_all:
        cmd = "git add -A"
    else:
        # Validate paths are within CWD
        for path_str in paths:
            try:
                path = (base / path_str).resolve()
                path.relative_to(base)
            except ValueError:
                return f"git_add blocked: path outside workspace ({path_str})"

        # Build git add command
        paths_str = " ".join(f'"{p}"' for p in paths)
        cmd = f"git add {paths_str}"

    try:
        result = subprocess.run(
            ["/bin/bash", "-lc", cmd],
            capture_output=True,
            text=True,
            cwd=base,
            timeout=30
        )
    except Exception as exc:
        return f"git_add failed: {exc}"

    if result.returncode != 0:
        return f"git_add failed (exit {result.returncode}):\n{result.stderr.strip()}"

    # Show what was staged
    status_result = subprocess.run(
        ["git", "diff", "--cached", "--name-status"],
        capture_output=True,
        text=True,
        cwd=base,
        timeout=10
    )

    staged = status_result.stdout.strip() or "(no changes staged)"
    return f"git_add success:\n{staged}"
```

---

#### 4. git_commit

**Purpose:** Create a commit with a message

**JSON Schema:**
```python
{
    "type": "function",
    "function": {
        "name": "git_commit",
        "description": "Create a git commit with the staged changes.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Commit message"
                },
                "amend": {
                    "type": "boolean",
                    "description": "Amend the previous commit instead of creating new one",
                    "default": False
                }
            },
            "required": ["message"]
        }
    }
}
```

**Handler Implementation:**
```python
def _handle_git_commit(raw_args: str) -> str:
    """Create a git commit."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for git_commit: {exc}"

    message = args.get("message", "").strip()
    amend = bool(args.get("amend", False))

    if not message:
        return "git_commit failed: 'message' is required and cannot be empty."

    # Escape message for shell
    message_escaped = message.replace('"', '\\"')

    base = Path.cwd()
    amend_flag = "--amend" if amend else ""
    cmd = f'git commit {amend_flag} -m "{message_escaped}"'

    try:
        result = subprocess.run(
            ["/bin/bash", "-lc", cmd],
            capture_output=True,
            text=True,
            cwd=base,
            timeout=30
        )
    except Exception as exc:
        return f"git_commit failed: {exc}"

    out = result.stdout.strip()
    err = result.stderr.strip()

    if result.returncode != 0:
        return f"git_commit failed (exit {result.returncode}):\n{err or out}"

    return f"git_commit success:\n{out}"
```

---

#### 5. git_push

**Purpose:** Push commits to remote repository

**JSON Schema:**
```python
{
    "type": "function",
    "function": {
        "name": "git_push",
        "description": "Push commits to a remote git repository.",
        "parameters": {
            "type": "object",
            "properties": {
                "remote": {
                    "type": "string",
                    "description": "Remote name",
                    "default": "origin"
                },
                "branch": {
                    "type": "string",
                    "description": "Branch name (defaults to current branch)"
                },
                "force": {
                    "type": "boolean",
                    "description": "Force push (dangerous, use with caution)",
                    "default": False
                },
                "set_upstream": {
                    "type": "boolean",
                    "description": "Set upstream tracking (-u flag)",
                    "default": False
                }
            }
        }
    }
}
```

**Handler Implementation:**
```python
def _handle_git_push(raw_args: str) -> str:
    """Push to remote repository."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for git_push: {exc}"

    remote = args.get("remote", "origin")
    branch = args.get("branch")
    force = bool(args.get("force", False))
    set_upstream = bool(args.get("set_upstream", False))

    base = Path.cwd()

    # Get current branch if not specified
    if not branch:
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=base,
            timeout=5
        )
        branch = branch_result.stdout.strip()
        if not branch:
            return "git_push failed: could not determine current branch"

    # Safety check for force push to main/master
    if force and branch in {"main", "master"}:
        return f"git_push blocked: force push to '{branch}' is dangerous. Are you sure? If so, use git CLI directly."

    # Build command
    cmd_parts = ["git", "push"]
    if set_upstream:
        cmd_parts.append("-u")
    if force:
        cmd_parts.append("--force")
    cmd_parts.extend([remote, branch])

    cmd = " ".join(cmd_parts)

    try:
        result = subprocess.run(
            ["/bin/bash", "-lc", cmd],
            capture_output=True,
            text=True,
            cwd=base,
            timeout=120  # Longer timeout for network
        )
    except Exception as exc:
        return f"git_push failed: {exc}"

    out = result.stdout.strip()
    err = result.stderr.strip()

    if result.returncode != 0:
        return f"git_push failed (exit {result.returncode}):\n{err or out}"

    return f"git_push success to {remote}/{branch}:\n{err or out}"  # git push often outputs to stderr
```

---

### TIER 2: High-Value Tools

---

#### 6. ask_user

**Purpose:** Interactive user prompts during execution

**JSON Schema:**
```python
{
    "type": "function",
    "function": {
        "name": "ask_user",
        "description": "Prompt the user for input during execution. Useful for decisions, confirmations, or gathering information.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Question to ask the user"
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of choices (e.g., ['yes', 'no', 'skip'])"
                },
                "default": {
                    "type": "string",
                    "description": "Default answer if user just presses Enter"
                }
            },
            "required": ["question"]
        }
    }
}
```

**Handler Implementation:**
```python
def _handle_ask_user(raw_args: str) -> str:
    """Prompt user for input."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for ask_user: {exc}"

    question = args.get("question", "").strip()
    options = args.get("options") or []
    default = args.get("default", "").strip()

    if not question:
        return "ask_user failed: 'question' is required."

    # Format prompt
    prompt = question
    if options:
        options_str = "/".join(options)
        prompt = f"{question} [{options_str}]"
    if default:
        prompt = f"{prompt} (default: {default})"
    prompt += ": "

    try:
        user_input = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return "ask_user cancelled by user."

    # Use default if empty
    if not user_input and default:
        user_input = default

    # Validate against options if provided
    if options and user_input not in options:
        return f"ask_user: user entered '{user_input}' (not in options: {options})"

    return f"ask_user response: {user_input}"
```

---

#### 7. glob_files

**Purpose:** Find files matching glob patterns

**JSON Schema:**
```python
{
    "type": "function",
    "function": {
        "name": "glob_files",
        "description": "Find files matching a glob pattern (e.g., '**/*.py', 'src/**/*.js').",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match files (e.g., '*.py', '**/*.json', 'test_*.py')"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                    "default": 100
                }
            },
            "required": ["pattern"]
        }
    }
}
```

**Handler Implementation:**
```python
def _handle_glob_files(raw_args: str) -> str:
    """Find files matching glob pattern."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for glob_files: {exc}"

    pattern = args.get("pattern", "").strip()
    max_results = int(args.get("max_results", 100))

    if not pattern:
        return "glob_files failed: 'pattern' is required."

    base = Path.cwd().resolve()

    try:
        matches = list(base.glob(pattern))
    except Exception as exc:
        return f"glob_files failed: {exc}"

    # Filter to files only, sort, limit
    files = sorted([m for m in matches if m.is_file()], key=lambda p: str(p))[:max_results]

    if not files:
        return f"glob_files: no matches for pattern '{pattern}'"

    # Format results as relative paths
    lines = []
    for f in files:
        try:
            rel = f.relative_to(base)
            lines.append(str(rel))
        except ValueError:
            lines.append(str(f))  # Shouldn't happen but handle anyway

    count_str = f" (showing {len(files)} of {len(matches)})" if len(matches) > max_results else ""
    return f"glob_files found {len(files)} file(s){count_str}:\n" + "\n".join(lines)
```

---

#### 8. read_env

**Purpose:** Read environment variables

**JSON Schema:**
```python
{
    "type": "function",
    "function": {
        "name": "read_env",
        "description": "Read environment variables. Filters out sensitive variables by default.",
        "parameters": {
            "type": "object",
            "properties": {
                "var_name": {
                    "type": "string",
                    "description": "Specific variable to read (if not provided, lists all non-sensitive variables)"
                },
                "include_sensitive": {
                    "type": "boolean",
                    "description": "Include potentially sensitive variables (keys, tokens, passwords). Use with caution.",
                    "default": False
                }
            }
        }
    }
}
```

**Handler Implementation:**
```python
def _handle_read_env(raw_args: str) -> str:
    """Read environment variables with security filtering."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for read_env: {exc}"

    var_name = args.get("var_name")
    include_sensitive = bool(args.get("include_sensitive", False))

    # Sensitive patterns to filter
    sensitive_patterns = [
        "key", "token", "secret", "password", "passwd", "pwd",
        "api", "auth", "credential", "private", "session"
    ]

    def is_sensitive(name: str) -> bool:
        """Check if variable name suggests sensitive data."""
        name_lower = name.lower()
        return any(pattern in name_lower for pattern in sensitive_patterns)

    # Read specific variable
    if var_name:
        value = os.environ.get(var_name)
        if value is None:
            return f"read_env: environment variable '{var_name}' is not set"

        # Warn if reading sensitive variable
        if is_sensitive(var_name) and not include_sensitive:
            return f"read_env blocked: '{var_name}' appears to be sensitive. Set include_sensitive=true to read anyway."

        # Mask part of sensitive values
        if is_sensitive(var_name):
            if len(value) > 8:
                masked = value[:4] + "..." + value[-4:]
                return f"read_env: {var_name}={masked} (masked)"
            else:
                return f"read_env: {var_name}=*** (masked)"

        return f"read_env: {var_name}={value}"

    # List all variables
    all_vars = dict(os.environ)

    if include_sensitive:
        vars_to_show = all_vars
    else:
        vars_to_show = {k: v for k, v in all_vars.items() if not is_sensitive(k)}

    if not vars_to_show:
        return "read_env: no non-sensitive environment variables found"

    lines = [f"read_env: found {len(vars_to_show)} variable(s):"]
    for key in sorted(vars_to_show.keys()):
        value = vars_to_show[key]
        # Truncate long values
        if len(value) > 100:
            value = value[:97] + "..."
        lines.append(f"  {key}={value}")

    filtered_count = len(all_vars) - len(vars_to_show)
    if filtered_count > 0:
        lines.append(f"\n({filtered_count} sensitive variable(s) filtered; set include_sensitive=true to see all)")

    return "\n".join(lines)
```

---

#### 9. system_info

**Purpose:** Get system information (OS, CPU, memory, disk)

**JSON Schema:**
```python
{
    "type": "function",
    "function": {
        "name": "system_info",
        "description": "Get system information including OS, CPU, memory, and disk usage.",
        "parameters": {
            "type": "object",
            "properties": {
                "detail_level": {
                    "type": "string",
                    "enum": ["basic", "full"],
                    "description": "Level of detail to return",
                    "default": "basic"
                }
            }
        }
    }
}
```

**Handler Implementation:**
```python
def _handle_system_info(raw_args: str) -> str:
    """Get system information."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for system_info: {exc}"

    detail_level = args.get("detail_level", "basic")

    import platform

    lines = ["system_info:"]

    # OS information
    lines.append(f"  OS: {platform.system()} {platform.release()}")
    lines.append(f"  Platform: {platform.platform()}")
    lines.append(f"  Machine: {platform.machine()}")
    lines.append(f"  Processor: {platform.processor() or 'unknown'}")
    lines.append(f"  Python: {platform.python_version()}")

    # Disk usage
    try:
        import shutil
        total, used, free = shutil.disk_usage(Path.cwd())
        total_gb = total / (1024**3)
        used_gb = used / (1024**3)
        free_gb = free / (1024**3)
        percent_used = (used / total) * 100
        lines.append(f"  Disk: {used_gb:.1f}GB used / {total_gb:.1f}GB total ({percent_used:.1f}% used, {free_gb:.1f}GB free)")
    except Exception:
        lines.append("  Disk: unable to get disk usage")

    if detail_level == "full":
        # CPU count
        try:
            import os
            cpu_count = os.cpu_count()
            lines.append(f"  CPU cores: {cpu_count}")
        except Exception:
            pass

        # Memory (requires psutil - optional)
        try:
            import psutil
            mem = psutil.virtual_memory()
            mem_total_gb = mem.total / (1024**3)
            mem_used_gb = mem.used / (1024**3)
            mem_percent = mem.percent
            lines.append(f"  Memory: {mem_used_gb:.1f}GB / {mem_total_gb:.1f}GB ({mem_percent:.1f}% used)")
        except ImportError:
            lines.append("  Memory: psutil not installed (pip install psutil for memory info)")
        except Exception:
            lines.append("  Memory: unable to get memory info")

        # Current directory
        lines.append(f"  CWD: {Path.cwd()}")

        # Hostname
        lines.append(f"  Hostname: {platform.node()}")

    return "\n".join(lines)
```

**Note:** Add `psutil` as optional dependency for full system info.

---

#### 10. which_command

**Purpose:** Find executable location (like `which` on Unix, `where` on Windows)

**JSON Schema:**
```python
{
    "type": "function",
    "function": {
        "name": "which_command",
        "description": "Find the location of an executable command in PATH.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Command name to locate (e.g., 'python', 'git', 'node')"
                }
            },
            "required": ["command"]
        }
    }
}
```

**Handler Implementation:**
```python
def _handle_which_command(raw_args: str) -> str:
    """Find command location in PATH."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for which_command: {exc}"

    command = args.get("command", "").strip()

    if not command:
        return "which_command failed: 'command' is required."

    location = shutil.which(command)

    if location:
        return f"which_command: {command} -> {location}"
    else:
        return f"which_command: '{command}' not found in PATH"
```

---

### TIER 3: Advanced Tools

---

#### 11. apply_patch

**Purpose:** Apply git-style unified diffs

**JSON Schema:**
```python
{
    "type": "function",
    "function": {
        "name": "apply_patch",
        "description": "Apply a git-style unified diff patch to files.",
        "parameters": {
            "type": "object",
            "properties": {
                "patch_content": {
                    "type": "string",
                    "description": "Unified diff content (output from git diff or similar)"
                },
                "reverse": {
                    "type": "boolean",
                    "description": "Apply patch in reverse (undo changes)",
                    "default": False
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Test patch without applying (shows what would change)",
                    "default": False
                }
            },
            "required": ["patch_content"]
        }
    }
}
```

**Handler Implementation:**
```python
def _handle_apply_patch(raw_args: str) -> str:
    """Apply unified diff patch."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for apply_patch: {exc}"

    patch_content = args.get("patch_content", "").strip()
    reverse = bool(args.get("reverse", False))
    dry_run = bool(args.get("dry_run", False))

    if not patch_content:
        return "apply_patch failed: 'patch_content' is required."

    base = Path.cwd()

    # Write patch to temporary file
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False) as f:
            f.write(patch_content)
            patch_file = f.name
    except Exception as exc:
        return f"apply_patch failed to create temp file: {exc}"

    try:
        # Build patch command
        cmd = ["patch", "-p1"]
        if reverse:
            cmd.append("-R")
        if dry_run:
            cmd.append("--dry-run")
        cmd.extend(["-i", patch_file])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=base,
            timeout=30
        )

        out = result.stdout.strip()
        err = result.stderr.strip()

        if result.returncode != 0:
            return f"apply_patch failed (exit {result.returncode}):\n{err or out}"

        prefix = "apply_patch (dry-run)" if dry_run else "apply_patch success"
        return f"{prefix}:\n{out or err}"

    except FileNotFoundError:
        return "apply_patch failed: 'patch' command not found. Install patch utility."
    except Exception as exc:
        return f"apply_patch failed: {exc}"
    finally:
        # Clean up temp file
        try:
            Path(patch_file).unlink()
        except Exception:
            pass
```

---

#### 12. find_symbol

**Purpose:** Find function/class/variable definitions in code

**JSON Schema:**
```python
{
    "type": "function",
    "function": {
        "name": "find_symbol",
        "description": "Find function, class, or variable definitions in code files. Uses ripgrep with common language patterns.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol_name": {
                    "type": "string",
                    "description": "Name of the symbol to find (function, class, variable)"
                },
                "symbol_type": {
                    "type": "string",
                    "enum": ["function", "class", "variable", "any"],
                    "description": "Type of symbol to search for",
                    "default": "any"
                },
                "language": {
                    "type": "string",
                    "enum": ["python", "javascript", "typescript", "go", "rust", "java", "any"],
                    "description": "Programming language (narrows search patterns)",
                    "default": "any"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return",
                    "default": 20
                }
            },
            "required": ["symbol_name"]
        }
    }
}
```

**Handler Implementation:**
```python
def _handle_find_symbol(raw_args: str) -> str:
    """Find symbol definitions in code."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for find_symbol: {exc}"

    symbol_name = args.get("symbol_name", "").strip()
    symbol_type = args.get("symbol_type", "any")
    language = args.get("language", "any")
    max_results = int(args.get("max_results", 20))

    if not symbol_name:
        return "find_symbol failed: 'symbol_name' is required."

    base = Path.cwd()

    # Build language-specific patterns
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
        return f"find_symbol: no search patterns for language='{language}' and type='{symbol_type}'"

    # Combine patterns with OR
    pattern_str = "|".join(f"({p})" for p in patterns)

    # Run ripgrep
    cmd = [
        "rg",
        "--no-heading",
        "--line-number",
        "--color", "never",
        "-e", pattern_str,
        "--max-count", str(max_results),
        "."
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=base,
            capture_output=True,
            text=True,
            timeout=15
        )
    except FileNotFoundError:
        return "find_symbol failed: ripgrep (rg) not available."
    except Exception as exc:
        return f"find_symbol failed: {exc}"

    output = result.stdout.strip()

    if not output:
        return f"find_symbol: no matches for symbol '{symbol_name}' (type={symbol_type}, language={language})"

    lines = output.splitlines()[:max_results]
    return f"find_symbol found {len(lines)} match(es) for '{symbol_name}':\n" + "\n".join(lines)
```

---

#### 13. run_background

**Purpose:** Run command in background, return process ID

**JSON Schema:**
```python
{
    "type": "function",
    "function": {
        "name": "run_background",
        "description": "Start a command in the background and return immediately with process ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Command to run in background"
                },
                "log_file": {
                    "type": "string",
                    "description": "Optional file path to redirect stdout/stderr"
                }
            },
            "required": ["command"]
        }
    }
}
```

**Handler Implementation:**
```python
def _handle_run_background(raw_args: str) -> str:
    """Run command in background."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for run_background: {exc}"

    command = args.get("command", "").strip()
    log_file = args.get("log_file")

    if not command:
        return "run_background failed: 'command' is required."

    # Safety check
    lowered = command.lower()
    if lowered.startswith("sudo ") or "apt-get" in lowered:
        return "run_background blocked: disallowed sudo/apt-get."

    base = Path.cwd()

    # Prepare log file
    stdout_dest = subprocess.PIPE
    stderr_dest = subprocess.PIPE

    if log_file:
        _, log_path, err = _resolve_path(log_file)
        if err:
            return f"run_background blocked: {err}"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = open(log_path, 'w')
            stdout_dest = log_handle
            stderr_dest = subprocess.STDOUT
        except Exception as exc:
            return f"run_background failed to open log file: {exc}"

    try:
        # Start process in background
        proc = subprocess.Popen(
            ["/bin/bash", "-lc", command],
            stdout=stdout_dest,
            stderr=stderr_dest,
            cwd=base,
            start_new_session=True  # Detach from parent
        )

        pid = proc.pid
        log_info = f" (logging to {log_file})" if log_file else ""
        return f"run_background: started process with PID {pid}{log_info}\nCommand: {command}"

    except Exception as exc:
        return f"run_background failed: {exc}"
```

**Note:** This creates background processes. Consider adding companion tools `check_process` and `kill_process`.

---

#### 14. db_query

**Purpose:** Execute SQL queries (read-only by default)

**JSON Schema:**
```python
{
    "type": "function",
    "function": {
        "name": "db_query",
        "description": "Execute a SQL query against a database. Read-only by default (SELECT, SHOW, DESCRIBE).",
        "parameters": {
            "type": "object",
            "properties": {
                "connection_string": {
                    "type": "string",
                    "description": "Database connection string (e.g., 'sqlite:///db.sqlite3', 'postgresql://user:pass@host/db')"
                },
                "query": {
                    "type": "string",
                    "description": "SQL query to execute"
                },
                "allow_write": {
                    "type": "boolean",
                    "description": "Allow write operations (INSERT, UPDATE, DELETE, CREATE, DROP). Use with caution.",
                    "default": False
                },
                "max_rows": {
                    "type": "integer",
                    "description": "Maximum rows to return",
                    "default": 100
                }
            },
            "required": ["connection_string", "query"]
        }
    }
}
```

**Handler Implementation:**
```python
def _handle_db_query(raw_args: str) -> str:
    """Execute database query."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for db_query: {exc}"

    connection_string = args.get("connection_string", "").strip()
    query = args.get("query", "").strip()
    allow_write = bool(args.get("allow_write", False))
    max_rows = int(args.get("max_rows", 100))

    if not connection_string or not query:
        return "db_query failed: 'connection_string' and 'query' are required."

    # Safety: check for write operations
    query_upper = query.upper().strip()
    write_keywords = {"INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE"}
    is_write_query = any(query_upper.startswith(kw) for kw in write_keywords)

    if is_write_query and not allow_write:
        return "db_query blocked: query appears to be a write operation. Set allow_write=true to proceed."

    try:
        import sqlalchemy
        from sqlalchemy import create_engine, text
    except ImportError:
        return "db_query failed: sqlalchemy not installed. Run: pip install sqlalchemy"

    try:
        # Create engine with timeout
        engine = create_engine(
            connection_string,
            connect_args={'timeout': 30} if 'sqlite' in connection_string else {},
            pool_pre_ping=True
        )

        with engine.connect() as conn:
            result = conn.execute(text(query))

            # For SELECT queries, fetch results
            if query_upper.startswith("SELECT") or query_upper.startswith("SHOW") or query_upper.startswith("DESCRIBE"):
                rows = result.fetchmany(max_rows)
                if not rows:
                    return "db_query: query returned 0 rows"

                # Format as table
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
                # For write queries
                conn.commit()
                affected = result.rowcount
                return f"db_query success: {affected} row(s) affected"

    except Exception as exc:
        return f"db_query failed: {exc}"
```

**Note:** Add `sqlalchemy` to dependencies. Consider adding support for specific drivers (psycopg2, pymysql, etc.).

---

#### 15. generate_tests

**Purpose:** Generate test cases for a function (LLM-assisted)

**JSON Schema:**
```python
{
    "type": "function",
    "function": {
        "name": "generate_tests",
        "description": "Generate test cases for a function using the LLM. Creates a test file with pytest-style tests.",
        "parameters": {
            "type": "object",
            "properties": {
                "function_name": {
                    "type": "string",
                    "description": "Name of the function to test"
                },
                "file_path": {
                    "type": "string",
                    "description": "Path to file containing the function"
                },
                "test_file_path": {
                    "type": "string",
                    "description": "Path where test file should be created (defaults to test_<original_file>)"
                },
                "framework": {
                    "type": "string",
                    "enum": ["pytest", "unittest"],
                    "description": "Test framework to use",
                    "default": "pytest"
                }
            },
            "required": ["function_name", "file_path"]
        }
    }
}
```

**Handler Implementation:**
```python
def _handle_generate_tests(raw_args: str, llm_client, settings) -> str:
    """Generate test cases using LLM."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return f"Invalid arguments for generate_tests: {exc}"

    function_name = args.get("function_name", "").strip()
    file_path = args.get("file_path", "").strip()
    test_file_path = args.get("test_file_path")
    framework = args.get("framework", "pytest")

    if not function_name or not file_path:
        return "generate_tests failed: 'function_name' and 'file_path' are required."

    # Read source file
    base, source_path, err = _resolve_path(file_path)
    if err:
        return f"generate_tests blocked: {err}"

    if not source_path.exists():
        return f"generate_tests failed: file not found ({file_path})"

    try:
        source_code = source_path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"generate_tests failed to read file: {exc}"

    # Determine test file path
    if not test_file_path:
        test_file_path = f"test_{source_path.name}"

    _, test_path, err2 = _resolve_path(test_file_path)
    if err2:
        return f"generate_tests blocked: {err2}"

    # Generate tests using LLM
    prompt = f"""Generate {framework} test cases for the function `{function_name}` from this code:

```
{source_code[:5000]}
```

Requirements:
- Create comprehensive tests covering normal cases, edge cases, and error cases
- Use {framework} framework
- Include docstrings
- Test file should be self-contained and runnable
- Return ONLY the test code, no explanations

Generate the complete test file:"""

    try:
        response = llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            max_tokens=2000
        )
        test_code = response.choices[0].message.content.strip()

        # Clean up markdown code blocks if present
        if test_code.startswith("```"):
            lines = test_code.split("\n")
            # Remove first and last lines (``` markers)
            test_code = "\n".join(lines[1:-1])

        # Write test file
        test_path.write_text(test_code, encoding="utf-8")

        return f"generate_tests success: created {test_path.relative_to(base)}\n\nGenerated {len(test_code.splitlines())} lines of test code."

    except Exception as exc:
        return f"generate_tests failed: {exc}"
```

**Note:** This handler needs access to `llm_client`. Update the dispatcher to pass it:
```python
elif name == "generate_tests":
    result = _handle_generate_tests(tool_call.function.arguments, client, settings)
```

---

## Integration Steps

### 1. Update chat.py

For each tool above:

1. **Add JSON schema** to the `TOOLS` list (starting at line 28)
2. **Add handler function** after existing handlers (around line 1740+)
3. **Add dispatcher entry** in `handle_chat_turn()` function (around line 715)

Example dispatcher entry:
```python
elif name == "edit_file":
    result = _handle_edit_file(tool_call.function.arguments)
elif name == "http_request":
    result = _handle_http_request(tool_call.function.arguments)
# ... etc
```

### 2. Update Dependencies

Add to `pyproject.toml`:
```toml
dependencies = [
    "openai>=2.8.0",
    "faiss-cpu>=1.13.0",
    "requests>=2.31.0",      # For http_request
    "sqlalchemy>=2.0.0",     # For db_query (optional)
    "psutil>=5.9.0",         # For system_info (optional)
]
```

### 3. Update DEFAULT_SYSTEM Prompt

Update the system prompt (line 21-26) to mention new tools:
```python
DEFAULT_SYSTEM = (
    "You are a concise CLI assistant running in a terminal. "
    "You can call tools to: edit files precisely (edit_file), make HTTP requests (http_request), "
    "manage git (git_add/commit/push), ask user questions (ask_user), find files (glob_files), "
    "read environment variables (read_env), get system info (system_info), find code symbols (find_symbol), "
    "and much more. "
    "All existing file ops, shell/SSH, search, docker, and git tools are also available. "
    "Ask for missing details only if necessary, and prefer performing the action via the tool rather than just describing it."
)
```

### 4. Test Each Tool

Create a test script:
```bash
cd claudeWannaBe
source venv/bin/activate

# Test edit_file
jay-agent chat
> create a file test.py with "hello = 'world'"
> edit the file to change 'world' to 'universe'

# Test http_request
> make an http request to httpbin.org/get

# Test git tools
> show git status
> stage all files with git_add
> commit with message "test commit"

# Test glob_files
> find all python files

# Test ask_user
> ask me which database I prefer

# Test read_env
> show PATH environment variable

# Test system_info
> show system information

# Test which_command
> find where python3 is located
```

### 5. Update Documentation

Update `/Users/jaysettle/Documents/CursAI/3 LLM CLI/LLMDocumentation.md`:

Add to section **3) Commands & Tools**:
```markdown
- Advanced editing: `edit_file` (string replacement)
- HTTP/API: `http_request` (GET/POST/PUT/DELETE with headers/body)
- Enhanced Git: `git_add`, `git_commit`, `git_push`
- Interactive: `ask_user` (prompt user for input)
- File Discovery: `glob_files` (pattern matching)
- Environment: `read_env` (read env vars with security filtering)
- System: `system_info` (OS/CPU/memory/disk), `which_command` (find executables)
- Advanced: `apply_patch`, `find_symbol`, `run_background`, `db_query`, `generate_tests`
```

---

## Safety & Error Handling Checklist

For each tool implementation, verify:

- [ ] Input validation (required parameters)
- [ ] Path safety (use `_resolve_path()` for file operations)
- [ ] Timeout enforcement (subprocess calls)
- [ ] Size limits (HTTP responses, file reads)
- [ ] Clear error messages
- [ ] Success confirmation messages
- [ ] JSON parsing error handling
- [ ] Exception catching
- [ ] Security filtering (env vars, SQL injection)
- [ ] Confirmation for destructive operations

---

## Priority Implementation Order

**Recommended order:**

1. **edit_file** - Most impactful, enables efficient code editing
2. **http_request** - Essential for web development
3. **git_add, git_commit, git_push** - Complete git workflow
4. **ask_user** - Enables interactive workflows
5. **glob_files** - File discovery
6. **read_env** - Common debugging need
7. **system_info, which_command** - System diagnostics
8. **find_symbol** - Code navigation
9. **apply_patch, run_background** - Advanced features
10. **db_query, generate_tests** - Specialized use cases

---

## Expected Outcome

After implementing these 15 tools, jay-agent will have:

- **49 total tools** (34 existing + 15 new)
- **Precise file editing** without full rewrites
- **HTTP/API testing** capabilities
- **Complete git workflow** (read + write)
- **Interactive user prompts**
- **Advanced code navigation**
- **System introspection**
- **Database querying**
- **Background process management**
- **AI-assisted test generation**

This will make jay-agent **competitive with Claude Code, GitHub Copilot, and Gemini Code Assist** while maintaining its unique strengths (SSH, RAG, sandboxed Python, semantic renaming).

---

## Notes

- All implementations follow existing patterns in `chat.py`
- Safety is paramount (CWD constraints, timeouts, confirmations)
- Error messages are detailed and actionable
- Return values are formatted for terminal display
- Tools are composable (can be chained by the LLM)
- Each tool is stateless and idempotent where possible

Start with Tier 1 tools and test thoroughly before moving to Tier 2 and 3.
