"""
Entry point for jay-agent CLI.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Support running both as `python -m agent.cli.main` and via direct path execution.
if __package__ is None or __package__ == "":
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    from agent.core.config import load_settings
    from agent.core.logging_utils import setup_logging
    from agent.cli import commands
else:
    from ..core.config import load_settings
    from ..core.logging_utils import setup_logging
    from ..cli import commands


def main():
    parser = argparse.ArgumentParser(prog="jay-agent")
    subparsers = parser.add_subparsers(dest="command")
    commands.register(subparsers)
    args = parser.parse_args()
    settings = load_settings()
    setup_logging(settings)
    commands.dispatch(args, settings)


if __name__ == "__main__":
    main()
