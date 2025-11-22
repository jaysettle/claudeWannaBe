from __future__ import annotations

from .chat import add_chat
from .ask import add_ask
from .index_cmd import add_index
from .search_cmd import add_search
from .exec_cmd import add_exec
from .run_cmd import add_run
from .ssh_cmd import add_ssh


def register(subparsers):
    add_chat(subparsers)
    add_ask(subparsers)
    add_index(subparsers)
    add_search(subparsers)
    add_exec(subparsers)
    add_run(subparsers)
    add_ssh(subparsers)


def dispatch(args, settings):
    if not hasattr(args, "func"):
        raise SystemExit("No command provided")
    args.func(args, settings)
