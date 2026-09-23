"""High-level agent activity events.

These events are what a future UI may show while a request is in flight
("Classifying request", "Using the configured LLM"). They are safe by
construction: the event kinds are a closed set, messages are fixed strings owned
by the agent, and ``detail`` values are restricted to an allow-list of
non-sensitive keys. Prompts, model reasoning, tool arguments, credentials and
internal traces must never be placed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

#: Detail keys that may accompany an activity event. Anything else raises.
ALLOWED_DETAIL_KEYS: frozenset[str] = frozenset(
    {
        "artifact_type",
        "capability",
        "capability_available",
        "classifier",
        "confidence",
        "duration_ms",
        "evidence_count",
        "execution_path",
        "intent",
        "llm_mode",
        "model",
        "provider",
        "session_id",
        "skills",
        "status",
        "turns",
        "words",
    }
)

MAX_DETAIL_VALUE_LENGTH = 120


class AgentActivityKind(str, Enum):
    """Stage of a request, in the order the agent emits them."""

    PREPARING_REQUEST = "preparing_request"
    CLASSIFYING_INTENT = "classifying_intent"
    SELECTING_PROVIDER = "selecting_provider"
    PREPARING_PATHWAY = "preparing_pathway"
    RETRIEVING_EVIDENCE = "retrieving_evidence"
    EXECUTING_CAPABILITY = "executing_capability"
    GENERATING_RESPONSE = "generating_response"
    GENERATING_ARTIFACT = "generating_artifact"
    COMPLETED = "completed"
    FAILED = "failed"


#: User-facing wording for each stage. Fixed text - never interpolated with
#: prompts, model output or configuration values.
ACTIVITY_MESSAGES: dict[AgentActivityKind, str] = {
    AgentActivityKind.PREPARING_REQUEST: "Preparing request",
    AgentActivityKind.CLASSIFYING_INTENT: "Classifying request",
    AgentActivityKind.SELECTING_PROVIDER: "Selecting the configured LLM",
    AgentActivityKind.PREPARING_PATHWAY: "Preparing execution pathway",
    AgentActivityKind.RETRIEVING_EVIDENCE: "Searching Lenny's transcripts",
    AgentActivityKind.EXECUTING_CAPABILITY: "Running the selected capability",
    AgentActivityKind.GENERATING_RESPONSE: "Generating response",
    AgentActivityKind.GENERATING_ARTIFACT: "Generating artifact",
    AgentActivityKind.COMPLETED: "Finished",
    AgentActivityKind.FAILED: "Request failed",
}

DetailValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class AgentActivity:
    """One high-level status update."""

    kind: AgentActivityKind
    message: str
    detail: dict[str, DetailValue] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.kind.value,
            "message": self.message,
            "detail": dict(self.detail),
            "created_at": self.created_at.isoformat(),
        }


class ActivityReporter:
    """Collects activity events for one agent invocation."""

    def __init__(self) -> None:
        self._events: list[AgentActivity] = []

    def emit(
        self,
        kind: AgentActivityKind,
        *,
        detail: dict[str, DetailValue] | None = None,
    ) -> AgentActivity:
        event = AgentActivity(
            kind=kind,
            message=ACTIVITY_MESSAGES[kind],
            detail=_validate_detail(detail or {}),
        )
        self._events.append(event)
        return event

    @property
    def events(self) -> tuple[AgentActivity, ...]:
        return tuple(self._events)

    def to_dicts(self) -> list[dict[str, object]]:
        return [event.to_dict() for event in self._events]


def _validate_detail(detail: dict[str, DetailValue]) -> dict[str, DetailValue]:
    unknown = sorted(set(detail) - ALLOWED_DETAIL_KEYS)
    if unknown:
        raise ValueError(
            "Unsupported agent activity detail key(s): "
            f"{', '.join(unknown)}. Activity detail is restricted to non-sensitive values."
        )
    for key, value in detail.items():
        if isinstance(value, str) and len(value) > MAX_DETAIL_VALUE_LENGTH:
            raise ValueError(f"Agent activity detail '{key}' is too long to be a safe status value.")
    return dict(detail)


__all__ = [
    "ACTIVITY_MESSAGES",
    "ALLOWED_DETAIL_KEYS",
    "ActivityReporter",
    "AgentActivity",
    "AgentActivityKind",
]
