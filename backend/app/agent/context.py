"""Context passed to the application agent for one request.

The context is assembled by the caller (the API layer today, a future chat
workflow later) and carries everything the agent needs without reaching into the
database itself: the user request, the conversation history of that session, any
retrieved evidence, the provider override for this request, and the capabilities
that may be used. Structured fields are kept empty until the phases that fill
them exist.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.llm.base import LLMMessage
from app.services import session_service

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
CONVERSATION_ROLES = (ROLE_USER, ROLE_ASSISTANT)

#: Upper bound on how many prior messages are carried into the model request.
MAX_HISTORY_MESSAGES = 12


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """One prior message of the active session."""

    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in CONVERSATION_ROLES:
            raise ValueError(f"Unsupported conversation role: {self.role!r}")

    def to_llm_message(self) -> LLMMessage:
        return LLMMessage(role=self.role, content=self.content)


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Everything the agent knows about the current request."""

    user_message: str
    session_id: uuid.UUID | None = None
    history: tuple[ConversationTurn, ...] = ()
    #: Evidence retrieved by the knowledge base. Filled in a later phase; the
    #: Phase 3 router never populates it.
    retrieved_context: tuple[str, ...] = ()
    #: Per-request provider override (the LLM toggle); ``None`` uses LLM_MODE.
    llm_mode: str | None = None
    #: Capability names the caller allows for this request.
    capabilities: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.user_message, str) or not self.user_message.strip():
            raise ValueError("An agent request needs a non-empty user message.")

    @classmethod
    def from_session(
        cls,
        db: Session,
        *,
        session_id: uuid.UUID,
        user_message: str,
        llm_mode: str | None = None,
        capabilities: Sequence[str] = (),
        history_limit: int = MAX_HISTORY_MESSAGES,
    ) -> AgentContext:
        """Load the conversation history of one session.

        Messages are read through the Phase 1 session service, which filters by
        session id in SQL, so another session's history can never leak in.
        """
        messages = session_service.list_messages(db, session_id=session_id)
        turns = [
            ConversationTurn(role=message.role, content=message.content)
            for message in messages
            if message.role in CONVERSATION_ROLES and (message.content or "").strip()
        ]
        if history_limit > 0:
            turns = turns[-history_limit:]
        return cls(
            user_message=user_message,
            session_id=session_id,
            history=tuple(turns),
            llm_mode=llm_mode,
            capabilities=tuple(capabilities),
        )

    def describe(self) -> dict[str, object]:
        """Safe summary for logs and activity events - never the request text."""
        return {
            "session_id": str(self.session_id) if self.session_id else None,
            "history_turns": len(self.history),
            "retrieved_context_items": len(self.retrieved_context),
            "llm_mode": self.llm_mode,
            "capabilities": list(self.capabilities),
        }


__all__ = [
    "CONVERSATION_ROLES",
    "MAX_HISTORY_MESSAGES",
    "ROLE_ASSISTANT",
    "ROLE_USER",
    "AgentContext",
    "ConversationTurn",
]
