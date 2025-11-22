from __future__ import annotations

def add_index(subparsers):
    parser = subparsers.add_parser("index", help="Index repository")
    parser.add_argument("path", default=".", nargs="?")
    parser.set_defaults(func=run_index)


def run_index(args, settings):
    print(f"indexing {args.path}")
