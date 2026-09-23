"""The application agent.

This is the runtime agent of the product (not the development coding agent that
built the repository). It receives a request with its context, classifies it
through the router, selects the configured provider, prepares the execution
pathway and executes the capability that pathway resolves to.

Execution is deliberately thin. The router decides *which* capability a request
belongs to, the registry owns *what* that capability is, and the capability
itself owns its prompt and its output - the agent only sequences them. The two
composition steps below are the only orchestration rules in this phase: gather
transcript evidence for a request that needs it, and wrap a generated article in
an artifact when the request asked for both. Anything a capability reports is
either prose or structured data; model reasoning is never read, stored or
returned.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.agent.activity import ActivityReporter, AgentActivity, AgentActivityKind
from app.agent.classifier import LLMIntentClassifier, references_lenny_sources
from app.agent.context import AgentContext
from app.agent.intents import ExecutionPath, ExecutionPlan, Intent
from app.agent.prompts import BASE_SYSTEM_PROMPT
from app.agent.router import AgentRouter
from app.agent.runtimes import (
    AgentRunOutput,
    AgentRuntime,
    ClaudeAgentRuntime,
    ProviderAgentRuntime,
)
from app.agent.skills import ArtifactSkill, EvidenceBundle, SkillContext
from app.agent.skills.artifacts import ARTIFACT_TOOL_NAME, ARTIFACT_TYPE_MARKDOWN, build_wrapped_artifact
from app.agent.skills.transcript_search import SEARCH_TOOL_NAME, gather_evidence
from app.agent.tools import ToolRegistry, default_registry
from app.config import Settings, get_settings
from app.errors import AgentConfigurationError, AgentError, LLMError
from app.llm.base import BaseLLMClient, LLMUsage
from app.llm.factory import create_llm_client, normalize_llm_mode

logger = logging.getLogger("lenny.agent")

AGENT_NAME = "application-agent"

STATUS_COMPLETED = "completed"
STATUS_PATHWAY_PREPARED = "pathway_prepared"

AgentStatus = Literal["completed", "pathway_prepared"]

PATHWAY_PREPARED_NOTE = (
    "The routing pathway was prepared but not executed: this capability is implemented in a "
    "later phase, so no capability output was generated and no transcript evidence was retrieved."
)
DIRECT_RESPONSE_NOTE = "The request was answered directly by the configured LLM provider."
CAPABILITY_EXECUTED_NOTE = "The request was handled by the capability the router selected."
EVIDENCE_COMPOSITION_NOTE = (
    "Transcript evidence was retrieved from Lenny's Podcast and used to ground the capability's output."
)
ARTIFACT_COMPOSITION_NOTE = (
    "The artifact was built from the output of the capability the router selected."
)


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Structured outcome of one agent invocation."""

    status: AgentStatus
    intent: Intent
    confidence: float
    execution_path: ExecutionPath
    capability: str | None
    capability_available: bool
    llm_mode: str
    provider: str
    model: str | None
    classifier: str
    plan_steps: tuple[str, ...] = ()
    secondary_intents: tuple[Intent, ...] = ()
    signals: tuple[str, ...] = ()
    reply: str | None = None
    #: Structured artifact (``type``/``title``/``content``/``css``), separate from
    #: ``reply`` so the artifact body is never mixed into assistant prose.
    artifact: dict[str, Any] | None = None
    #: Episode/guest metadata for the retrieved passages the output was based on.
    sources: tuple[dict[str, Any], ...] = ()
    #: Capability-specific measurements (word count, reading time, artifact type).
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Capabilities that ran, in order. More than one means a composed response.
    skills: tuple[str, ...] = ()
    usage: LLMUsage | None = None
    notes: tuple[str, ...] = ()
    activity: tuple[AgentActivity, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        """JSON-ready payload. Contains no prompts, reasoning or credentials."""
        return {
            "status": self.status,
            "intent": self.intent.value,
            "confidence": self.confidence,
            "execution_path": self.execution_path.value,
            "capability": self.capability,
            "capability_available": self.capability_available,
            "classifier": self.classifier,
            "secondary_intents": [intent.value for intent in self.secondary_intents],
            "signals": list(self.signals),
            "plan_steps": list(self.plan_steps),
            "llm_mode": self.llm_mode,
            "provider": self.provider,
            "model": self.model,
            "reply": self.reply,
            "artifact": self.artifact,
            "sources": [dict(source) for source in self.sources],
            "metadata": dict(self.metadata),
            "skills": list(self.skills),
            "usage": self.usage.to_dict() if self.usage else None,
            "notes": list(self.notes),
            "activity": [event.to_dict() for event in self.activity],
        }


@dataclass(frozen=True, slots=True)
class CapabilityExecution:
    """What executing one routed capability produced."""

    reply: str | None
    artifact: dict[str, Any] | None
    sources: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]
    skills: tuple[str, ...]
    notes: tuple[str, ...]
    usage: LLMUsage | None = None
    provider: str | None = None
    model: str | None = None


