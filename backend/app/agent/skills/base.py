"""Shared pieces for the capabilities the agent can execute.

A capability (tool/skill) receives a :class:`SkillContext` - the provider client,
the registry, the active request and, when the capability needs the knowledge
base, a database session - so a skill never reaches for global state and can be
unit tested with fakes. :class:`EvidenceBundle` is what the transcript search
capability hands to the capabilities that need retrieved transcript passages.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.agent.activity import ActivityReporter
from app.agent.context import AgentContext
from app.agent.tools import ToolRegistry
from app.errors import LLMConfigurationError, TranscriptSearchError
from app.llm.base import BaseLLMClient
from app.rag.retrieval import TranscriptSearchResult

#: Longest excerpt of one retrieved chunk that is placed in a prompt. Chunks are
#: already small; this only guards against an unusually long one.
MAX_EVIDENCE_CHARS = 1400

EVIDENCE_BLOCK_HEADER = "Retrieved transcript evidence:"
EVIDENCE_BLOCK_EMPTY = "No transcript evidence was retrieved."


def evidence_to_dict(result: TranscriptSearchResult) -> dict[str, Any]:
    """Plain, JSON-ready metadata for one retrieved passage.

    The frontend will need this to identify where an insight came from, so the
    episode identity, guest, publish date and link are preserved verbatim.
    """
    return {
        "episode_id": result.episode_id,
        "title": result.title,
        "guest": result.guest,
        "publish_date": result.publish_date.isoformat() if isinstance(result.publish_date, date) else None,
        "youtube_url": result.youtube_url,
        "chunk_index": result.chunk_index,
        "similarity": round(float(result.similarity), 4),
        "excerpt": _excerpt(result.content),
    }


def _excerpt(content: str, *, limit: int = 240) -> str:
    text = " ".join((content or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def format_evidence_block(results: Sequence[TranscriptSearchResult], *, limit: int | None = None) -> str:
    """Render retrieved passages as a numbered, citable evidence block."""
    if not results:
        return EVIDENCE_BLOCK_EMPTY

    lines: list[str] = [EVIDENCE_BLOCK_HEADER]
    for index, result in enumerate(results, start=1):
        title = result.title or result.episode_id
        guest = result.guest or "unknown guest"
        published = result.publish_date.isoformat() if isinstance(result.publish_date, date) else "date unknown"
        content = " ".join((result.content or "").split())[:MAX_EVIDENCE_CHARS]
        lines.append(f"[{index}] {title} - {guest} ({published}), similarity {result.similarity:.3f}")
        lines.append(content)
        if limit is not None and index >= limit:
            break
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """Retrieved transcript passages plus their prompt-ready rendering."""

    passages: tuple[TranscriptSearchResult, ...] = ()
    text: str = EVIDENCE_BLOCK_EMPTY

    @property
    def count(self) -> int:
        return len(self.passages)

    @property
    def has_evidence(self) -> bool:
        return bool(self.passages)

    def sources(self) -> tuple[dict[str, Any], ...]:
        """Structured source metadata for the agent result."""
        return tuple(evidence_to_dict(passage) for passage in self.passages)


@dataclass(slots=True)
class SkillContext:
    """Everything a capability needs in order to run one request."""

    request: str
    registry: ToolRegistry
    client: BaseLLMClient | None = None
    db: Session | None = None
    agent_context: AgentContext | None = None
    reporter: ActivityReporter | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def history(self) -> tuple[Any, ...]:
        return self.agent_context.history if self.agent_context is not None else ()

    def require_client(self) -> BaseLLMClient:
        """Return the provider client, or fail with an actionable error.

        Retrieval needs no model, so the client is optional here; capabilities
        that generate text must ask for it explicitly.
        """
        if self.client is None:
            raise LLMConfigurationError(
                "This capability needs a language model provider and none was supplied.",
                user_message=(
                    "No language model provider is available for this request. "
                    "Check LLM_MODE and the provider variables in the repository root .env file."
                ),
            )
        return self.client

    def require_db(self) -> Session:
        """Return the database session, or fail with an actionable error.

        Knowledge-base capabilities cannot run without one, and a missing session
        is a wiring problem rather than an empty result.
        """
        if self.db is None:
            raise TranscriptSearchError(
                "Transcript retrieval requires a database session.",
                user_message=(
                    "Lenny's transcripts are not reachable for this request because no database session "
                    "was provided. Check DATABASE_URL and try again."
                ),
            )
        return self.db


__all__ = [
    "EVIDENCE_BLOCK_EMPTY",
    "EVIDENCE_BLOCK_HEADER",
    "MAX_EVIDENCE_CHARS",
    "EvidenceBundle",
    "SkillContext",
    "evidence_to_dict",
    "format_evidence_block",
]
