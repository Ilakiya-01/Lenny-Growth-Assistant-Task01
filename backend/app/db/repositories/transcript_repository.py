"""Database access for transcript chunks.

Chunk identity is ``(episode_id, chunk_index)``. Re-ingesting an unchanged
episode therefore performs no writes, which keeps ingestion safe to rerun.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.orm import Session

from app.db.models import TranscriptChunk
from app.errors import EmbeddingDimensionMismatchError

logger = logging.getLogger("lenny.ingestion")


@dataclass(slots=True)
class ChunkRecord:
    """A chunk ready to be stored."""

    episode_id: str
    chunk_index: int
    content: str
    embedding: list[float]
    guest: str | None = None
    title: str | None = None
    youtube_url: str | None = None
    publish_date: date | None = None
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class UpsertOutcome:
    """How an episode's chunks were affected by an upsert."""

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    pruned: int = 0

    @property
    def written(self) -> int:
        return self.inserted + self.updated


def upsert_episode_chunks(db: Session, records: Sequence[ChunkRecord]) -> UpsertOutcome:
    """Insert or update the chunks of one episode and prune stale tail chunks.

    A row is only rewritten when its content or metadata changed, so rerunning
    ingestion over an unchanged corpus does not touch the table. ``xmax = 0``
    distinguishes freshly inserted rows from updated ones in the ``RETURNING``
    clause.
    """
    outcome = UpsertOutcome()
    if not records:
        return outcome

    rows = [
        {
            "episode_id": record.episode_id,
            "chunk_index": record.chunk_index,
            "content": record.content,
            "embedding": record.embedding,
            "guest": record.guest,
            "title": record.title,
            "youtube_url": record.youtube_url,
            "publish_date": record.publish_date,
            "metadata": record.metadata,
        }
        for record in records
    ]

    # Core DML on the mapped table: passing the ORM class here would make
    # SQLAlchemy interpret the "metadata" key as the declarative MetaData.
    table = TranscriptChunk.__table__

    statement = postgres_insert(table).values(rows)
    statement = statement.on_conflict_do_update(
        constraint="uq_transcript_chunks_episode_chunk",
        set_={
            "content": statement.excluded.content,
            "embedding": statement.excluded.embedding,
            "guest": statement.excluded.guest,
            "title": statement.excluded.title,
            "youtube_url": statement.excluded.youtube_url,
            "publish_date": statement.excluded.publish_date,
            "metadata": statement.excluded.metadata,
        },
        where=(table.c.content.is_distinct_from(statement.excluded.content))
        | (table.c.metadata.is_distinct_from(statement.excluded.metadata)),
    ).returning(table.c.id, text("(xmax = 0) AS was_inserted"))

    for _row_id, was_inserted in db.execute(statement).all():
        if was_inserted:
            outcome.inserted += 1
        else:
            outcome.updated += 1
    outcome.unchanged = len(records) - outcome.inserted - outcome.updated

    outcome.pruned = prune_episode_chunks(db, records[0].episode_id, len(records))
    return outcome


def prune_episode_chunks(db: Session, episode_id: str, keep: int) -> int:
    """Delete chunks beyond ``keep`` for an episode (shorter re-chunking)."""
    result = db.execute(
        delete(TranscriptChunk).where(
            TranscriptChunk.episode_id == episode_id,
            TranscriptChunk.chunk_index >= keep,
        )
    )
    return int(result.rowcount or 0)


def get_embedding_dimension(db: Session) -> int | None:
    """Return the vector dimension of ``transcript_chunks.embedding``.

    Returns ``None`` when the table does not exist yet (migrations pending).
    """
    value = db.execute(
        text(
            "SELECT a.atttypmod FROM pg_attribute AS a "
            "WHERE a.attrelid = to_regclass('public.transcript_chunks') AND a.attname = 'embedding'"
        )
    ).scalar_one_or_none()
    return int(value) if value and value > 0 else None


def check_embedding_dimension(db: Session, expected: int, *, model: str) -> None:
    """Fail fast when the model dimension does not match the database column."""
    actual = get_embedding_dimension(db)
    if actual is None:
        raise EmbeddingDimensionMismatchError(
            "The transcript_chunks table was not found. Apply the migrations first: "
            "cd backend && alembic upgrade head"
        )
    if actual != expected:
        raise EmbeddingDimensionMismatchError(
            f"The embedding model '{model}' produces {expected}-dimensional vectors, but "
            f"transcript_chunks.embedding is vector({actual}). Select a model with a matching "
            "dimension or add a migration for the new dimension."
        )


def count_chunks(db: Session) -> int:
    return int(db.execute(select(func.count()).select_from(TranscriptChunk)).scalar_one())


def count_episodes(db: Session) -> int:
    return int(db.execute(select(func.count(func.distinct(TranscriptChunk.episode_id)))).scalar_one())
