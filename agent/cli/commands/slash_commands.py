"""
Slash command system for jay-agent interactive chat.

Usage:
    In agent/cli/commands/chat.py, import and use:


    # In run_chat(), before main loop:
    setup_command_completion()

    # In main loop, before sending to LLM:
    if user_input.startswith("/"):
        result = handle_slash_command(user_input, settings, convo, client)
        if result.get("exit"):
            break
        if result.get("system_prompt"):
            current_system_prompt = result["system_prompt"]
        continue
"""

from __future__ import annotations
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...core.conversation import Conversation
    from ...core.llm_client import LLMClient


def handle_slash_command(user_input: str, settings, convo, client) -> dict:
    """
    Handle slash commands (commands starting with /).

    Args:
        user_input: The user's input starting with /
        settings: Settings object
        convo: Conversation object
        client: LLMClient object

    Returns:
        dict with:
            - 'exit': bool - whether to exit chat
            - 'system_prompt': str | None - updated system prompt (if changed)
    """
    # Parse command and arguments
    parts = user_input[1:].split()  # Remove leading / and split
    if not parts:
        print("Empty command. Type /help for available commands.")
        return {"exit": False, "system_prompt": None}

    command = parts[0].lower()
    args = parts[1:]

    result = {"exit": False, "system_prompt": None}

    # Route to appropriate handler
    if command in {"help", "h", "?"}:
        _handle_help_command(args)

    elif command in {"model", "m"}:
        _handle_model_command(args, settings, client)

    elif command in {"config", "cfg"}:
        _handle_config_command(args, settings)

    elif command in {"tools", "t"}:
        _handle_tools_command(args)

    elif command in {"history", "hist"}:
        _handle_history_command(args, convo)

    elif command in {"clear", "cls", "reset"}:
        system_prompt = next((msg["content"] for msg in convo.history() if msg["role"] == "system"), "")
        _handle_clear_command(args, convo, system_prompt)

    elif command in {"save"}:
        _handle_save_command(args, convo, settings)

    elif command in {"load"}:
        _handle_load_command(args, convo, settings)

    elif command in {"system", "sys"}:
        current_system = next((msg["content"] for msg in convo.history() if msg["role"] == "system"), "")
        new_system = _handle_system_command(args, convo, current_system)
        if new_system != current_system:
            result["system_prompt"] = new_system

    elif command in {"transcripts", "list"}:
        _handle_transcripts_command(args, settings)

    elif command in {"exit", "quit", "q"}:
        result["exit"] = _handle_exit_command(args)

    else:
        print(f"Unknown command: /{command}")
        print("Type /help for available commands")

    return result


def _handle_help_command(args: list[str]) -> None:
    """Display help information."""
    print("\nSlash Commands:")
    print("  /help              Show this help message")
    print("  /model             List available models")
    print("  /model <name>      Switch to a specific model")
    print("  /model <number>    Switch by number from list")
    print("  /config            Show current configuration")
    print("  /tools             List all available tools")
    print("  /history [N]       Show last N messages (default 10)")
    print("  /clear             Clear conversation history")
    print("  /save [file]       Save conversation to file")
    print("  /load <file>       Load conversation from file")
    print("  /system [prompt]   View or change system prompt")
    print("  /transcripts       List saved transcripts")
    print("  /exit, /quit       Exit the chat")
    print("\nRegular Commands:")
    print("  exit, quit         Exit the chat")
    print("  (anything else)    Send message to AI")
    print("\nTip: Type '/tools' to see all available AI tools")


def _handle_model_command(args: list[str], settings, client) -> None:
    """Handle /model command."""
    logger = logging.getLogger(__name__)

    if not args:
        # List available models
        print("\nFetching available models from Ollama...")
        try:
            import requests
            base_url = settings.base_url.replace("/v1", "")  # Remove /v1 suffix
            response = requests.get(f"{base_url}/api/tags", timeout=10)

            if response.status_code != 200:
                print(f"Error: Could not fetch models (HTTP {response.status_code})")
                return

            data = response.json()
            models = data.get("models", [])

            if not models:
                print("No models found on Ollama server.")
                return

            print(f"\nAvailable models (current: {settings.model}):\n")
            for idx, model in enumerate(models, 1):
                name = model.get("name", "unknown")
                size = model.get("size", 0)
                size_gb = size / (1024**3)
                modified = model.get("modified_at", "")[:10] if model.get("modified_at") else "unknown"

                marker = "→" if name == settings.model else " "
                print(f"{marker} {idx}. {name:<30} ({size_gb:.1f}GB, modified: {modified})")

            print("\nTo switch: /model <name> or /model <number>")
            print("Example: /model llama3:latest  or  /model 2")

        except ImportError:
            print("Error: requests library not installed. Run: pip install requests")
        except Exception as exc:
            print(f"Error fetching models: {exc}")
            logger.exception("Model fetch error")

        return

    # Switch to specific model
    target = " ".join(args)  # Allow model names with spaces

    # Check if it's a number (select by index)
    if target.isdigit():
        try:
            import requests
            base_url = settings.base_url.replace("/v1", "")
            response = requests.get(f"{base_url}/api/tags", timeout=10)
            data = response.json()
            models = data.get("models", [])

            idx = int(target) - 1  # Convert to 0-indexed
            if 0 <= idx < len(models):
                target = models[idx]["name"]
            else:
                print(f"Error: Invalid model number. Choose 1-{len(models)}")
                return
        except Exception as exc:
            print(f"Error: {exc}")
            logger.exception("Model selection error")
            return

    # Update settings and client
    old_model = settings.model
    settings.model = target
    client.model = target  # Update client's model

    print(f"✓ Model switched: {old_model} → {target}")
    print(f"  Next message will use {target}")


