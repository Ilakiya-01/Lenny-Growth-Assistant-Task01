"""Database-backed tests for chunk storage, idempotency and vector search.

These tests need the migrated ``transcript_chunks`` table; they skip when the
configured database is unreachable or not migrated. All rows they create use a
test-only ``episode_id`` and are removed again.
"""

import math
from dataclasses import replace

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.db.database import get_session_factory
from app.db.models import TranscriptChunk
from app.db.repositories.transcript_repository import (
    ChunkRecord,
    get_embedding_dimension,
    upsert_episode_chunks,
)
from app.errors import EmbeddingDimensionMismatchError
from app.rag.embeddings import EmbeddingProvider
from app.rag.retrieval import format_embedding, search_transcript_chunks

EPISODE = "__pytest_rag__"
OTHER_EPISODE = "__pytest_rag_other__"


class TopicProvider(EmbeddingProvider):
    """Deterministic provider: topic words drive the first vector dimensions."""

    name = "topic-test"
    TOPICS = ("growth", "pricing", "churn", "hiring")

    def __init__(self, dimension: int = 384, model: str = "topic-test-384") -> None:
        self._dimension = dimension
        self.model = model

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def tokenizer(self):  # noqa: ANN201 - not needed by these tests
        raise NotImplementedError

    @property
    def max_tokens(self) -> int | None:
        return None

    def embed_documents(self, texts) -> list[list[float]]:  # noqa: ANN001
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        words = text.lower().split()
        values = [0.0] * self._dimension
        for index, topic in enumerate(self.TOPICS):
            values[index] = float(words.count(topic))
        # Tiny deterministic filler so no vector is all-zero (cosine is
        # undefined for a zero vector).
        for position, _word in enumerate(words):
            values[len(self.TOPICS) + position % 8] += 0.001
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]


@pytest.fixture
def db():
    session = get_session_factory()()
    try:
        try:
            migrated = get_embedding_dimension(session) is not None
        except SQLAlchemyError as exc:
            pytest.skip(f"database unreachable: {exc}")
        if not migrated:
            pytest.skip("transcript_chunks is missing; run 'alembic upgrade head'")
        yield session
    finally:
        try:
            session.rollback()
            session.execute(delete(TranscriptChunk).where(TranscriptChunk.episode_id.in_([EPISODE, OTHER_EPISODE])))
            session.commit()
        finally:
            session.close()


def _records(provider: TopicProvider) -> list[ChunkRecord]:
    return [
        ChunkRecord(
            episode_id=EPISODE,
            chunk_index=0,
            content="growth growth growth hiring",
            embedding=provider.embed_documents(["growth growth growth hiring"])[0],
            guest="Ada",
            title="Growth loops",
            metadata={"video_id": "abc"},
        ),
        ChunkRecord(
            episode_id=EPISODE,
            chunk_index=1,
            content="pricing pricing growth",
            embedding=provider.embed_documents(["pricing pricing growth"])[0],
            guest="Ada",
            title="Growth loops",
            metadata={"video_id": "abc"},
        ),
        ChunkRecord(
            episode_id=OTHER_EPISODE,
            chunk_index=0,
            content="churn churn renewal",
            embedding=provider.embed_documents(["churn churn renewal"])[0],
            guest="Brian",
            title="Churn talk",
            metadata={"video_id": "def"},
        ),
    ]


def _episode_row_count(db, episode_id: str) -> int:
    return int(
        db.execute(
            select(func.count()).select_from(TranscriptChunk).where(TranscriptChunk.episode_id == episode_id)
        ).scalar_one()
    )


def test_upsert_inserts_new_chunks(db) -> None:
    outcome = upsert_episode_chunks(db, _records(TopicProvider()))
    db.commit()

    assert (outcome.inserted, outcome.updated, outcome.unchanged, outcome.pruned) == (3, 0, 0, 0)
    assert _episode_row_count(db, EPISODE) == 2


def test_rerunning_unchanged_records_writes_nothing(db) -> None:
    records = _records(TopicProvider())
    upsert_episode_chunks(db, records)
    db.commit()

    outcome = upsert_episode_chunks(db, records)
    db.commit()

    assert (outcome.inserted, outcome.updated, outcome.unchanged, outcome.pruned) == (0, 0, 3, 0)


def test_changed_content_updates_in_place(db) -> None:
    provider = TopicProvider()
    records = _records(provider)
    upsert_episode_chunks(db, records)
    db.commit()

    edited = [replace(records[0], content="growth growth growth hiring edited"), *records[1:]]
    edited[0] = replace(edited[0], embedding=provider.embed_documents([edited[0].content])[0])
    outcome = upsert_episode_chunks(db, edited)
    db.commit()

    assert (outcome.inserted, outcome.updated, outcome.unchanged) == (0, 1, 2)
    assert _episode_row_count(db, EPISODE) == 2


def test_shorter_episode_prunes_stale_tail_chunks(db) -> None:
    records = _records(TopicProvider())
    upsert_episode_chunks(db, records)
    db.commit()

    outcome = upsert_episode_chunks(db, records[:1])
    db.commit()

    assert outcome.pruned == 1
    assert _episode_row_count(db, EPISODE) == 1


def test_vector_search_ranks_the_closest_chunk_first(db) -> None:
    upsert_episode_chunks(db, _records(TopicProvider()))
    db.commit()

    results = search_transcript_chunks(db, "growth", top_k=3, episode_id=EPISODE, provider=TopicProvider())

    assert [result.content for result in results] == [
        "growth growth growth hiring",
        "pricing pricing growth",
    ]
    assert results[0].similarity > results[1].similarity
    assert results[0].guest == "Ada"
    assert results[0].title == "Growth loops"
    assert results[0].metadata["video_id"] == "abc"
    assert results[0].chunk_index == 0


def test_search_can_filter_by_guest(db) -> None:
    upsert_episode_chunks(db, _records(TopicProvider()))
    db.commit()

    results = search_transcript_chunks(db, "growth renewal", top_k=5, guest="Brian", provider=TopicProvider())

    assert [result.episode_id for result in results] == [OTHER_EPISODE]


def test_search_can_filter_by_similarity(db) -> None:
    upsert_episode_chunks(db, _records(TopicProvider()))
    db.commit()

    results = search_transcript_chunks(
        db, "growth", top_k=5, min_similarity=0.9, episode_id=EPISODE, provider=TopicProvider()
    )

    assert [result.content for result in results] == ["growth growth growth hiring"]


def test_empty_query_returns_no_results(db) -> None:
    assert search_transcript_chunks(db, "   ", provider=TopicProvider()) == []


def test_dimension_mismatch_is_reported(db) -> None:
    with pytest.raises(EmbeddingDimensionMismatchError, match="vector\\(384\\)"):
        search_transcript_chunks(db, "growth", provider=TopicProvider(dimension=3, model="tiny-3"))


def test_format_embedding_uses_pgvector_text_format() -> None:
    assert format_embedding([1.0, 0.5]) == "[1.00000000,0.50000000]"
