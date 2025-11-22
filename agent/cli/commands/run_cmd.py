from __future__ import annotations

def add_run(subparsers):
    parser = subparsers.add_parser("run", help="Run python file")
    parser.add_argument("path")
    parser.set_defaults(func=run_run)


def run_run(args, settings):
    print(f"run python: {args.path}")
