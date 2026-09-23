"""Session and message operations."""

import uuid

from sqlalchemy.orm import Session

from app.db.models import ChatSession, Message
from app.db.repositories import message_repository, session_repository
from app.errors import SessionNotFoundError


def create_session(db: Session, *, user_id: uuid.UUID | None = None, title: str | None = None) -> ChatSession:
    return session_repository.create_session(db, user_id=user_id, title=title)


def list_sessions(db: Session, *, user_id: uuid.UUID | None = None) -> list[ChatSession]:
    return session_repository.list_sessions(db, user_id=user_id)


def get_session_or_raise(db: Session, session_id: uuid.UUID) -> ChatSession:
    session = session_repository.get_session(db, session_id)
    if session is None:
        raise SessionNotFoundError(session_id)
    return session


def rename_session(db: Session, *, session_id: uuid.UUID, title: str) -> ChatSession:
    get_session_or_raise(db, session_id)
    renamed = session_repository.rename_session(db, session_id=session_id, title=title)
    if renamed is None:  # pragma: no cover - guarded by get_session_or_raise
        raise SessionNotFoundError(session_id)
    return renamed


def list_messages(db: Session, *, session_id: uuid.UUID) -> list[Message]:
    get_session_or_raise(db, session_id)
    return message_repository.list_messages(db, session_id=session_id)


def add_message(
    db: Session,
    *,
    session_id: uuid.UUID,
    role: str,
    content: str,
    artifact: dict | None = None,
) -> Message:
    """Persist a message for a session.

    Called by the production chat workflow (:mod:`app.services.chat_service`)
    once a turn has completed, and by tests.
    """
    get_session_or_raise(db, session_id)
    return message_repository.add_message(
        db, session_id=session_id, role=role, content=content, artifact=artifact
    )
