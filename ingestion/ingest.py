#!/usr/bin/env python
"""Ingest Lenny podcast transcripts into the PostgreSQL/pgvector knowledge base.

Usage (from the repository root)::

    backend/.venv/Scripts/python.exe ingestion/ingest.py            # full corpus
    backend/.venv/Scripts/python.exe ingestion/ingest.py --dry-run  # parse + chunk only
    backend/.venv/Scripts/python.exe ingestion/ingest.py --limit 5  # first five episodes
    backend/.venv/Scripts/python.exe ingestion/ingest.py --episode ada-chen-rekhi --verbose

The transcript repository is read from ``TRANSCRIPTS_PATH`` in the root
``.env`` file. The command is safe to rerun: unchanged chunks are not rewritten.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# The ingestion pipeline lives with the backend application code so the CLI
# and the API share configuration, models and the retrieval foundation.
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.rag.pipeline import ingest_transcripts  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest Lenny podcast transcripts into PostgreSQL/pgvector.")
    parser.add_argument("--limit", type=int, default=None, help="only ingest the first N transcripts")
    parser.add_argument(
        "--episode",
        action="append",
        default=None,
        help="only ingest the given episode slug (folder name); repeatable",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse, normalize and chunk without embedding or writing to the database",
    )
    parser.add_argument("--verbose", action="store_true", help="log every episode instead of every tenth")
    return parser.parse_args(argv)


def _configure_logging(*, verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Long transcripts are tokenized for chunking but never embedded whole, so
    # the tokenizer's "sequence longer than model maximum" notice is expected.
    logging.getLogger("transformers").setLevel(logging.ERROR)
    # Model loading checks the Hugging Face cache over the network; keep the
    # ingestion log readable.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_logging(verbose=args.verbose)
    # Episode titles can contain non-ASCII characters; do not let a legacy
    # console code page mangle the summary.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    metrics = ingest_transcripts(
        limit=args.limit,
        episodes=args.episode,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )

    print()
    print("Ingestion summary")
    for line in metrics.summary_lines(dry_run=args.dry_run):
        print(f"  {line}")
    if metrics.failures:
        print("\nFailed files")
        for failure in metrics.failures:
            print(f"  - {failure.path}: {failure.error}")

    return 1 if metrics.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
