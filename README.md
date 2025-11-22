# Jay Agent CLI

Terminal-first agent CLI that talks to an OpenAI-compatible endpoint (default Ollama at `http://192.168.3.142:11434/v1`). Installed as an editable package with the `jay-agent` console command.

## Status
- Interactive chat wired to call tools:
  - File ops: `create_file`, `write_file` (overwrite/append), `read_file` (head/tail/range), `copy_path`, `rename_path`, `delete_path` (confirm + optional recursive), `rename_all` (pattern), `rename_semantic` (content-based), `list_dir`, `list_tree`.
  - Search: `search_text` (ripgrep), `search_index` (RAG index), `web_search` (SerpAPI; needs `JAY_SERPAPI_KEY`, supports site filter, fetch/summarize top links).
  - Exec: `run_shell` (bash), `run_powershell` (local PowerShell), `run_python` (CWD), `run_ssh` (remote; key or password with sshpass).
  - Install: `install_package` (allowlist via Homebrew: sshpass, ripgrep, powershell). run_shell blocks sudo/apt-get; use install_package or run manually.
  - Network: `ping_host` (reachability checks).
- RAG indexing/search: `jay-agent index [path]` builds a vector index (embeddings + metadata) at `./data/index.*`; `jay-agent search "query"` searches it with similarity.
- Logging goes to `data/logs/agent.log` relative to the working directory.
- Chat transcripts (jsonl) can be saved to `data/sessions/` (configurable) and resumed.

## Setup
1. Activate the venv: `source /Users/jaysettle/Documents/CursAI/2/myenv/bin/activate`
2. Install editable: `pip install -e .` (already done in this workspace).
3. Configure endpoint via `config/settings.toml` or env vars (`JAY_BASE_URL`, `JAY_MODEL`, `JAY_API_KEY`, etc.).

## Usage
- Chat: `jay-agent chat`
  - Ask: “create a file notes/todo.txt with 'buy milk'”, “list the files in this folder”, “run script.py”, “search for TODO in *.py”, “run ssh user@host 'ls'”, “run shell 'ls -la'”, “run powershell 'Get-ChildItem'”, “run ssh with password user@host 'cmd'”.
  - Flags: `--system "Your instructions"`, `--resume path/to/transcript.jsonl`, `--transcript-dir DIR`, `--no-transcript`
- One-shot ask (stub): `jay-agent ask "question"`
- Index/search: `jay-agent index .`; `jay-agent search "query"` (vector similarity via faiss)
- Web search: “web search 'query'” (requires `JAY_SERPAPI_KEY` for SerpAPI)
- SSH: `jay-agent ssh user@host "cmd"` (opts: `--port`, `--identity`)
- Other commands exist but are not yet fully implemented.

## Project Structure
- `agent/cli/main.py` – CLI entrypoint.
- `agent/cli/commands/` – subcommands; `chat.py` implements chat + tools.
- `agent/core/` – config, logging, conversation, LLM client.
- `agent/config/settings.toml` – default endpoint/model settings.
- `agent/rag/` – RAG indexing/search (chunk/embed/index/search).
- `agent/tools/` – helper modules (file ops, python exec, shell/git helpers).
- `LLMDocumentation.md` – extended documentation of features and behavior.

## Notes
- All file/system actions are constrained to the current working directory for safety.
- Requires an OpenAI-compatible server reachable at `base_url`.
