"""Shared pytest fixtures."""

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from datetime import date
from typing import Any

import httpx
import httpx2
import pytest
from anthropic import AsyncAnthropic
from fastapi.testclient import TestClient

from app.agent.skills import transcript_search as transcript_search_module
from app.db.database import get_session_factory
from app.db.models import ChatSession
from app.llm.anthropic_client import AnthropicLLMClient
from app.llm.base import BaseLLMClient, LLMResponse, LLMUsage
from app.llm.ollama_client import OllamaLLMClient
from app.main import app
from app.rag.retrieval import DEFAULT_TOP_K, TranscriptSearchResult

#: Clearly fake value. Tests must never depend on real credentials.
TEST_API_KEY = "sk-ant-test-not-a-real-key"


class ScriptedLLMClient(BaseLLMClient):
    """Provider double that returns scripted text instead of calling out.

    Agent and router tests use this so classification, planning and reply
    generation are exercised without a provider, a network call or a paid API
    request. ``texts`` scripts one reply per call for the composed pathways,
    where one request runs two capabilities in sequence.
    """

    provider = "fake"

    def __init__(
        self,
        *,
        text: str = "",
        texts: list[str] | None = None,
        error: Exception | None = None,
        model: str = "fake-model",
    ) -> None:
        super().__init__(model=model)
        self._text = text
        self._texts = list(texts or [])
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def generate(self, messages, *, system=None, max_tokens=None, temperature=None, think=None) -> LLMResponse:
        self.calls.append(
            {
                "messages": list(messages),
                "system": system,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "think": think,
            }
        )
        if self._error is not None:
            raise self._error
        text = self._text
        if self._texts:
            text = self._texts[min(len(self.calls) - 1, len(self._texts) - 1)]
        return LLMResponse(text=text, provider=self.provider, model=self.model, usage=LLMUsage(1, 1))


@pytest.fixture
def scripted_client() -> Callable[..., ScriptedLLMClient]:
    """Factory for :class:`ScriptedLLMClient` instances."""
    return ScriptedLLMClient


class FakeRetrieval:
    """Scripted stand-in for the Phase 2 retrieval boundary.

    Capability tests replace the skill module's retrieval call, so the whole
    tool -> registry -> evidence -> prompt chain runs without a database or an
    embedding model. Real retrieval is verified separately against the ingested
    transcripts; nothing here is reported as real retrieval.
    """

    def __init__(self) -> None:
        self.passages: list[TranscriptSearchResult] = []
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None

    def script(self, *passages: TranscriptSearchResult, error: Exception | None = None) -> None:
        self.passages = list(passages)
        self.error = error

    def __call__(self, context: Any, query: str, *, top_k: int = DEFAULT_TOP_K, **kwargs: Any):
        self.calls.append({"query": query, "top_k": top_k, "context": context})
        if self.error is not None:
            raise self.error
        return list(self.passages)


@pytest.fixture
def fake_retrieval(monkeypatch) -> FakeRetrieval:
    """Replace the transcript search capability's retrieval call with a double."""
    retrieval = FakeRetrieval()
    monkeypatch.setattr(transcript_search_module, "run_transcript_search", retrieval)
    return retrieval


@pytest.fixture
def transcript_result() -> Callable[..., TranscriptSearchResult]:
    """Factory for one retrieved transcript passage."""

    def _build(**overrides: Any) -> TranscriptSearchResult:
        values: dict[str, Any] = {
            "id": "11111111-1111-1111-1111-111111111111",
            "episode_id": "pytest-episode",
            "guest": "Ada Lovelace",
            "title": "Growth loops that compound",
            "youtube_url": "https://www.youtube.com/watch?v=pytest",
            "publish_date": date(2024, 5, 1),
            "chunk_index": 0,
            "content": "Retention compounds: the fastest growers fix churn before they buy growth.",
            "metadata": {"video_id": "pytest"},
            "similarity": 0.82,
        }
        values.update(overrides)
        return TranscriptSearchResult(**values)

    return _build


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def created_sessions() -> list[uuid.UUID]:
    """Collects session ids so test-created rows are removed afterwards."""
    session_ids: list[uuid.UUID] = []
    yield session_ids

    if not session_ids:
        return

    db = get_session_factory()()
    try:
        for session_id in session_ids:
            session = db.get(ChatSession, session_id)
            if session is not None:
                db.delete(session)
        db.commit()
    finally:
        db.close()


@pytest.fixture
def run_async() -> Callable[[Coroutine[Any, Any, Any]], Any]:
    """Run a coroutine from a synchronous test.

    The suite avoids an extra async test plugin: every asynchronous unit under
    test is a single coroutine.
    """

    def _run(coro: Coroutine[Any, Any, Any]) -> Any:
        return asyncio.run(coro)

    return _run


@pytest.fixture
def anthropic_stub() -> Callable[..., AnthropicLLMClient]:
    """Build an Anthropic provider wired to a mock HTTP transport.

    The real SDK is exercised - request building, response parsing, error
    mapping - while no network call and no paid API request is made.
    """
    def _build(handler: Any, *, model: str = "claude-sonnet-4-5", **kwargs: Any) -> AnthropicLLMClient:
        http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        sdk_client = AsyncAnthropic(api_key=TEST_API_KEY, http_client=http_client, max_retries=0)
        return AnthropicLLMClient(api_key=TEST_API_KEY, model=model, client=sdk_client, **kwargs)

    return _build


@pytest.fixture
def ollama_stub() -> Callable[..., OllamaLLMClient]:
    """Build an Ollama provider backed by a mock HTTP transport (no network)."""

    def _build(handler: Any, *, model: str = "llama3.1:8b", base_url: str = "http://localhost:11434", **kwargs: Any) -> OllamaLLMClient:
        http_client = httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler))
        return OllamaLLMClient(model=model, client=http_client, **kwargs)

    return _build
