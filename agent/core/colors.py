"""
Simple ANSI color utilities for terminal output.
Colors only apply when stdout/stderr is a TTY.
"""
import sys


class Colors:
    """ANSI color codes for terminal output."""

    # Basic colors
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright foreground colors
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"


def is_tty() -> bool:
    """Check if stdout is connected to a terminal."""
    return sys.stdout.isatty()


def colorize(text: str, color: str, bold: bool = False) -> str:
    """
    Add color to text if output is a TTY.

    Args:
        text: The text to colorize
        color: Color code from Colors class
        bold: Whether to make text bold

    Returns:
        Colored text if TTY, otherwise plain text
    """
    if not is_tty():
        return text

    prefix = Colors.BOLD if bold else ""
    return f"{prefix}{color}{text}{Colors.RESET}"


def dim(text: str) -> str:
    """Dim text (for less important info)."""
    if not is_tty():
        return text
    return f"{Colors.DIM}{text}{Colors.RESET}"


def success(text: str) -> str:
    """Green text for success messages."""
    return colorize(text, Colors.GREEN)


def error(text: str) -> str:
    """Red text for error messages."""
    return colorize(text, Colors.RED, bold=True)


def warning(text: str) -> str:
    """Yellow text for warnings."""
    return colorize(text, Colors.YELLOW)


def info(text: str) -> str:
    """Cyan text for info messages."""
    return colorize(text, Colors.CYAN)


def tool(text: str) -> str:
    """Magenta text for tool names."""
    return colorize(text, Colors.MAGENTA)


def prompt(text: str) -> str:
    """Blue text for prompts."""
    return colorize(text, Colors.BRIGHT_BLUE, bold=True)


def agent_prompt(text: str) -> str:
    """Green text for agent prompt."""
    return colorize(text, Colors.BRIGHT_GREEN, bold=True)
