from __future__ import annotations

def add_ssh(subparsers):
    parser = subparsers.add_parser("ssh", help="Run SSH command")
    parser.add_argument("target")
    parser.add_argument("command")
    parser.set_defaults(func=run_ssh)


def run_ssh(args, settings):
    print(f"ssh {args.target}: {args.command}")
