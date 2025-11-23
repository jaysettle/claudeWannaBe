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
  - Exec local: `run_shell(command)` (blocks sudo/apt-get), `run_bash_script(script, timeout?, cwd?, env?)`, `run_powershell(command)` (if pwsh/powershell present), `run_python(path, args=[])`, `python_exec(code, timeout?, persist?, globals?, files?, requirements?, session_id?, max_memory_mb?)`, `run_tests(cmd?, timeout?)`, `run_lint(cmd?, timeout?)`, `run_type_check(cmd?, timeout?)`, `pip_install(name, timeout?)`, `npm_install(name, timeout?)`, docker helpers (`docker_ps`, `docker_images`, `docker_logs(container, tail?)`, `docker_stop(container)`, `docker_compose(args?, timeout?)`), git helpers (`git_status`, `git_diff(path?)`, `git_log(limit?, oneline?)`).
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

## 8) Server Infrastructure Setup

### Dual Ollama Instance Architecture

The jay-agent infrastructure runs on a dedicated Linux server (192.168.3.142, AMD Ryzen 5 5600X with GPU) hosting two independent Ollama instances:

**Port 11434**: OpenWebUI instance
- Existing web-based AI interface
- Public-facing on LAN
- Shared model access

**Port 11435**: jay-agent dedicated instance
- Dedicated endpoint for jay-agent CLI clients
- Isolated service for CLI workloads
- Shares same model files (saves ~50GB disk space)

### Server Configuration

**Ollama Installation**:
- Models stored at: `/home/ollama/.ollama/models`
- Available models: `gpt-oss:20b`, `deepseek-coder:6.7b`, `llama3:latest`
- Both instances automatically share model files

**Systemd Service** (`/etc/systemd/system/ollama-agent.service`):
```ini
[Unit]
Description=Ollama Service for jay-agent (port 11435)
After=network.target

[Service]
Type=simple
User=ollama
Group=ollama
ExecStart=/usr/local/bin/ollama serve
Environment="OLLAMA_HOST=0.0.0.0:11435"
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

**Service Management**:
```bash
# Start/stop the jay-agent instance
sudo systemctl start ollama-agent
sudo systemctl stop ollama-agent
sudo systemctl status ollama-agent

# Original OpenWebUI instance
sudo systemctl status ollama
```

**Firewall Configuration**:
```bash
# UFW rules for port 11435 (LAN-only access)
sudo ufw allow from 192.168.3.0/24 to any port 11435 proto tcp
sudo ufw status
```

**Dependencies Installed**:
- ripgrep (for code search)
- git (for repository operations)
- build-essential (for Python package builds)

### Network Setup

**Server**: 192.168.3.142
- Two Ollama processes listening on different ports
- LAN-accessible endpoints
- GPU acceleration enabled for both instances

**Clients**: Mac/Linux laptops on same LAN
- Connect to `http://192.168.3.142:11435/v1` for jay-agent
- No special routing or VPN required
- Standard OpenAI-compatible API calls

### Client Configuration

**Configuration File** (`agent/config/settings.toml`):
```toml
base_url = "http://192.168.3.142:11435/v1"
api_key = "ollama"
model = "gpt-oss:20b"
embed_model = "gpt-oss:20b"
workspace = "."
safety_strict = true
data_dir = "data"
log_level = "INFO"
```

**Environment Variable Overrides**:
- `JAY_BASE_URL`: Override Ollama endpoint
- `JAY_MODEL`: Override default model
- `JAY_API_KEY`: Override API key (Ollama uses "ollama" by default)
- `JAY_SERPAPI_KEY`: For web search functionality (SerpAPI account required)

### Cross-Platform Client Setup

**Mac Setup**:
```bash
git clone https://github.com/jaysettle/claudeWannaBe.git
cd claudeWannaBe
python3 -m venv venv
source venv/bin/activate
pip install -e .
jay-agent chat
```

**Linux Setup** (identical):
```bash
git clone https://github.com/jaysettle/claudeWannaBe.git
cd claudeWannaBe
python3 -m venv venv
source venv/bin/activate
pip install -e .

# Optional: Set SerpAPI key for web search (otherwise web_search tool will error)
# Get free key at https://serpapi.com (100 searches/month)
# Add to shell profile for persistence:
echo 'export JAY_SERPAPI_KEY="your-serpapi-key-here"' >> ~/.bashrc
source ~/.bashrc

# Or set for current session only:
export JAY_SERPAPI_KEY="your-serpapi-key-here"

jay-agent chat
```

**Note**: Web search functionality requires a SerpAPI key. Without `JAY_SERPAPI_KEY` set, all tools except `web_search` will work normally. To make the key permanent, add it to `~/.bashrc` (Linux) or `~/.zshrc` (Mac with zsh). Free tier provides 100 searches/month.

### Verification

**Server-side checks**:
```bash
# Check Ollama version on port 11435
curl -s http://192.168.3.142:11435/api/version

# List available models
curl -s http://192.168.3.142:11435/api/tags

# Check service status
sudo systemctl status ollama-agent
sudo systemctl status ollama  # Original instance
```

**Client-side checks**:
```bash
# Test connection
curl -s http://192.168.3.142:11435/api/version

# Verify jay-agent CLI
jay-agent --help

# Test chat
jay-agent chat
```

### Model Sharing & Performance

**Disk Usage**:
- Single model directory shared by both instances
- No duplication of 20GB+ model files
- Location: `/home/ollama/.ollama/models`

**Performance**:
- GPU acceleration available to both instances
- Port 11434: OpenWebUI workloads
- Port 11435: jay-agent CLI workloads
- Concurrent requests handled independently

**VRAM Usage** (gpt-oss:20b):
- ~12GB VRAM per loaded model instance
- AMD Ryzen 5 5600X with sufficient GPU memory

### Deployment Workflow

1. **Server deployed once**: Ollama instances run as systemd services
2. **Clients clone from GitHub**: Repository includes pre-configured settings
3. **Virtual environment per client**: Isolated Python dependencies
4. **Configuration automatic**: `settings.toml` points to port 11435
5. **No additional setup**: Works immediately after `pip install -e .`

### Security Considerations

- LAN-only access via UFW firewall rules
- No internet-facing endpoints
- API key required (even for Ollama: "ollama")
- Client-side safety constraints (CWD-only file ops, sudo blocked)
- SSH requires explicit user credentials (keys or sshpass)

### Troubleshooting

**Connection failures**:
```bash
# Verify Ollama is running
curl http://192.168.3.142:11435/api/version

# Check firewall
sudo ufw status | grep 11435

# Check service logs
sudo journalctl -u ollama-agent -f
```

**Model not found**:
```bash
# List models on server
curl -s http://192.168.3.142:11435/api/tags | jq

# Pull a model if needed (on server)
ollama pull gpt-oss:20b
```

**Client configuration issues**:
```bash
# Verify config
cat agent/config/settings.toml

# Override with environment variable
export JAY_BASE_URL="http://192.168.3.142:11435/v1"
jay-agent chat
```

## 9) Limitations / Future Work
- Web search requires SerpAPI key (env var `JAY_SERPAPI_KEY`).
- Vector search is faiss cosine only (no rerank/metadata filtering).
- No undo/trash for destructive ops; no journal/rollback.
- `ask`/`run` are stubs; no memory beyond transcripts.
- No allow/deny lists or secret redaction for shell/SSH; only timeouts.
- No automated tests/CI; minimal Windows handling (pwsh optional).