class ApplicationAgent:
    """Orchestrates classification, provider selection and pathway preparation."""

    def __init__(
        self,
        *,
        client: BaseLLMClient,
        llm_mode: str,
        router: AgentRouter | None = None,
        registry: ToolRegistry | None = None,
        runtimes: dict[str, AgentRuntime] | None = None,
    ) -> None:
        self._client = client
        self._llm_mode = normalize_llm_mode(llm_mode)
        self._registry = registry or default_registry()
        self._router = router or AgentRouter(self._registry)
        # Runtimes are keyed by LLM mode, so the provider mode alone decides which
        # runtime executes a prepared plan.
        self._runtimes = runtimes or {self._llm_mode: ProviderAgentRuntime(client)}

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def router(self) -> AgentRouter:
        return self._router

    @property
    def llm_mode(self) -> str:
        return self._llm_mode

    @property
    def client(self) -> BaseLLMClient:
        return self._client

    async def handle(
        self,
        context: AgentContext,
        *,
        session_id: uuid.UUID | None = None,
        reporter: ActivityReporter | None = None,
        db: Session | None = None,
    ) -> AgentResult:
        """Run one request through the agent.

        ``db`` is the database session the knowledge-base capabilities retrieve
        through; it is only required for pathways that read the transcripts.
        """
        activity = reporter or ActivityReporter()
        resolved_session = session_id if session_id is not None else context.session_id
        activity.emit(
            AgentActivityKind.PREPARING_REQUEST,
            detail={"session_id": str(resolved_session) if resolved_session else None, "llm_mode": self._llm_mode},
        )

        try:
            decision = await self._router.route(context, reporter=activity)
            activity.emit(
                AgentActivityKind.SELECTING_PROVIDER,
                detail={"provider": self._client.provider, "model": self._client.model, "llm_mode": self._llm_mode},
            )
            plan = self._router.plan(context, decision, client=self._client, llm_mode=self._llm_mode)
            activity.emit(
                AgentActivityKind.PREPARING_PATHWAY,
                detail={
                    "intent": plan.intent.value,
                    "confidence": plan.confidence,
                    "execution_path": plan.execution_path.value,
                    "capability": plan.capability,
                    "capability_available": plan.capability_available,
                },
            )

            output: AgentRunOutput | None = None
            execution: CapabilityExecution | None = None
            notes: tuple[str, ...] = ()
            status: AgentStatus = STATUS_PATHWAY_PREPARED

            if plan.generates_reply:
                activity.emit(AgentActivityKind.GENERATING_RESPONSE)
                output = await self._runtime_for(self._llm_mode).complete(
                    context=context, system_prompt=BASE_SYSTEM_PROMPT
                )
                status = STATUS_COMPLETED
                notes = (DIRECT_RESPONSE_NOTE,)
            elif plan.executable:
                execution = await self._execute_capability(
                    context=context, plan=plan, db=db, reporter=activity
                )
                status = STATUS_COMPLETED
                notes = execution.notes
            else:
                notes = (PATHWAY_PREPARED_NOTE,)
                logger.info(
                    "Pathway '%s' prepared for intent '%s' but not executed (capability available=%s)",
                    plan.execution_path.value,
                    plan.intent.value,
                    plan.capability_available,
                )
        except (LLMError, AgentError) as exc:
            activity.emit(AgentActivityKind.FAILED, detail={"status": error_category(exc)})
            logger.warning("Agent request failed (%s): %s", error_category(exc), getattr(exc, "detail", exc))
            raise

        activity.emit(AgentActivityKind.COMPLETED, detail={"status": status})
        return AgentResult(
            status=status,
            intent=plan.intent,
            confidence=plan.confidence,
            execution_path=plan.execution_path,
            capability=plan.capability,
            capability_available=plan.capability_available,
            llm_mode=plan.llm_mode,
            provider=_resolved(output, execution, "provider") or plan.provider,
            model=_resolved(output, execution, "model") or plan.model,
            classifier=plan.decision.classifier,
            plan_steps=plan.steps,
            secondary_intents=plan.decision.secondary_intents,
            signals=plan.decision.signals,
            reply=output.reply if output else (execution.reply if execution else None),
            artifact=execution.artifact if execution else None,
            sources=execution.sources if execution else (),
            metadata=execution.metadata if execution else {},
            skills=execution.skills if execution else (),
            usage=(output.usage if output else None) or (execution.usage if execution else None),
            notes=notes,
            activity=activity.events,
        )

    async def _execute_capability(
        self,
        *,
        context: AgentContext,
        plan: ExecutionPlan,
        db: Session | None,
        reporter: ActivityReporter,
    ) -> CapabilityExecution:
        """Invoke the routed capability, including the supported compositions.

        Composition stays explicit rather than being a planner: a request whose
        secondary intent asks about Lenny's Podcast gets transcript evidence
        retrieved first, and an essay request that also asks for an artifact gets
        the finished essay wrapped in one. Both extra capabilities come from the
        registry, so nothing here depends on capability internals.
        """
        capability = plan.capability
        tool = self._registry.tool(capability) if capability else None
        if tool is None:
            raise AgentConfigurationError(
                f"The router selected capability '{capability}' but it is not registered.",
            )

        skill_context = SkillContext(
            request=context.user_message,
            client=self._client,
            registry=self._registry,
            db=db,
            agent_context=context,
            reporter=reporter,
        )

        evidence = await self._gather_evidence_if_needed(context, plan, skill_context)

        reporter.emit(
            AgentActivityKind.EXECUTING_CAPABILITY,
            detail={
                "capability": tool.name,
                "intent": plan.intent.value,
                "execution_path": plan.execution_path.value,
                "evidence_count": evidence.count if evidence else 0,
            },
        )
        result = await tool.run(self._capability_arguments(plan, evidence), skill_context)

        skills: list[str] = [tool.name]
        notes: list[str] = []
        if evidence is not None:
            notes.append(EVIDENCE_COMPOSITION_NOTE)
        else:
            notes.append(CAPABILITY_EXECUTED_NOTE)

        artifact = result.metadata.get("artifact")
        if artifact is None and self._should_wrap_in_artifact(plan):
            artifact = self._compose_artifact(result.content, reporter)
            if artifact is not None:
                skills.append(ARTIFACT_TOOL_NAME)
                notes.append(ARTIFACT_COMPOSITION_NOTE)

        sources = _as_sources(result.metadata.get("sources")) or (
            evidence.sources() if evidence is not None else ()
        )
        metadata = _json_safe_metadata(result.metadata)
        if artifact is not None:
            metadata.setdefault("artifact_type", artifact.get("type"))
            metadata.setdefault("artifact_title", artifact.get("title"))

        usage = result.metadata.get("usage")
        return CapabilityExecution(
            reply=_capability_reply(plan, result.content, artifact),
            artifact=artifact if isinstance(artifact, dict) else None,
            sources=sources,
            metadata=metadata,
            skills=tuple(skills),
            notes=tuple(notes),
            usage=usage if isinstance(usage, LLMUsage) else None,
            provider=_as_text(result.metadata.get("provider")),
            model=_as_text(result.metadata.get("model")),
        )

    async def _gather_evidence_if_needed(
        self,
        context: AgentContext,
        plan: ExecutionPlan,
        skill_context: SkillContext,
    ) -> EvidenceBundle | None:
        """Retrieve transcript evidence for capabilities that need grounding.

        The grounded Q&A skill retrieves for itself; every other capability gets
        the evidence handed to it when the request asked for Lenny-specific
        material (a secondary RAG intent or an explicit reference to the podcast).
        """
        if plan.intent is Intent.RAG_QA:
            return None
        needs_evidence = (
            Intent.RAG_QA in plan.decision.secondary_intents
            or references_lenny_sources(context.user_message)
        )
        if not needs_evidence or self._registry.tool(SEARCH_TOOL_NAME) is None:
            return None
        return await gather_evidence(skill_context, context.user_message)

    def _capability_arguments(self, plan: ExecutionPlan, evidence: EvidenceBundle | None) -> dict[str, Any]:
        """Argument bag for the routed capability.

        Only retrieved evidence is passed across: the request itself always comes
        from the skill context, so a capability never depends on the agent's
        wording of its arguments.
        """
        if evidence is None:
            return {}
        return {"evidence": evidence}

    def _should_wrap_in_artifact(self, plan: ExecutionPlan) -> bool:
        """Wrap a finished article in an artifact when the request asked for both."""
        return (
            plan.intent is Intent.SHIP30FOR30
            and Intent.ARTIFACT_GENERATION in plan.decision.secondary_intents
            and self._registry.is_available(ARTIFACT_TOOL_NAME)
        )

    def _compose_artifact(
        self,
        source_output: str,
        reporter: ActivityReporter,
    ) -> dict[str, Any] | None:
        """Build a markdown artifact from another capability's output.

        The artifact skill is registered (the caller checks that), but the wrap
        itself is deterministic: the document already exists, so re-generating it
        through a model would only risk truncating or altering it.
        """
        reporter.emit(
            AgentActivityKind.GENERATING_ARTIFACT,
            detail={"capability": ARTIFACT_TOOL_NAME, "artifact_type": ARTIFACT_TYPE_MARKDOWN},
        )
        return build_wrapped_artifact(source_output).to_dict()

    def _runtime_for(self, llm_mode: str) -> AgentRuntime:
        runtime = self._runtimes.get(llm_mode)
        if runtime is None:
            raise AgentConfigurationError(
                f"No agent runtime is registered for LLM mode '{llm_mode}'.",
            )
        return runtime

    async def aclose(self) -> None:
        """Release the underlying provider client."""
        await self._client.aclose()


