"""Database access for users and chat sessions."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ChatSession, User

DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_SESSION_TITLE = "New Chat"


def get_user(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def ensure_default_user(db: Session) -> User:
    """Return the default user, creating it on first use."""
    user = get_user(db, DEFAULT_USER_ID)
    if user is None:
        user = User(id=DEFAULT_USER_ID, metadata_json={"type": "default"})
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def create_session(db: Session, *, user_id: uuid.UUID | None = None, title: str | None = None) -> ChatSession:
    if user_id is None:
        user_id = ensure_default_user(db).id

    session = ChatSession(user_id=user_id, title=title or DEFAULT_SESSION_TITLE)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def rename_session(db: Session, *, session_id: uuid.UUID, title: str) -> ChatSession | None:
    session = get_session(db, session_id)
    if session is None:
        return None
    session.title = title
    db.commit()
    db.refresh(session)
    return session


def list_sessions(db: Session, *, user_id: uuid.UUID | None = None) -> list[ChatSession]:
    statement = select(ChatSession).order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
    if user_id is not None:
        statement = statement.where(ChatSession.user_id == user_id)
    return list(db.scalars(statement))


def get_session(db: Session, session_id: uuid.UUID) -> ChatSession | None:
    return db.get(ChatSession, session_id)
