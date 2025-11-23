# LLM Agent CLI – Detailed Guide

## 1) Overview
- Terminal-first agent CLI (`jay-agent`) that uses an OpenAI-compatible chat API (default Ollama at `http://192.168.3.142:11434/v1`).
- Capabilities: interactive chat with tool-calling (rich file ops, local shell/PowerShell/Python, SSH), directory listing/tree, text search (ripgrep), vector RAG indexing/search, optional chat transcripts/resume, one-shot ask, exec command, basic package installs, ping, web search (SerpAPI with optional fetch/summaries).
- Installed as an editable package exposing console entry `jay-agent`.

## 2) Architecture & Flow
- **Entry/CLI wiring**: `agent/cli/main.py` sets up argparse and registers subcommands from `agent/cli/commands/`.
- **Commands**: `chat`, `ask` (stub), `index`, `search`, `exec`, `run` (stub), `ssh`.
- **Chat pipeline** (`agent/cli/commands/chat.py`):
  1. Build system prompt (+ optional resume transcript).
  2. Send a non-stream request with tool schema to detect tool calls.
  3. Execute requested tools locally (sandboxed to CWD, timeouts).
  4. Send follow-up non-stream for the final message, or stream if no tool was used.
  5. Optionally log transcript entries to JSONL.
- **LLM client** (`agent/core/llm_client.py`): wraps OpenAI-compatible `chat`/`embed` using settings (base_url/api_key/model).
- **Config** (`agent/core/config.py`, `agent/config/settings.toml`): defaults + env overrides (`JAY_BASE_URL`, `JAY_MODEL`, `JAY_API_KEY`, `JAY_DATA_DIR`, `JAY_LOG_LEVEL`, etc.).
- **Logging** (`agent/core/logging_utils.py`): console + `data/logs/agent.log` relative to current working directory.
- **RAG** (`agent/rag`): chunk → embed → vector index (faiss cosine) + metadata. `index_cmd.py` builds the index; `search_cmd.py` and chat `search_index` query it.
- **Safety boundaries**: all local file/command tools are constrained to the current working directory; deletes require confirm; shell blocks sudo/apt-get; SSH only runs when requested; installs restricted to allowlisted Homebrew packages; timeouts on shell/PowerShell/SSH/Python.

## 3) Commands & Tools
- `jay-agent chat`
  - File ops: `create_file`, `write_file` (overwrite/append), `read_file` (head/tail/range with max chars), `copy_path`, `rename_path`, `delete_path` (confirm + optional recursive), `rename_all` (pattern), `rename_semantic` (content-based), `list_dir`, `list_tree`.
  - Search: `search_text` (ripgrep), `search_index` (vector RAG index), `web_search` (SerpAPI; requires `JAY_SERPAPI_KEY`, supports site filter, result count, optional fetch/summarize top links with max_bytes/max_fetch_time guards).
  - Exec local: `run_shell(command)` (blocks sudo/apt-get), `run_powershell(command)` (if pwsh/powershell present), `run_python(path, args=[])`, `python_exec(code, timeout?, persist?, globals?, files?, requirements?, session_id?, max_memory_mb?)`, `run_tests(cmd?, timeout?)`, `run_lint(cmd?, timeout?)`, `run_type_check(cmd?, timeout?)`, `pip_install(name, timeout?)`, `npm_install(name, timeout?)`, docker helpers (`docker_ps`, `docker_images`, `docker_logs(container, tail?)`, `docker_stop(container)`, `docker_compose(args?, timeout?)`), git helpers (`git_status`, `git_diff(path?)`, `git_log(limit?, oneline?)`).
  - Exec remote: `run_ssh(target, command, port?, identity?, user?, password?)` (password requires `sshpass`; prefers keys; warns if sshpass missing).
  - Install: `install_package(name)` (allowlisted Homebrew installs: sshpass, ripgrep/rg, powershell/pwsh; errors if brew missing); `pip_install`, `npm_install` for package managers.
  - Network: `ping_host(host, count?, timeout?)`.
  - Code search: `code_search(query, glob?, context?, max_results?)` (ripgrep with context).
  - Flags: `--system "..."`, `--resume <transcript.jsonl>`, `--transcript-dir <dir>` (default `data/sessions`), `--no-transcript`.
- `jay-agent ask "question"`: stub one-shot.
- `jay-agent index [path]`: chunk + embed allowed files under `path` (default `.`), save vector index + metadata under `./data/index.*` (npy + meta.json).
- `jay-agent search "query"`: embed query and search the saved vector index; prints scores/snippets.
- Web search: via chat `web_search` tool (SerpAPI; `JAY_SERPAPI_KEY` required).
- `jay-agent exec "cmd"`: run a local shell command via bash (subject to sudo/apt-get block).
- `jay-agent ssh user@host "cmd"`: run an SSH command (opts: `--port`, `--identity`, `--user`, `--password`).
- `jay-agent run ...`: stub placeholder.

## 4) Data, Paths, and Files
- Logs: `data/logs/agent.log` relative to the directory where you launch the CLI.
- Transcripts: `data/sessions/session-*.jsonl` by default; disable with `--no-transcript`; resume with `--resume <file>`.
- RAG index: `data/index.npy` + `data/index.meta.json` relative to the launch directory.
- All local file/system actions are restricted to the current working directory; SSH runs remotely.

## 5) Setup
1) Activate venv: `source /Users/jaysettle/Documents/CursAI/2/myenv/bin/activate`
2) Install editable: `pip install -e .`
3) Configure endpoint: `config/settings.toml` or env vars (`JAY_BASE_URL`, `JAY_MODEL`, `JAY_API_KEY`, `JAY_DATA_DIR`, `JAY_LOG_LEVEL`, etc.).
4) Optional: install ripgrep (`brew install ripgrep`) and sshpass (`install_package sshpass` or brew) for search/password SSH.

## 6) Typical Workflows
- **Chat in a workspace**: `jay-agent chat` → ask “create a file notes/todo.txt with 'buy milk'”, “search for TODO in *.py”, “run ssh user@host 'ls'”, “ping 192.168.3.192”.
- **Index and search (RAG)**: `jay-agent index .` then `jay-agent search "logging"` or in chat “search the index for logging”.
- **Transcripts**: `jay-agent chat --transcript-dir data/sessions`; resume with `--resume data/sessions/session-YYYYMMDD-HHMMSS.jsonl`.
- **Installs**: “install package sshpass” (allowlist; requires Homebrew).

## 7) Safety Notes
- Paths limited to current working directory for file ops and local exec.
- Deletes require `confirm=true`; no trash/undo.
- `run_shell` blocks sudo/apt-get; use `install_package` or manual install.
- Password SSH requires sshpass; keys recommended.
- Timeouts on shell/PowerShell/SSH/Python; network/web browsing not exposed.

## 8) Limitations / Future Work
- No web search/browse tool; all actions are local/SSH.
- Vector search is faiss cosine only (no rerank/metadata filtering).
- No undo/trash for destructive ops; no journal/rollback.
- `ask`/`run` are stubs; no memory beyond transcripts.
- No allow/deny lists or secret redaction for shell/SSH; only timeouts.
- No automated tests/CI; minimal Windows handling (pwsh optional).