def _handle_config_command(args: list[str], settings) -> None:
    """Display current configuration."""
    print("\nCurrent Configuration:")
    print(f"  Base URL:      {settings.base_url}")
    print(f"  Model:         {settings.model}")
    print(f"  Embed Model:   {settings.embed_model}")
    print(f"  API Key:       {'*' * min(len(settings.api_key), 8) if settings.api_key else '(not set)'}")
    print(f"  Workspace:     {settings.workspace}")
    print(f"  Data Dir:      {settings.data_dir}")
    print(f"  Log Level:     {settings.log_level}")
    print(f"  Safety Strict: {settings.safety_strict}")
    print(f"\nConfig file: agent/config/settings.toml")
    print(f"Override with: JAY_MODEL, JAY_BASE_URL, etc.")


def _handle_tools_command(args: list[str]) -> None:
    """List all available tools."""
    # Import here to avoid circular dependency
    try:
        from .chat import TOOLS
    except ImportError:
        print("Error: Could not load tools list")
        return

    # Group tools by category
    categories = {
        "File Operations": ["create_file", "read_file", "write_file", "edit_file", "copy_path",
                           "rename_path", "delete_path", "rename_all", "rename_semantic",
                           "list_dir", "list_tree", "glob_files"],
        "Search": ["search_text", "search_index", "code_search", "web_search", "find_symbol"],
        "Code Execution": ["run_python", "python_exec", "run_shell", "run_powershell", "run_ssh",
                          "run_background", "run_bash_script"],
        "Git": ["git_status", "git_diff", "git_log", "git_add", "git_commit", "git_push"],
        "Docker": ["docker_ps", "docker_images", "docker_logs", "docker_stop", "docker_compose"],
        "Testing & QA": ["run_tests", "run_lint", "run_type_check", "generate_tests"],
        "Package Management": ["pip_install", "npm_install", "install_package"],
        "HTTP/API": ["http_request", "ping_host"],
        "System": ["read_env", "system_info", "which_command"],
        "Interactive": ["ask_user"],
        "Advanced": ["apply_patch", "db_query"],
    }

    # Get all tool names
    tool_names = {tool["function"]["name"] for tool in TOOLS}

    print(f"\nAvailable Tools ({len(tool_names)} total):\n")

    for category, tools in categories.items():
        available_in_category = [t for t in tools if t in tool_names]
        if available_in_category:
            print(f"{category}:")
            for tool in available_in_category:
                # Find tool description
                tool_obj = next((t for t in TOOLS if t["function"]["name"] == tool), None)
                desc = tool_obj["function"]["description"][:60] if tool_obj else ""
                print(f"  • {tool:<25} {desc}")
            print()

    # Show uncategorized tools
    categorized = {t for tools in categories.values() for t in tools}
    uncategorized = tool_names - categorized
    if uncategorized:
        print("Other:")
        for tool in sorted(uncategorized):
            print(f"  • {tool}")
        print()

    print("Tip: Ask the AI to use these tools in natural language")
    print('Example: "create a file test.py" or "search for TODO in all files"')


def _handle_history_command(args: list[str], convo) -> None:
    """Display conversation history."""
    history = convo.history()

    if not history:
        print("\nNo conversation history yet.")
        return

    # Parse optional limit argument
    limit = 10  # Default
    if args and args[0].isdigit():
        limit = int(args[0])

    print(f"\nConversation History (last {limit} messages):\n")

    for idx, msg in enumerate(history[-limit:], 1):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        # Truncate long messages
        if len(content) > 200:
            content = content[:197] + "..."

        # Format role
        role_display = {
            "system": "SYS",
            "user": "YOU",
            "assistant": "AI ",
            "tool": "TOOL"
        }.get(role, role.upper())

        print(f"{idx}. [{role_display}] {content}")

    print(f"\nTotal messages: {len(history)}")
    print("Tip: /clear to reset conversation")


