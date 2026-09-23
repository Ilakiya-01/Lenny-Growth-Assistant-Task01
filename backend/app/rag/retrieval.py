"""Vector similarity search over transcript chunks.

This is the retrieval foundation of the knowledge base: it embeds a query with
the configured provider and calls the ``match_transcript_chunks`` database
function (cosine similarity, HNSW index). It deliberately contains no agent or
chat logic - later phases consume it as a tool.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.repositories.transcript_repository import check_embedding_dimension
from app.rag.embeddings import EmbeddingProvider, get_embedding_provider

logger = logging.getLogger("lenny.retrieval")

DEFAULT_TOP_K = 5

MATCH_CHUNKS_SQL = text(
    "SELECT * FROM public.match_transcript_chunks("
    "CAST(:query_embedding AS vector), :match_count, :match_threshold, :filter_guest, :filter_episode_id)"
)


@dataclass(slots=True)
class TranscriptSearchResult:
    """One retrieved transcript chunk with its source metadata."""

    id: str
    episode_id: str
    guest: str | None
    title: str | None
    youtube_url: str | None
    publish_date: date | None
    chunk_index: int
    content: str
    metadata: dict[str, Any]
    similarity: float


def format_embedding(values: Sequence[float]) -> str:
    """Render a vector in pgvector's text format (``[1,2,3]``)."""
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


def search_transcript_chunks(
    db: Session,
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float | None = None,
    guest: str | None = None,
    episode_id: str | None = None,
    provider: EmbeddingProvider | None = None,
) -> list[TranscriptSearchResult]:
    """Return the transcript chunks most similar to ``query``.

    Similarity is cosine similarity in ``[-1, 1]`` (practically ``[0, 1]`` for
    text embeddings); results are ordered by decreasing similarity.
    """
    query = query.strip()
    if not query:
        return []
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")

    provider = provider or get_embedding_provider()
    check_embedding_dimension(db, provider.dimension, model=provider.model)

    embedding = provider.embed_query(query)
    rows = (
        db.execute(
            MATCH_CHUNKS_SQL,
            {
                "query_embedding": format_embedding(embedding),
                "match_count": top_k,
                "match_threshold": min_similarity,
                "filter_guest": guest,
                "filter_episode_id": episode_id,
            },
        )
        .mappings()
        .all()
    )

    results = [
        TranscriptSearchResult(
            id=str(row["id"]),
            episode_id=row["episode_id"],
            guest=row["guest"],
            title=row["title"],
            youtube_url=row["youtube_url"],
            publish_date=row["publish_date"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            metadata=row["metadata"] or {},
            similarity=float(row["similarity"]),
        )
        for row in rows
    ]
    logger.debug("Retrieved %d chunks for query %r", len(results), query[:80])
    return results
