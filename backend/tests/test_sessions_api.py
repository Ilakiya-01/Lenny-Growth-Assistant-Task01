"""Integration tests for sessions and messages.

These tests run against the database configured through DATABASE_URL and are
skipped when no database is configured.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.database import get_session_factory
from app.services import session_service

pytestmark = pytest.mark.skipif(
    not get_settings().database_url, reason="DATABASE_URL is not configured"
)


def test_create_session_persists_and_is_listed(client: TestClient, created_sessions: list[uuid.UUID]) -> None:
    response = client.post("/api/sessions", json={})

    assert response.status_code == 201
    body = response.json()
    created_sessions.append(uuid.UUID(body["id"]))

    assert body["title"] == "New Chat"
    assert body["created_at"]
    assert body["updated_at"]

    listing = client.get("/api/sessions")
    assert listing.status_code == 200
    assert body["id"] in [item["id"] for item in listing.json()["sessions"]]


def test_create_session_accepts_a_title(client: TestClient, created_sessions: list[uuid.UUID]) -> None:
    response = client.post("/api/sessions", json={"title": "Product Growth"})

    assert response.status_code == 201
    body = response.json()
    created_sessions.append(uuid.UUID(body["id"]))
    assert body["title"] == "Product Growth"


def test_new_session_has_no_messages(client: TestClient, created_sessions: list[uuid.UUID]) -> None:
    session_id = client.post("/api/sessions", json={}).json()["id"]
    created_sessions.append(uuid.UUID(session_id))

    response = client.get(f"/api/sessions/{session_id}/messages")

    assert response.status_code == 200
    assert response.json() == {"messages": []}


def test_messages_are_persisted_and_retrieved_in_order(
    client: TestClient, created_sessions: list[uuid.UUID]
) -> None:
    session_id = uuid.UUID(client.post("/api/sessions", json={}).json()["id"])
    created_sessions.append(session_id)

    db = get_session_factory()()
    try:
        session_service.add_message(db, session_id=session_id, role="user", content="First question")
        session_service.add_message(db, session_id=session_id, role="assistant", content="First answer")
    finally:
        db.close()

    response = client.get(f"/api/sessions/{session_id}/messages")

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert [message["content"] for message in messages] == ["First question", "First answer"]


def test_messages_are_isolated_per_session(client: TestClient, created_sessions: list[uuid.UUID]) -> None:
    first_id = uuid.UUID(client.post("/api/sessions", json={}).json()["id"])
    second_id = uuid.UUID(client.post("/api/sessions", json={}).json()["id"])
    created_sessions.extend([first_id, second_id])

    db = get_session_factory()()
    try:
        session_service.add_message(db, session_id=first_id, role="user", content="Only for session one")
    finally:
        db.close()

    first_messages = client.get(f"/api/sessions/{first_id}/messages").json()["messages"]
    second_messages = client.get(f"/api/sessions/{second_id}/messages").json()["messages"]

    assert len(first_messages) == 1
    assert second_messages == []


def test_unknown_session_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/sessions/{uuid.uuid4()}/messages")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_invalid_session_id_returns_422(client: TestClient) -> None:
    response = client.get("/api/sessions/not-a-uuid/messages")

    assert response.status_code == 422