def create_application_agent(
    *,
    settings: Settings | None = None,
    client: BaseLLMClient | None = None,
    mode: str | None = None,
    registry: ToolRegistry | None = None,
) -> ApplicationAgent:
    """Build the agent for the configured (or requested) provider mode.

    The provider is resolved through the LLM factory. Cloud mode uses the Claude
    Agent SDK runtime; local mode uses the shared provider client. The provider
    selection never changes the skill/tool architecture.
    """
    settings = settings or get_settings()
    resolved_mode = normalize_llm_mode(mode if mode is not None else settings.llm_mode)
    llm_client = client or create_llm_client(settings=settings, mode=resolved_mode)
    tool_registry = registry or default_registry()

    llm_classifier = None
    if settings.llm_router_llm_classification:
        llm_classifier = LLMIntentClassifier(llm_client)
        logger.info("LLM-assisted routing is enabled: low-confidence requests are classified by the provider")

    router = AgentRouter(tool_registry, llm_classifier=llm_classifier)

    if resolved_mode == "cloud":
        runtimes: dict[str, AgentRuntime] = {
            "cloud": ClaudeAgentRuntime(
                model=settings.anthropic_model,
                api_key=settings.anthropic_api_key,
            )
        }
    else:
        runtimes = {resolved_mode: ProviderAgentRuntime(llm_client)}

    return ApplicationAgent(
        client=llm_client,
        llm_mode=resolved_mode,
        router=router,
        registry=tool_registry,
        runtimes=runtimes,
    )


