"""Session and session-message endpoints."""

import uuid

from fastapi import APIRouter, Body, Depends, status
from sqlalchemy.orm import Session

from app.api.schemas import (
    MessageListResponse,
    MessageResponse,
    SessionCreateRequest,
    SessionListResponse,
    SessionResponse,
)
from app.db.database import get_db
from app.services import session_service

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: SessionCreateRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> SessionResponse:
    session = session_service.create_session(
        db,
        user_id=payload.user_id if payload else None,
        title=payload.title if payload else None,
    )
    return SessionResponse.model_validate(session)


@router.get("", response_model=SessionListResponse)
def list_sessions(
    user_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
) -> SessionListResponse:
    sessions = session_service.list_sessions(db, user_id=user_id)
    return SessionListResponse(sessions=[SessionResponse.model_validate(item) for item in sessions])


@router.get("/{session_id}/messages", response_model=MessageListResponse)
def list_session_messages(
    session_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> MessageListResponse:
    messages = session_service.list_messages(db, session_id=session_id)
    return MessageListResponse(messages=[MessageResponse.model_validate(item) for item in messages])
