"""The agentic router.

The router decides *what kind of request* it is looking at and *which pathway*
that request belongs on. It never executes a capability: for the specialized
pathways it resolves the registered capability and records whether that
capability is available, and the agent executes the plan it returns.

Classification runs through the deterministic heuristic classifier by default.
When LLM-assisted routing is enabled in configuration, requests the heuristic is
not confident about are re-classified by the configured provider; a failure in
that step surfaces as :class:`~app.errors.AgentClassificationError` rather than
being silently replaced with a guess.
"""

from __future__ import annotations

import logging

from app.agent.activity import ActivityReporter, AgentActivityKind
from app.agent.classifier import HeuristicIntentClassifier, LLMIntentClassifier
from app.agent.context import AgentContext
from app.agent.intents import (
    INTENT_CAPABILITY,
    INTENT_EXECUTION_PATH,
    ExecutionPath,
    ExecutionPlan,
    Intent,
    RoutingDecision,
)
from app.agent.tools import ToolRegistry
from app.llm.base import BaseLLMClient

logger = logging.getLogger("lenny.agent.router")

#: Below this heuristic confidence the optional provider classifier is consulted.
LLM_ASSIST_CONFIDENCE_THRESHOLD = 0.6

STEP_CLASSIFY = "classify_intent"
STEP_SELECT_PROVIDER = "select_provider"
STEP_RESOLVE_CAPABILITY = "resolve_capability"
STEP_INVOKE_CAPABILITY = "invoke_capability"
STEP_DIRECT_RESPONSE = "generate_direct_response"


class AgentRouter:
    """Classifies requests and prepares execution pathways."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        classifier: HeuristicIntentClassifier | None = None,
        llm_classifier: LLMIntentClassifier | None = None,
    ) -> None:
        self._registry = registry
        self._classifier = classifier or HeuristicIntentClassifier()
        self._llm_classifier = llm_classifier

    @property
    def uses_llm_classification(self) -> bool:
        return self._llm_classifier is not None

    async def route(self, context: AgentContext, *, reporter: ActivityReporter | None = None) -> RoutingDecision:
        """Classify the request into an intent and its execution pathway."""
        if reporter is not None:
            reporter.emit(
                AgentActivityKind.CLASSIFYING_INTENT,
                detail={"classifier": "llm-assisted" if self.uses_llm_classification else self._classifier.name},
            )

        result = self._classifier.classify(context.user_message)
        if self._llm_classifier is not None and result.confidence < LLM_ASSIST_CONFIDENCE_THRESHOLD:
            logger.info(
                "Heuristic confidence %.2f is below %.2f: asking the configured provider to classify the request",
                result.confidence,
                LLM_ASSIST_CONFIDENCE_THRESHOLD,
            )
            result = await self._llm_classifier.classify(
                context.user_message,
                capabilities=context.capabilities or self._registry.capability_names(),
            )

        decision = RoutingDecision(
            intent=result.intent,
            confidence=result.confidence,
            execution_path=INTENT_EXECUTION_PATH[result.intent],
            classifier=result.classifier,
            signals=result.signals,
            secondary_intents=result.secondary_intents,
        )
        logger.info(
            "Routed request to intent=%s confidence=%.2f path=%s classifier=%s",
            decision.intent.value,
            decision.confidence,
            decision.execution_path.value,
            decision.classifier,
        )
        return decision

    def plan(
        self,
        context: AgentContext,
        decision: RoutingDecision,
        *,
        client: BaseLLMClient,
        llm_mode: str,
    ) -> ExecutionPlan:
        """Resolve the capability for a decision and describe the pathway.

        Availability comes from the registry, so a pathway whose capability is
        not registered is still reported accurately rather than failing later.
        """
        capability = INTENT_CAPABILITY[decision.intent]
        available = capability is None or self._registry.is_available(capability)

        if decision.execution_path is ExecutionPath.DIRECT_RESPONSE:
            steps = (STEP_CLASSIFY, STEP_SELECT_PROVIDER, STEP_DIRECT_RESPONSE)
        else:
            steps = (STEP_CLASSIFY, STEP_SELECT_PROVIDER, STEP_RESOLVE_CAPABILITY, STEP_INVOKE_CAPABILITY)

        return ExecutionPlan(
            decision=decision,
            capability=capability,
            capability_available=available,
            provider=client.provider,
            model=client.model,
            llm_mode=llm_mode,
            steps=steps,
        )

    def capability_state(self, intent: Intent) -> tuple[str | None, bool]:
        """Return the capability name and availability for an intent."""
        capability = INTENT_CAPABILITY[intent]
        return capability, capability is None or self._registry.is_available(capability)


__all__ = [
    "STEP_CLASSIFY",
    "STEP_DIRECT_RESPONSE",
    "STEP_INVOKE_CAPABILITY",
    "STEP_RESOLVE_CAPABILITY",
    "STEP_SELECT_PROVIDER",
    "LLM_ASSIST_CONFIDENCE_THRESHOLD",
    "AgentRouter",
]
