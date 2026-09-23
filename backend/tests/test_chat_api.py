"""Tests for the production chat workflow (Phase 5).

The endpoint-level tests run against the database configured through
``DATABASE_URL`` and are skipped when none is configured. The provider is always
a scripted double: these tests make no paid call and no live model call.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.agent.agent import AgentResult, ApplicationAgent
from app.agent.intents import ExecutionPath, Intent
from app.api import chat as chat_api
from app.config import get_settings
from app.errors import LLMConfigurationError, LLMUnavailableError
from app.llm.factory import MODE_CLOUD, MODE_OLLAMA
from app.services import chat_service

pytestmark = pytest.mark.skipif(
    not get_settings().database_url, reason="DATABASE_URL is not configured"
)

CHAT_URL = "/api/chat"
STREAM_URL = "/api/chat/stream"

#: Routes to the grounded Q&A capability; retrieval is the scripted double, so
#: these tests never load an embedding model.
QUESTION = "What did Lenny's guests say about product-market fit?"
ESSAY_REQUEST = "Write an essay about retention."
ARTIFACT_REQUEST = "Create a markdown product strategy document about retention."

ARTIFACT_JSON = json.dumps(
    {
        "type": "markdown",
        "title": "Product strategy",
        "content": "# Product strategy\n\nShip the retention fix first.",
    }
)

DIRECT_REPLY = "Product-market fit shows up as retention that holds without new traffic."


@pytest.fixture
def stub_chat_agent(monkeypatch, scripted_client, fake_retrieval, transcript_result):
    """Replace the cached chat agent with one whose provider is scripted.

    Retrieval is replaced as well, so a grounded question exercises the whole
    agent -> capability -> evidence chain without an embedding model or a live
    vector query. Nothing here is reported as real retrieval.
    """
    fake_retrieval.script(transcript_result())

    def _install(*, text: str = "", texts: list[str] | None = None, error: Exception | None = None):
        agent = ApplicationAgent(client=scripted_client(text=text, texts=texts, error=error), llm_mode=MODE_OLLAMA)
        requested: list[str] = []

        def _factory(llm_mode: str) -> ApplicationAgent:
            requested.append(llm_mode)
            return agent

        monkeypatch.setattr(chat_service, "get_chat_agent", _factory)
        return agent, requested

    return _install


def _create_session(client: TestClient, created_sessions: list[uuid.UUID], title: str | None = None) -> uuid.UUID:
    body = client.post("/api/sessions", json={"title": title} if title else {}).json()
    session_id = uuid.UUID(body["id"])
    created_sessions.append(session_id)
    return session_id


def _messages(client: TestClient, session_id: uuid.UUID) -> list[dict[str, Any]]:
    return client.get(f"/api/sessions/{session_id}/messages").json()["messages"]


def _sse_frames(response) -> list[tuple[str, dict[str, Any]]]:
    """Parse ``text/event-stream`` frames into (event, data) pairs."""
    frames: list[tuple[str, dict[str, Any]]] = []
    event = ""
    for line in response.iter_lines():
        if line.startswith("event: "):
            event = line[len("event: ") :]
        elif line.startswith("data: "):
            frames.append((event, json.loads(line[len("data: ") :])))
            event = ""
    return frames


def test_a_turn_is_answered_and_both_messages_are_persisted(
    client: TestClient, created_sessions: list[uuid.UUID], stub_chat_agent
) -> None:
    stub_chat_agent(text=DIRECT_REPLY)
    session_id = _create_session(client, created_sessions)

    response = client.post(CHAT_URL, json={"session_id": str(session_id), "message": QUESTION})

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == str(session_id)
    assert body["message"]["role"] == "assistant"
    assert body["message"]["content"] == DIRECT_REPLY
    assert body["user_message"]["role"] == "user"
    assert body["user_message"]["content"] == QUESTION
    assert body["artifact"] is None
    assert body["intent"] == "rag_qa"
    assert body["provider"] == "fake"
    # Provenance travels as structured data, so the UI never has to trust the
    # model to format its own attribution.
    assert [source["guest"] for source in body["sources"]] == ["Ada Lovelace"]
    assert body["metrics"]["evidence_count"] == 1

    persisted = _messages(client, session_id)
    assert [(item["role"], item["content"]) for item in persisted] == [
        ("user", QUESTION),
        ("assistant", DIRECT_REPLY),
    ]


def test_a_greeting_stays_on_the_general_path_with_no_retrieval(
    client: TestClient, created_sessions: list[uuid.UUID], stub_chat_agent, fake_retrieval
) -> None:
    """A conversational opener must not be routed through transcript grounding.

    Regression guard for the Phase 6 check that "hi" is answered as a normal
    reply: no retrieval, no skills, one provider call, and the turn persisted
    once.
    """
    agent, _ = stub_chat_agent(text="Hi! What are you working on today?")
    session_id = _create_session(client, created_sessions)

    response = client.post(CHAT_URL, json={"session_id": str(session_id), "message": "hi"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "general"
    assert body["skills"] == []
    assert body["sources"] == []
    assert body["message"]["content"] == "Hi! What are you working on today?"
    stages = [event["stage"] for event in body["activity"]]
    pathway = next(e["detail"] for e in body["activity"] if e["stage"] == "preparing_pathway")
    assert pathway["execution_path"] == "direct_response"
    assert "retrieving_evidence" not in stages
    assert fake_retrieval.calls == []
    assert len(agent.client.calls) == 1

    persisted = _messages(client, session_id)
    assert [(item["role"], item["content"]) for item in persisted] == [
        ("user", "hi"),
        ("assistant", "Hi! What are you working on today?"),
    ]


def test_a_structured_artifact_is_returned_separately_and_stored_on_the_message(
    client: TestClient, created_sessions: list[uuid.UUID], stub_chat_agent
) -> None:
    stub_chat_agent(text=ARTIFACT_JSON)
    session_id = _create_session(client, created_sessions)

    response = client.post(CHAT_URL, json={"session_id": str(session_id), "message": ARTIFACT_REQUEST})

    assert response.status_code == 200
    body = response.json()
    assert body["artifact"] == {
        "type": "markdown",
        "title": "Product strategy",
        "content": "# Product strategy\n\nShip the retention fix first.",
        "css": None,
    }
    # The artifact rides beside the reply; the assistant text is never the place
    # a renderer has to parse it back out of.
    assert "<artifact" not in body["message"]["content"]
    assert body["metrics"]["artifact_type"] == "markdown"

    persisted = _messages(client, session_id)
    assert persisted[1]["artifact"]["title"] == "Product strategy"


def test_the_first_message_names_an_untitled_session(
    client: TestClient, created_sessions: list[uuid.UUID], stub_chat_agent
) -> None:
    stub_chat_agent(text=DIRECT_REPLY)
    session_id = _create_session(client, created_sessions)

    client.post(CHAT_URL, json={"session_id": str(session_id), "message": QUESTION})

    listing = client.get("/api/sessions").json()["sessions"]
    titled = next(item for item in listing if item["id"] == str(session_id))
    # Long requests are shortened on a word boundary so the sidebar stays tidy.
    assert titled["title"] == chat_service.derive_title(QUESTION)
    assert titled["title"].startswith("What did Lenny's guests")
    assert titled["title"].endswith("…")
    assert len(titled["title"]) <= chat_service.TITLE_MAX_LENGTH + 1


def test_an_existing_title_is_left_alone(
    client: TestClient, created_sessions: list[uuid.UUID], stub_chat_agent
) -> None:
    stub_chat_agent(text=DIRECT_REPLY)
    session_id = _create_session(client, created_sessions, title="Onboarding research")

    client.post(CHAT_URL, json={"session_id": str(session_id), "message": QUESTION})

    listing = client.get("/api/sessions").json()["sessions"]
    titled = next(item for item in listing if item["id"] == str(session_id))
    assert titled["title"] == "Onboarding research"


def test_history_stays_inside_its_own_session(
    client: TestClient, created_sessions: list[uuid.UUID], stub_chat_agent
) -> None:
    stub_chat_agent(text=DIRECT_REPLY)
    first = _create_session(client, created_sessions)
    second = _create_session(client, created_sessions)

    client.post(CHAT_URL, json={"session_id": str(first), "message": QUESTION})
    client.post(CHAT_URL, json={"session_id": str(second), "message": ESSAY_REQUEST})

    assert [item["content"] for item in _messages(client, first)] == [QUESTION, DIRECT_REPLY]
    assert [item["content"] for item in _messages(client, second)] == [
        ESSAY_REQUEST,
        DIRECT_REPLY,
    ]


def test_the_requested_mode_reaches_the_agent_factory(
    client: TestClient, created_sessions: list[uuid.UUID], stub_chat_agent
) -> None:
    _, requested = stub_chat_agent(text=DIRECT_REPLY)
    session_id = _create_session(client, created_sessions)

    response = client.post(
        CHAT_URL, json={"session_id": str(session_id), "message": QUESTION, "llm_mode": MODE_CLOUD}
    )

    assert response.status_code == 200
    assert requested == [MODE_CLOUD]


def test_an_unsupported_mode_is_refused_rather_than_silently_substituted(
    client: TestClient, created_sessions: list[uuid.UUID], stub_chat_agent
) -> None:
    stub_chat_agent(text=DIRECT_REPLY)
    session_id = _create_session(client, created_sessions)

    response = client.post(
        CHAT_URL, json={"session_id": str(session_id), "message": QUESTION, "llm_mode": "gpt-somewhere"}
    )

    assert response.status_code == 503
    # The client gets the safe, actionable message; the unsupported value itself
    # is only ever logged.
    assert response.json()["detail"] == LLMConfigurationError.user_message
    assert _messages(client, session_id) == []


def test_a_provider_failure_is_reported_and_persists_nothing(
    client: TestClient, created_sessions: list[uuid.UUID], stub_chat_agent
) -> None:
    stub_chat_agent(error=LLMUnavailableError("connection refused", user_message="Cannot reach the local model."))
    session_id = _create_session(client, created_sessions)

    response = client.post(CHAT_URL, json={"session_id": str(session_id), "message": QUESTION})

    assert response.status_code == 503
    assert response.json()["detail"] == "Cannot reach the local model."
    # A failed turn leaves no partial history behind, so a retry cannot duplicate
    # the user's message.
    assert _messages(client, session_id) == []


def test_an_unknown_session_is_a_404(
    client: TestClient, stub_chat_agent
) -> None:
    stub_chat_agent(text=DIRECT_REPLY)

    response = client.post(CHAT_URL, json={"session_id": str(uuid.uuid4()), "message": QUESTION})

    assert response.status_code == 404


def test_an_empty_message_is_rejected(client: TestClient, created_sessions: list[uuid.UUID], stub_chat_agent) -> None:
    stub_chat_agent(text=DIRECT_REPLY)
    session_id = _create_session(client, created_sessions)

    response = client.post(CHAT_URL, json={"session_id": str(session_id), "message": ""})

    assert response.status_code == 422


def test_the_stream_reports_activity_then_the_completed_turn(
    client: TestClient, created_sessions: list[uuid.UUID], stub_chat_agent
) -> None:
    stub_chat_agent(text=ARTIFACT_JSON)
    session_id = _create_session(client, created_sessions)

    with client.stream(
        "POST", STREAM_URL, json={"session_id": str(session_id), "message": ARTIFACT_REQUEST}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        frames = _sse_frames(response)

    events = [name for name, _ in frames]
    assert events[0] == chat_api.EVENT_ACTIVITY
    assert chat_api.EVENT_ACTIVITY in events
    assert events[-2] == chat_api.EVENT_ARTIFACT_READY
    assert events[-1] == chat_api.EVENT_DONE

    artifact = dict(frames[-2][1])
    assert artifact["type"] == "markdown"
    assert artifact["title"] == "Product strategy"

    done = dict(frames[-1][1])
    assert done["message"]["content"]
    assert done["message"]["id"]
    assert done["artifact"]["title"] == "Product strategy"
    assert [stage["stage"] for stage in done["activity"]][-1] == "completed"

    # The stream persists the turn exactly like the JSON route does.
    assert len(_messages(client, session_id)) == 2


def test_the_stream_reports_a_failure_as_an_error_event(
    client: TestClient, created_sessions: list[uuid.UUID], stub_chat_agent
) -> None:
    stub_chat_agent(error=LLMUnavailableError("connection refused", user_message="Cannot reach the local model."))
    session_id = _create_session(client, created_sessions)

    with client.stream("POST", STREAM_URL, json={"session_id": str(session_id), "message": QUESTION}) as response:
        frames = _sse_frames(response)

    assert frames[-1][0] == chat_api.EVENT_ERROR
    assert frames[-1][1]["detail"] == "Cannot reach the local model."
    assert frames[-1][1]["status"] == 503
    assert _messages(client, session_id) == []


def test_activity_events_carry_no_request_text(
    client: TestClient, created_sessions: list[uuid.UUID], stub_chat_agent
) -> None:
    stub_chat_agent(text=DIRECT_REPLY)
    session_id = _create_session(client, created_sessions)

    with client.stream("POST", STREAM_URL, json={"session_id": str(session_id), "message": QUESTION}) as response:
        frames = _sse_frames(response)

    activity = [data for name, data in frames if name == chat_api.EVENT_ACTIVITY]
    assert activity
    serialised = json.dumps(activity)
    assert "product-market fit" not in serialised
    assert QUESTION not in serialised


def test_metrics_only_expose_the_safe_subset() -> None:
    turn = chat_service.ChatTurn(
        session_id=uuid.uuid4(),
        user_message=None,  # type: ignore[arg-type]
        assistant_message=None,  # type: ignore[arg-type]
        result=_result_with_metadata(
            {
                "word_count": 1180,
                "reading_time_minutes": 5,
                "insufficient_evidence": False,
                "question": "a question that must not be echoed",
                "passages": [{"content": "retrieved transcript text"}],
                "usage": object(),
            }
        ),
    )

    metrics = turn.metrics()

    assert metrics == {"word_count": 1180, "reading_time_minutes": 5, "insufficient_evidence": False}


def test_titles_are_shortened_on_a_word_boundary() -> None:
    assert chat_service.derive_title("Short question") == "Short question"
    assert chat_service.derive_title("   spaced   out   ") == "spaced out"
    assert chat_service.derive_title("") == ""

    long_title = chat_service.derive_title("word " * 40, max_length=20)
    assert long_title.endswith("…")
    assert len(long_title) <= 21
    assert "word word word" in long_title


def test_an_unexpected_error_never_leaks_its_detail() -> None:
    driver_error = OperationalError("SELECT 1", {}, Exception("postgres://user:secret@host/db"))

    payload = chat_api.error_payload(driver_error)

    assert payload["status"] == 503
    assert "secret" not in payload["detail"]
    assert payload["detail"] == chat_api.user_message_for(driver_error)


def _result_with_metadata(metadata: dict[str, Any]) -> AgentResult:
    """Minimal AgentResult stand-in for the metadata filtering unit test."""
    return AgentResult(
        status="completed",
        intent=Intent.SHIP30FOR30,
        confidence=1.0,
        execution_path=ExecutionPath.SHIP30FOR30,
        capability="ship30for30",
        capability_available=True,
        llm_mode=MODE_OLLAMA,
        provider="fake",
        model="fake-model",
        classifier="heuristic",
        metadata=metadata,
    )
