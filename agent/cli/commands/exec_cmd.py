from __future__ import annotations

def add_exec(subparsers):
    parser = subparsers.add_parser("exec", help="Execute shell command safely")
    parser.add_argument("command")
    parser.set_defaults(func=run_exec)


def run_exec(args, settings):
    print(f"exec: {args.command}")
