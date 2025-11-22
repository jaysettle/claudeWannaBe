from __future__ import annotations

def add_ask(subparsers):
    parser = subparsers.add_parser("ask", help="One-shot question")
    parser.add_argument("query")
    parser.set_defaults(func=run_ask)


def run_ask(args, settings):
    print(f"ask: {args.query}")
