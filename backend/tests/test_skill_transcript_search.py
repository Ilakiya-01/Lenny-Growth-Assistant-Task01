"""Transcript search capability tests.

The happy path runs the real chain - tool -> SkillContext -> Phase 2
``search_transcript_chunks`` -> ``match_transcript_chunks`` - against the migrated
database, skipping when it is unavailable. Failure and empty-result paths replace
the Phase 2 boundary so they are testable without breaking a database.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from app.agent.context import AgentContext
from app.agent.skills import transcript_search as transcript_search_module
from app.agent.skills.base import (
    EVIDENCE_BLOCK_EMPTY,
    EVIDENCE_BLOCK_HEADER,
    EvidenceBundle,
    SkillContext,
    evidence_to_dict,
    format_evidence_block,
)
from app.agent.skills.transcript_search import (
    MAX_TOP_K,
    MIN_EVIDENCE_SIMILARITY,
    SEARCH_TOOL_NAME,
    TranscriptSearchTool,
    _coerce_top_k,
    gather_evidence,
    run_transcript_search,
)
from app.agent.tools import default_registry
from app.db.database import get_session_factory
from app.db.models import TranscriptChunk
from app.db.repositories.transcript_repository import (
    ChunkRecord,
    get_embedding_dimension,
    upsert_episode_chunks,
)
from app.errors import EmbeddingProviderError, TranscriptSearchError
from app.rag.embeddings import EmbeddingProvider

EPISODE = "__pytest_phase4__"


class TopicProvider(EmbeddingProvider):
    """Deterministic provider: topic words drive the first vector dimensions."""

    name = "topic-test"
    TOPICS = ("growth", "pricing", "churn")

    def __init__(self, dimension: int = 384, model: str = "topic-test-384") -> None:
        self._dimension = dimension
        self.model = model
        self.queries: list[str] = []

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
        self.queries.append(text)
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        words = text.lower().split()
        values = [0.0] * self._dimension
        for index, topic in enumerate(self.TOPICS):
            values[index] = float(words.count(topic))
        for position, _word in enumerate(words):
            values[len(self.TOPICS) + position % 8] += 0.001
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]


@pytest.fixture
def db():
    """A migrated database session, or a skip when the database is unavailable."""
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
            session.execute(delete(TranscriptChunk).where(TranscriptChunk.episode_id == EPISODE))
            session.commit()
        finally:
            session.close()


@pytest.fixture
def topic_provider(monkeypatch) -> TopicProvider:
    """Make the Phase 2 retrieval function use a deterministic embedder."""
    provider = TopicProvider()
    monkeypatch.setattr("app.rag.retrieval.get_embedding_provider", lambda: provider)
    return provider


def _seed(db, provider: TopicProvider) -> None:
    outcome = upsert_episode_chunks(
        db,
        [
            ChunkRecord(
                episode_id=EPISODE,
                chunk_index=0,
                content="growth growth retention compounds over time",
                embedding=provider.embed_documents(["growth growth retention compounds over time"])[0],
                guest="Ada Lovelace",
                title="Growth loops that compound",
                youtube_url="https://www.youtube.com/watch?v=pytest",
                publish_date=date(2024, 5, 1),
                metadata={"video_id": "pytest"},
            ),
            ChunkRecord(
                episode_id=EPISODE,
                chunk_index=1,
                content="pricing pricing packaging changes everything",
                embedding=provider.embed_documents(["pricing pricing packaging changes everything"])[0],
                guest="Ada Lovelace",
                title="Growth loops that compound",
                metadata={"video_id": "pytest"},
            ),
        ],
    )
    db.commit()
    assert outcome.inserted == 2


def _context(**overrides: Any) -> SkillContext:
    values: dict[str, Any] = {"request": "retention", "registry": default_registry()}
    values.update(overrides)
    return SkillContext(**values)


def test_the_tool_retrieves_ranked_chunks_with_source_metadata(db, topic_provider, run_async) -> None:
    _seed(db, topic_provider)

    result = run_async(
        TranscriptSearchTool().run({"query": "growth growth retention"}, _context(db=db))
    )

    assert result.tool == SEARCH_TOOL_NAME
    assert result.metadata["query"] == "growth growth retention"
    assert result.metadata["result_count"] >= 1

    passage = result.metadata["passages"][0]
    assert passage["episode_id"] == EPISODE
    assert passage["title"] == "Growth loops that compound"
    assert passage["guest"] == "Ada Lovelace"
    assert passage["youtube_url"] == "https://www.youtube.com/watch?v=pytest"
    assert passage["publish_date"] == "2024-05-01"
    assert passage["chunk_index"] == 0
    assert 0.0 < passage["similarity"] <= 1.0
    assert "growth" in passage["excerpt"]

    # The prompt-ready rendering and the structured passages describe the same rows.
    assert EVIDENCE_BLOCK_HEADER in result.content
    assert "Growth loops that compound" in result.content
    assert len(result.metadata["results"]) == result.metadata["result_count"]


def test_the_natural_language_query_reaches_the_phase_2_embedder(db, topic_provider, run_async) -> None:
    _seed(db, topic_provider)

    run_async(
        TranscriptSearchTool().run(
            {"query": "how do the best founders price", "top_k": 2},
            _context(db=db),
        )
    )

    assert topic_provider.queries == ["how do the best founders price"]


def test_the_result_size_follows_the_requested_top_k(db, topic_provider, run_async) -> None:
    _seed(db, topic_provider)

    result = run_async(TranscriptSearchTool().run({"query": "growth pricing", "top_k": 1}, _context(db=db)))

    assert result.metadata["top_k"] == 1
    assert result.metadata["result_count"] == 1


def test_an_empty_result_is_reported_as_no_evidence(fake_retrieval, run_async) -> None:
    fake_retrieval.script()

    tool_result = run_async(TranscriptSearchTool().run({"query": "nothing matches"}, _context()))
    bundle = run_async(gather_evidence(_context(), "nothing matches"))

    assert tool_result.metadata["result_count"] == 0
    assert tool_result.metadata["passages"] == []
    assert tool_result.content == EVIDENCE_BLOCK_EMPTY
    assert isinstance(bundle, EvidenceBundle)
    assert bundle.has_evidence is False
    assert bundle.count == 0
    assert bundle.sources() == ()


def test_evidence_is_retrieved_through_the_registered_tool(fake_retrieval, transcript_result, run_async) -> None:
    fake_retrieval.script(transcript_result())
    context = _context()

    assert isinstance(context.registry.tool(SEARCH_TOOL_NAME), TranscriptSearchTool)

    bundle = run_async(gather_evidence(context, "retention"))

    assert bundle.count == 1
    assert bundle.passages[0].episode_id == "pytest-episode"
    assert fake_retrieval.calls[0]["query"] == "retention"


def test_the_search_tool_reports_weak_matches_that_are_not_yet_evidence(fake_retrieval, transcript_result, run_async) -> None:
    """Retrieval stays generous; the evidence quality gate lives one level up.

    A search request should still show what the knowledge base contains, while
    the same rows must not become the basis of a grounded answer.
    """
    fake_retrieval.script(transcript_result(similarity=MIN_EVIDENCE_SIMILARITY - 0.05))
    context = _context()

    tool_result = run_async(TranscriptSearchTool().run({}, context))
    bundle = run_async(gather_evidence(context, "retention"))

    assert tool_result.metadata["result_count"] == 1
    assert tool_result.metadata["passages"][0]["similarity"] == round(MIN_EVIDENCE_SIMILARITY - 0.05, 4)
    assert bundle.has_evidence is False
    assert bundle.count == 0
    assert bundle.text == EVIDENCE_BLOCK_EMPTY


def test_only_passages_above_the_evidence_floor_enter_the_bundle(fake_retrieval, transcript_result, run_async) -> None:
    fake_retrieval.script(
        transcript_result(chunk_index=0, similarity=0.78),
        transcript_result(chunk_index=2, content="Chit-chat about the weather.", similarity=0.55),
    )

    bundle = run_async(gather_evidence(_context(), "retention"))

    assert bundle.count == 1
    assert bundle.passages[0].chunk_index == 0
    assert "Retention compounds" in bundle.text
    assert "weather" not in bundle.text


def test_retrieved_evidence_is_recorded_on_the_agent_context(fake_retrieval, transcript_result, run_async) -> None:
    fake_retrieval.script(transcript_result())
    context = _context(agent_context=AgentContext(user_message="retention"))

    run_async(gather_evidence(context, "retention"))

    assert context.agent_context.retrieved_context == (
        "Retention compounds: the fastest growers fix churn before they buy growth.",
    )


def test_a_missing_embedding_model_is_an_actionable_error(monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise EmbeddingProviderError("could not load the model from D:/models/bge-small")

    monkeypatch.setattr(transcript_search_module, "search_transcript_chunks", _boom)

    with pytest.raises(TranscriptSearchError) as excinfo:
        run_transcript_search(_context(db=object()), "retention")

    assert "embedding" in str(excinfo.value)
    assert "D:/models" not in excinfo.value.user_message
    assert "EMBEDDING_" in excinfo.value.user_message


def test_a_database_failure_is_an_actionable_error(monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise SQLAlchemyError("connection refused by db.internal")

    monkeypatch.setattr(transcript_search_module, "search_transcript_chunks", _boom)

    with pytest.raises(TranscriptSearchError) as excinfo:
        run_transcript_search(_context(db=object()), "retention")

    assert "db.internal" not in excinfo.value.user_message
    assert "DATABASE_URL" in excinfo.value.user_message


def test_searching_without_a_database_session_is_an_actionable_error() -> None:
    with pytest.raises(TranscriptSearchError) as excinfo:
        run_transcript_search(_context(), "retention")

    assert "requires a database session" in str(excinfo.value)
    assert "DATABASE_URL" in excinfo.value.user_message


def test_blank_queries_are_rejected() -> None:
    with pytest.raises(TranscriptSearchError):
        run_transcript_search(_context(db=object()), "   ")


def test_the_search_size_is_bounded_and_validated() -> None:
    assert _coerce_top_k(None) >= 1
    assert _coerce_top_k(2) == 2
    assert _coerce_top_k(999) == MAX_TOP_K

    with pytest.raises(TranscriptSearchError):
        _coerce_top_k(0)
    with pytest.raises(TranscriptSearchError):
        _coerce_top_k("many")


def test_evidence_metadata_is_json_ready_and_preserves_the_source(transcript_result) -> None:
    passage = transcript_result(publish_date=None, title=None, guest=None, content="x" * 400, similarity=0.123456)

    payload = evidence_to_dict(passage)

    assert set(payload) == {
        "episode_id",
        "title",
        "guest",
        "publish_date",
        "youtube_url",
        "chunk_index",
        "similarity",
        "excerpt",
    }
    assert payload["publish_date"] is None
    assert payload["title"] is None
    assert payload["guest"] is None
    assert payload["similarity"] == 0.1235
    assert payload["excerpt"].endswith("...")
    assert len(payload["excerpt"]) < 400


def test_evidence_block_is_numbered_and_citable(transcript_result) -> None:
    block = format_evidence_block(
        [
            transcript_result(chunk_index=0),
            transcript_result(chunk_index=2, guest="Brian", title="Pricing talk", similarity=0.55),
        ]
    )

    assert block.startswith(EVIDENCE_BLOCK_HEADER)
    assert "[1] Growth loops that compound - Ada Lovelace (2024-05-01), similarity 0.820" in block
    assert "[2] Pricing talk - Brian (2024-05-01), similarity 0.550" in block
    assert format_evidence_block([]) == EVIDENCE_BLOCK_EMPTY
    assert format_evidence_block([transcript_result()], limit=1).count("[1]") == 1
