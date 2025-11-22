from __future__ import annotations

import subprocess
import shutil
from typing import List


def add_ssh(subparsers):
    parser = subparsers.add_parser("ssh", help="Run SSH command")
    parser.add_argument("target", help="Target in user@host or host form")
    parser.add_argument("command", help="Command to run remotely")
    parser.add_argument("--port", type=int, default=22, help="SSH port (default 22)")
    parser.add_argument("--identity", help="Path to identity/key file")
    parser.add_argument("--user", help="Optional username (if not in target)")
    parser.add_argument("--password", help="Optional password (requires sshpass installed; avoid for security)")
    parser.set_defaults(func=run_ssh)


def run_ssh(args, settings):
    cmd: List[str] = ["ssh"]
    target = args.target
    if args.user and "@" not in target:
        target = f"{args.user}@{target}"

    if args.identity:
        cmd.extend(["-i", args.identity])
    if args.port:
        cmd.extend(["-p", str(args.port)])
    cmd.extend([target, args.command])

    if args.password and not args.identity:
        sshpass = shutil.which("sshpass")
        if not sshpass:
            print("ssh failed: password provided but sshpass is not installed.")
            return
        cmd = [sshpass, "-p", args.password] + cmd

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as exc:
        print(f"SSH failed: {exc}")
        return

    print(f"exit={result.returncode}")
    if result.stdout:
        print("stdout:")
        print(result.stdout)
    if result.stderr:
        print("stderr:")
        print(result.stderr)
