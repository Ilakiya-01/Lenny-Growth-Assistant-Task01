#!/usr/bin/env python
"""Query the transcript knowledge base with semantic similarity search.

Usage (from the repository root)::

    backend/.venv/Scripts/python.exe ingestion/search.py "how do guests find product-market fit?"
    backend/.venv/Scripts/python.exe ingestion/search.py "pricing advice" --top-k 3 --min-similarity 0.4

This is the retrieval foundation only - no agent or chat behaviour. Later
phases call ``app.rag.retrieval.search_transcript_chunks`` from a tool.
"""

import argparse
import logging
import os
import sys
import textwrap
from pathlib import Path

# The retrieval foundation lives with the backend application code.
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.database import get_session_factory  # noqa: E402
from app.rag.retrieval import search_transcript_chunks  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Semantic search over the ingested Lenny transcripts.")
    parser.add_argument("query", help="natural language search query")
    parser.add_argument("--top-k", type=int, default=5, help="number of chunks to return (default: 5)")
    parser.add_argument(
        "--min-similarity",
        type=float,
        default=None,
        help="optional cosine similarity floor, e.g. 0.5",
    )
    parser.add_argument("--guest", default=None, help="restrict results to one guest")
    parser.add_argument("--episode", default=None, help="restrict results to one episode slug")
    parser.add_argument("--snippet", type=int, default=400, help="characters of each chunk to print (default: 400)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.ERROR)
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    # Transcript titles contain typographic quotes and other non-ASCII
    # characters; never let a legacy console code page mangle them.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    with get_session_factory()() as session:
        results = search_transcript_chunks(
            session,
            args.query,
            top_k=args.top_k,
            min_similarity=args.min_similarity,
            guest=args.guest,
            episode_id=args.episode,
        )

    if not results:
        print("No transcript chunks matched the query.")
        return 0

    print(f"{len(results)} result(s) for: {args.query}\n")
    for rank, result in enumerate(results, start=1):
        print(f"{rank}. similarity={result.similarity:.3f}  {result.title or result.episode_id}")
        print(f"   guest={result.guest or 'unknown'}  episode={result.episode_id}  chunk={result.chunk_index}")
        if result.youtube_url:
            print(f"   {result.youtube_url}")
        snippet = " ".join(result.content.split())
        if len(snippet) > args.snippet:
            snippet = snippet[: args.snippet].rstrip() + "..."
        print(textwrap.indent(textwrap.fill(snippet, width=100) + "\n", "   "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
