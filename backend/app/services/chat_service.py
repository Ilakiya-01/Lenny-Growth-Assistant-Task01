"""The production chat workflow.

One user turn: the request goes through the existing
:class:`~app.agent.agent.ApplicationAgent` (router -> capability -> provider),
then the user message and the assistant reply - with any structured artifact -
are persisted through the Phase 1 session service.

Nothing here re-implements routing, retrieval, skills, provider selection or
persistence, and the client never talks to a provider directly: this module is
the only place the HTTP layer meets the agent.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlalchemy.orm import Session

from app.agent.activity import ActivityReporter
from app.agent.agent import AgentResult, ApplicationAgent, create_application_agent
from app.agent.context import AgentContext
from app.config import get_settings
from app.db.models import ChatSession, Message
from app.db.repositories.session_repository import DEFAULT_SESSION_TITLE
from app.llm.factory import normalize_llm_mode
from app.services import session_service

logger = logging.getLogger("lenny.chat")

#: Capability measurements that are useful in the UI and safe to return. The
#: rest of the capability metadata (retrieved passages, the echoed question,
#: provider usage objects) stays server side.
METRIC_KEYS: tuple[str, ...] = (
    "word_count",
    "target_words",
    "reading_time_minutes",
    "headings",
    "bullets",
    "bold_phrases",
    "has_title",
    "has_takeaway",
    "insufficient_evidence",
    "evidence_count",
    "artifact_type",
    "result_count",
)

#: Session titles are derived from the first user message and kept short enough
#: for the sidebar.
TITLE_MAX_LENGTH = 48


@lru_cache
def get_chat_agent(llm_mode: str) -> ApplicationAgent:
    """Return the process-wide agent for one provider mode.

    The agent (and therefore the provider client) is shared between requests,
    exactly like the development endpoints do, so a chat turn never pays for
    client construction. The mode is resolved by the LLM factory: selecting
    Ollama never silently uses the cloud provider, or the other way round.
    """
    return create_application_agent(mode=llm_mode)


@dataclass(frozen=True, slots=True)
class ChatTurn:
    """Everything one chat turn produced."""

    session_id: uuid.UUID
    user_message: Message
    assistant_message: Message
    result: AgentResult

    @property
    def artifact(self) -> dict[str, Any] | None:
        return self.result.artifact

    def metrics(self) -> dict[str, Any]:
        """The safe subset of capability metadata for the UI."""
        return {
            key: value
            for key, value in self.result.metadata.items()
            if key in METRIC_KEYS and isinstance(value, (str, int, float, bool))
        }


def resolve_llm_mode(llm_mode: str | None) -> str:
    """Canonical provider mode for a request: the requested one, else the config."""
    settings = get_settings()
    return normalize_llm_mode(llm_mode or settings.llm_mode, origin="llm_mode")


async def run_chat_turn(
    db: Session,
    *,
    session_id: uuid.UUID,
    message: str,
    llm_mode: str | None = None,
    reporter: ActivityReporter | None = None,
) -> ChatTurn:
    """Run one request through the agent and persist the resulting turn.

    The messages are written only after the agent succeeds, so a failed turn
    leaves nothing behind: the client keeps the draft and a retry cannot produce
    a duplicated user message in the persisted history.
    """
    session = session_service.get_session_or_raise(db, session_id)
    mode = resolve_llm_mode(llm_mode)
    agent = get_chat_agent(mode)

    context = AgentContext.from_session(db, session_id=session_id, user_message=message, llm_mode=mode)
    result = await agent.handle(context, db=db, reporter=reporter)

    user_row = session_service.add_message(db, session_id=session_id, role="user", content=message)
    assistant_row = session_service.add_message(
        db,
        session_id=session_id,
        role="assistant",
        content=result.reply or "",
        artifact=result.artifact,
    )
    _title_session(db, session, message)
    logger.info(
        "Chat turn completed (session=%s intent=%s skills=%s provider=%s)",
        session_id,
        result.intent.value,
        list(result.skills),
        result.provider,
    )
    return ChatTurn(
        session_id=session_id,
        user_message=user_row,
        assistant_message=assistant_row,
        result=result,
    )


def _title_session(db: Session, session: ChatSession, message: str) -> None:
    """Name an untitled session after its first user message."""
    if session.title and session.title != DEFAULT_SESSION_TITLE:
        return
    title = derive_title(message)
    if title:
        session_service.rename_session(db, session_id=session.id, title=title)


def derive_title(message: str, *, max_length: int = TITLE_MAX_LENGTH) -> str:
    """One-line sidebar title taken from the start of the user's message."""
    collapsed = " ".join((message or "").split())
    if not collapsed:
        return ""
    if len(collapsed) <= max_length:
        return collapsed
    cut = collapsed[:max_length].rstrip()
    # Prefer a word boundary so the sidebar never shows a half-finished word.
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return f"{cut.rstrip()}…"


__all__ = [
    "DEFAULT_SESSION_TITLE",
    "METRIC_KEYS",
    "TITLE_MAX_LENGTH",
    "ChatTurn",
    "derive_title",
    "get_chat_agent",
    "resolve_llm_mode",
    "run_chat_turn",
]
