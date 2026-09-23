"""Agent context tests.

Context assembly reads the conversation history of one session through the
Phase 1 session service, so these tests need the configured database and are
skipped when it is absent.
"""

from __future__ import annotations

import uuid

import pytest

from app.agent.context import (
    CONVERSATION_ROLES,
    MAX_HISTORY_MESSAGES,
    AgentContext,
    ConversationTurn,
)
from app.config import get_settings
from app.db.database import get_session_factory
from app.errors import SessionNotFoundError
from app.services import session_service

pytestmark = pytest.mark.skipif(
    not get_settings().database_url, reason="DATABASE_URL is not configured"
)


def test_context_describes_itself_without_the_request_text() -> None:
    marker = "private-question-marker"
    context = AgentContext(
        user_message=marker,
        session_id=uuid.uuid4(),
        history=(ConversationTurn(role="user", content="earlier"),),
        llm_mode="ollama",
        capabilities=("transcript_search",),
    )

    described = context.describe()

    assert described["history_turns"] == 1
    assert described["llm_mode"] == "ollama"
    assert described["capabilities"] == ["transcript_search"]
    assert marker not in str(described)


def test_context_requires_a_user_message() -> None:
    with pytest.raises(ValueError):
        AgentContext(user_message="   ")


def test_conversation_turn_rejects_system_and_tool_roles() -> None:
    for role in ("system", "tool", "developer"):
        with pytest.raises(ValueError):
            ConversationTurn(role=role, content="x")

    assert set(CONVERSATION_ROLES) == {"user", "assistant"}


def test_history_is_loaded_from_the_session_only(db_session, created_sessions) -> None:
    session = session_service.create_session(db_session, title="Context test")
    other = session_service.create_session(db_session, title="Other session")
    created_sessions.extend([session.id, other.id])

    session_service.add_message(db_session, session_id=session.id, role="user", content="first question")
    session_service.add_message(db_session, session_id=session.id, role="assistant", content="first answer")
    session_service.add_message(db_session, session_id=session.id, role="system", content="internal note")
    session_service.add_message(db_session, session_id=other.id, role="user", content="other session secret")

    context = AgentContext.from_session(
        db_session, session_id=session.id, user_message="follow-up", llm_mode="ollama"
    )

    assert context.session_id == session.id
    assert [turn.content for turn in context.history] == ["first question", "first answer"]
    assert context.llm_mode == "ollama"
    assert "other session secret" not in str(context.history)


def test_history_is_trimmed_to_the_most_recent_turns(db_session, created_sessions) -> None:
    session = session_service.create_session(db_session, title="History limit")
    created_sessions.append(session.id)
    for index in range(MAX_HISTORY_MESSAGES + 4):
        session_service.add_message(db_session, session_id=session.id, role="user", content=f"message {index}")

    context = AgentContext.from_session(db_session, session_id=session.id, user_message="next")

    assert len(context.history) == MAX_HISTORY_MESSAGES
    assert context.history[-1].content == f"message {MAX_HISTORY_MESSAGES + 3}"


def test_history_limit_can_be_disabled(db_session, created_sessions) -> None:
    session = session_service.create_session(db_session, title="Unlimited history")
    created_sessions.append(session.id)
    session_service.add_message(db_session, session_id=session.id, role="user", content="only one")

    context = AgentContext.from_session(db_session, session_id=session.id, user_message="next", history_limit=0)

    assert [turn.content for turn in context.history] == ["only one"]


def test_unknown_session_is_reported_as_not_found(db_session) -> None:
    with pytest.raises(SessionNotFoundError):
        AgentContext.from_session(db_session, session_id=uuid.uuid4(), user_message="hello")


@pytest.fixture
def db_session():
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
