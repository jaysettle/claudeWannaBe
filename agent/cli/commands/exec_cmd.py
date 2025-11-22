from __future__ import annotations

import subprocess


def add_exec(subparsers):
    parser = subparsers.add_parser("exec", help="Execute shell command")
    parser.add_argument("command", help="Shell command to run")
    parser.set_defaults(func=run_exec)


def run_exec(args, settings):
    try:
        result = subprocess.run(
            ["/bin/bash", "-lc", args.command],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as exc:
        print(f"exec failed: {exc}")
        return

    print(f"exit={result.returncode}")
    if result.stdout:
        print("stdout:")
        print(result.stdout)
    if result.stderr:
        print("stderr:")
        print(result.stderr)
