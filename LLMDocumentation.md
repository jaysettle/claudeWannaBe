# LLM Agent CLI – Documentation

## Overview
- Repo provides a terminal-first agent CLI (`jay-agent`) configured for an OpenAI-compatible server (default Ollama at `http://192.168.3.142:11434/v1`).
- Key capabilities: interactive chat with tool-calling (create files, list current dir, run Python scripts), one-shot ask, placeholders for search/index/exec/run/ssh.
- Installed as an editable package with a console script so `jay-agent` is on PATH when the virtualenv is active.

## Setup
1) Activate your venv: `source /Users/jaysettle/Documents/CursAI/2/myenv/bin/activate`
2) Install/editable: `pip install -e .` (already done).
3) Model endpoint config: `config/settings.toml` or env vars (`JAY_BASE_URL`, `JAY_MODEL`, `JAY_API_KEY`, etc.).

## Commands
- `jay-agent chat`  
  - Interactive chat loop. Tools available to the model:
    - `create_file(path, content)`: writes text files under the current working directory; blocks paths outside CWD; returns relative + absolute path.
    - `list_dir()`: lists entries in the current working directory.
    - `run_python(path, args=[])`: executes a Python file via `python3` relative to CWD; returns exit code plus stdout/stderr; blocks paths outside CWD.
  - System prompt can be overridden: `--system "..."`.
- `jay-agent ask "question"`: one-shot (stub by default unless wired later).
- `jay-agent index/search/exec/run/ssh`: present but mostly stubs except chat tools above.

## Current Behavior
- Running `jay-agent chat` from any folder (with venv active) uses that folder as workspace for file I/O and script execution.
- Logs: `data/logs/agent.log` (relative to CWD).
- File creation and script execution are safeguarded to stay within the current directory.
- If no response text is returned by the model, the CLI now emits `(no response text)` instead of staying blank.

## Project Structure (key parts)
- `pyproject.toml` – packaging metadata and console script entry.
- `agent/cli/main.py` – entrypoint for CLI.
- `agent/cli/commands/` – subcommands; `chat.py` implements chat + tools.
- `agent/core/` – config, logging, conversation handling, LLM client wrapper.
- `agent/config/settings.toml` – default settings (base URL, model, data dir, etc.).
- `agent/rag/` – indexing/search scaffolding (not fully wired in CLI yet).
- `agent/tools/` – helper modules (not all exposed yet).

## How to Use (common examples)
- Create a file: `jay-agent chat` → “create a file notes/todo.txt with 'buy milk'”
- List files: “list the files in this folder”
- Run script: “run script.py” or “run script.py with args 1 2 3”
- One-shot ask: `jay-agent ask "What can you do?"` (currently stub).

## Notes / Limitations
- Requires the OpenAI-compatible server reachable at the configured `base_url`.
- Other subcommands (index/search/exec/run/ssh) are placeholders; extend as needed.
- All file/system actions are constrained to the current working directory for safety.