#: Coarse, user-safe error categories used in activity events.
ERROR_CATEGORIES: dict[str, str] = {
    "LLMConfigurationError": "llm_configuration",
    "LLMTimeoutError": "llm_timeout",
    "LLMUnavailableError": "llm_unavailable",
    "LLMModelUnavailableError": "llm_model_unavailable",
    "LLMResponseError": "llm_response",
    "AgentConfigurationError": "agent_configuration",
    "AgentClassificationError": "agent_classification",
    "TranscriptSearchError": "transcript_search",
    "ArtifactGenerationError": "artifact_generation",
    "AgentCapabilityError": "capability",
}


def error_category(exc: BaseException) -> str:
    """Map an exception to a short category safe to show as activity status."""
    for klass in type(exc).__mro__:
        category = ERROR_CATEGORIES.get(klass.__name__)
        if category:
            return category
    return "unexpected"


def _resolved(output: AgentRunOutput | None, execution: CapabilityExecution | None, field_name: str) -> str | None:
    value = getattr(output, field_name, None) if output is not None else None
    if value:
        return value
    return getattr(execution, field_name, None) if execution is not None else None


def _as_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _as_sources(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _json_safe_metadata(values: dict[str, Any]) -> dict[str, Any]:
    """Keep only the capability metadata that can be returned as JSON.

    Internal objects (token usage, retrieved rows) never reach the API payload;
    scalars, strings, nested dictionaries and lists of simple values do.
    """
    safe: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, dict):
            safe[key] = value
        elif isinstance(value, (list, tuple)) and all(
            isinstance(item, dict) or isinstance(item, (str, int, float, bool)) or item is None for item in value
        ):
            safe[key] = list(value)
    return safe


def _capability_reply(plan: ExecutionPlan, content: str, artifact: dict[str, Any] | None) -> str:
    """The assistant text for an executed capability.

    An artifact keeps its own body out of the reply: the user-facing text is a
    short, deterministic confirmation, and the artifact travels as structured
    data beside it.
    """
    if artifact is not None and plan.intent is Intent.ARTIFACT_GENERATION:
        title = str(artifact.get("title") or "artifact")
        kind = str(artifact.get("type") or "artifact")
        return f"I generated a {kind} artifact titled '{title}'. It is available as structured artifact data."
    return content


__all__ = [
    "AGENT_NAME",
    "ARTIFACT_COMPOSITION_NOTE",
    "CAPABILITY_EXECUTED_NOTE",
    "DIRECT_RESPONSE_NOTE",
    "EVIDENCE_COMPOSITION_NOTE",
    "ERROR_CATEGORIES",
    "PATHWAY_PREPARED_NOTE",
    "STATUS_COMPLETED",
    "STATUS_PATHWAY_PREPARED",
    "AgentResult",
    "AgentStatus",
    "ApplicationAgent",
    "CapabilityExecution",
    "create_application_agent",
    "error_category",
]
