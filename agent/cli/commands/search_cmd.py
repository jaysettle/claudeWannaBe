from __future__ import annotations

def add_search(subparsers):
    parser = subparsers.add_parser("search", help="Search index")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=5, help="Max results")
    parser.set_defaults(func=run_search)


def run_search(args, settings):
    from pathlib import Path
    from ...core.llm_client import LLMClient
    from ...rag.index import load_index
    from ...rag.search import search
    from ...rag.embed import embed_texts

    base = (Path.cwd() / settings.data_dir / "index").resolve()
    embeddings, metadata = load_index(base)
    if embeddings is None or metadata is None:
        print(f"No index found at {base.with_suffix('.npy')}. Run 'jay-agent index' first.")
        return

    llm = LLMClient(settings)
    q_vec = embed_texts(llm, [args.query])[0]

    results = search(embeddings, metadata, q_vec, limit=args.limit)
    if not results:
        print(f"No matches for '{args.query}'.")
        return

    print(f"Top {len(results)} results for '{args.query}':")
    for item in results:
        path = item.get("path")
        start = item.get("start_line")
        snippet = (item.get("text") or "").splitlines()
        first_line = snippet[0] if snippet else ""
        score = item.get("score")
        score_str = f" (score {score:.3f})" if score is not None else ""
        print(f"- {path}:{start}{score_str} -> {first_line}")
