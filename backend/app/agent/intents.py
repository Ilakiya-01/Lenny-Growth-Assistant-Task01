"""Intents recognized by the application agent and the pathways they select.

The router classifies a request into exactly one primary intent and reports the
execution pathway that intent maps to. Each non-conversational pathway maps to a
capability in the tool registry, which the agent executes when that capability is
available and reports without executing when it is still planned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Intent(str, Enum):
    """The user goal the agent believes it is being asked to satisfy."""

    RAG_QA = "rag_qa"
    SHIP30FOR30 = "ship30for30"
    ARTIFACT_GENERATION = "artifact_generation"
    GENERAL = "general"


class ExecutionPath(str, Enum):
    """The pathway the agent prepares for an intent."""

    TRANSCRIPT_SEARCH = "transcript_search"
    SHIP30FOR30 = "ship30for30"
    ARTIFACT_GENERATION = "artifact_generation"
    DIRECT_RESPONSE = "direct_response"


INTENT_EXECUTION_PATH: dict[Intent, ExecutionPath] = {
    Intent.RAG_QA: ExecutionPath.TRANSCRIPT_SEARCH,
    Intent.SHIP30FOR30: ExecutionPath.SHIP30FOR30,
    Intent.ARTIFACT_GENERATION: ExecutionPath.ARTIFACT_GENERATION,
    Intent.GENERAL: ExecutionPath.DIRECT_RESPONSE,
}

# Capability names as they appear in the tool registry. ``None`` means the
# intent is handled without a specialized capability. A question is answered by
# the grounded Q&A skill, which retrieves through the transcript search tool.
INTENT_CAPABILITY: dict[Intent, str | None] = {
    Intent.RAG_QA: "transcript_qa",
    Intent.SHIP30FOR30: "ship30for30",
    Intent.ARTIFACT_GENERATION: "artifact_generator",
    Intent.GENERAL: None,
}


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Structured result of intent classification.

    ``signals`` carries only short, controlled codes that explain which rules
    fired. No prompt text, model reasoning or chain-of-thought is recorded here.
    """

    intent: Intent
    confidence: float
    execution_path: ExecutionPath
    classifier: str
    signals: tuple[str, ...] = ()
    secondary_intents: tuple[Intent, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "execution_path": self.execution_path.value,
            "classifier": self.classifier,
            "signals": list(self.signals),
            "secondary_intents": [intent.value for intent in self.secondary_intents],
        }


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """What the agent intends to do for a classified request."""

    decision: RoutingDecision
    capability: str | None
    capability_available: bool
    provider: str
    model: str
    llm_mode: str
    steps: tuple[str, ...] = field(default_factory=tuple)

    @property
    def intent(self) -> Intent:
        return self.decision.intent

    @property
    def confidence(self) -> float:
        return self.decision.confidence

    @property
    def classifier(self) -> str:
        return self.decision.classifier

    @property
    def execution_path(self) -> ExecutionPath:
        return self.decision.execution_path

    @property
    def generates_reply(self) -> bool:
        """True only for pathways the agent answers directly without a capability."""
        return self.decision.execution_path is ExecutionPath.DIRECT_RESPONSE and self.capability_available

    @property
    def executable(self) -> bool:
        """True when the pathway's capability is registered and can be invoked."""
        return self.capability is None or self.capability_available

    def to_dict(self) -> dict[str, object]:
        return {
            **self.decision.to_dict(),
            "capability": self.capability,
            "capability_available": self.capability_available,
            "provider": self.provider,
            "model": self.model,
            "llm_mode": self.llm_mode,
            "steps": list(self.steps),
        }


__all__ = [
    "INTENT_CAPABILITY",
    "INTENT_EXECUTION_PATH",
    "ExecutionPath",
    "ExecutionPlan",
    "Intent",
    "RoutingDecision",
]
