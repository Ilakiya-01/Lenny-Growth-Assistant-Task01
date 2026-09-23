"""Database access for session messages."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ChatSession, Message

VALID_ROLES = ("user", "assistant", "system")


def list_messages(db: Session, *, session_id: uuid.UUID) -> list[Message]:
    statement = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    return list(db.scalars(statement))


def add_message(
    db: Session,
    *,
    session_id: uuid.UUID,
    role: str,
    content: str,
    artifact: dict | None = None,
) -> Message:
    if role not in VALID_ROLES:
        raise ValueError(f"Unsupported message role: {role}")

    message = Message(session_id=session_id, role=role, content=content, artifact=artifact)
    db.add(message)

    session = db.get(ChatSession, session_id)
    if session is not None:
        session.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(message)
    return message