def _handle_clear_command(args: list[str], convo, system_prompt: str) -> None:
    """Clear conversation history."""
    message_count = len(convo.history())

    # Confirm if there's significant history
    if message_count > 5:
        confirm = input(f"Clear {message_count} messages? [y/N]: ").strip().lower()
        if confirm not in {"y", "yes"}:
            print("Cancelled.")
            return

    # Reset conversation but keep system prompt
    convo.clear()
    convo.add_system(system_prompt)

    print(f"✓ Cleared {message_count} messages. Starting fresh.")


def _handle_save_command(args: list[str], convo, settings) -> None:
    """Save conversation to file."""
    # Determine save path
    if args:
        save_path = Path(" ".join(args))
    else:
        # Auto-generate filename
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        save_path = settings.data_dir / "sessions" / f"manual-save-{timestamp}.jsonl"

    # Ensure directory exists
    save_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with save_path.open("w", encoding="utf-8") as f:
            for msg in convo.history():
                f.write(json.dumps(msg) + "\n")

        print(f"✓ Saved {len(convo.history())} messages to: {save_path}")
    except Exception as exc:
        print(f"Error saving: {exc}")


def _handle_load_command(args: list[str], convo, settings) -> None:
    """Load conversation from file."""
    if not args:
        print("Error: /load requires a file path")
        print("Example: /load data/sessions/session-20241122-123456.jsonl")
        return

    load_path = Path(" ".join(args))

    if not load_path.exists():
        print(f"Error: File not found: {load_path}")
        return

    try:
        loaded_count = 0
        with load_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    msg = json.loads(line)
                    role = msg.get("role")
                    content = msg.get("content", "")

                    if role == "user":
                        convo.add_user(content)
                    elif role == "assistant":
                        convo.add_assistant(content)
                    elif role == "system":
                        convo.add_system(content)

                    loaded_count += 1

        print(f"✓ Loaded {loaded_count} messages from: {load_path}")
    except Exception as exc:
        print(f"Error loading: {exc}")


def _handle_system_command(args: list[str], convo, current_system: str) -> str:
    """View or change system prompt."""
    if not args:
        # Display current system prompt
        print(f"\nCurrent system prompt:\n{current_system}\n")
        print("To change: /system <new prompt>")
        return current_system

    # Set new system prompt
    new_prompt = " ".join(args)

    print(f"\n✓ System prompt updated")
    print(f"Old: {current_system[:100]}...")
    print(f"New: {new_prompt[:100]}...")

    # Add to conversation
    convo.add_system(new_prompt)

    return new_prompt


def _handle_transcripts_command(args: list[str], settings) -> None:
    """List saved transcript files."""
    transcript_dir = settings.data_dir / "sessions"

    if not transcript_dir.exists():
        print(f"\nNo transcripts directory found at: {transcript_dir}")
        return

    transcripts = sorted(transcript_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not transcripts:
        print(f"\nNo transcripts found in: {transcript_dir}")
        return

    print(f"\nSaved Transcripts ({len(transcripts)} files):\n")

    for idx, transcript in enumerate(transcripts[:20], 1):  # Show last 20
        size = transcript.stat().st_size
        modified = datetime.fromtimestamp(transcript.stat().st_mtime).strftime("%Y-%m-%d %H:%M")

        # Count messages
        try:
            line_count = sum(1 for _ in transcript.open())
        except:
            line_count = "?"

        print(f"{idx}. {transcript.name:<40} ({line_count} msgs, {size//1024}KB, {modified})")

    if len(transcripts) > 20:
        print(f"\n... and {len(transcripts) - 20} more")

    print(f"\nTo load: /load {transcript_dir}/<filename>")


def _handle_exit_command(args: list[str]) -> bool:
    """Exit the chat."""
    print("Bye.")
    return True  # Signal to exit main loop


def setup_command_completion():
    """Set up tab completion for slash commands (optional enhancement)."""
    try:
        import readline

        commands = [
            "/help", "/model", "/config", "/tools", "/history",
            "/clear", "/save", "/load", "/system", "/transcripts",
            "/exit", "/quit"
        ]

        def completer(text, state):
            options = [cmd for cmd in commands if cmd.startswith(text)]
            if state < len(options):
                return options[state]
            return None

        readline.set_completer(completer)
        readline.parse_and_bind("tab: complete")
    except ImportError:
        pass  # readline not available (Windows)
