from __future__ import annotations

def add_search(subparsers):
    parser = subparsers.add_parser("search", help="Search index")
    parser.add_argument("query")
    parser.set_defaults(func=run_search)


def run_search(args, settings):
    print(f"searching for {args.query}")
