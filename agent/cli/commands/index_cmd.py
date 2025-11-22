from __future__ import annotations

from pathlib import Path

from ...core.llm_client import LLMClient
from ...rag.chunk import chunk_lines
from ...rag.embed import embed_texts
from ...rag.index import save_index


ALLOWED_EXTS = {".md", ".markdown", ".txt", ".py", ".json", ".toml", ".yaml", ".yml"}


def add_index(subparsers):
    parser = subparsers.add_parser("index", help="Index repository")
    parser.add_argument("path", default=".", nargs="?")
    parser.set_defaults(func=run_index)


def run_index(args, settings):
    base = Path(args.path).resolve()
    if not base.exists():
        print(f"Path not found: {base}")
        return

    llm = LLMClient(settings)
    metadata = []
    texts = []

    for file in base.rglob("*"):
        if file.is_dir() or file.name.startswith(".") or file.suffix.lower() not in ALLOWED_EXTS:
            continue
        try:
            text = file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for start_line, chunk in chunk_lines(text):
            metadata.append({"path": str(file.relative_to(base)), "start_line": start_line, "text": chunk})
            texts.append(chunk)

    if not metadata:
        print("No files indexed (nothing matching allowed extensions).")
        return

    embeddings = embed_texts(llm, texts)

    index_path = (Path.cwd() / settings.data_dir / "index").resolve()
    save_index(index_path, embeddings, metadata)
    print(f"Indexed {len(metadata)} chunks from {base} -> {index_path.with_suffix('.npy')} / {index_path.with_suffix('.meta.json')}")
