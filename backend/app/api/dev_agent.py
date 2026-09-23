"""Development-only verification endpoints for the agent layer.

These routes exist to verify the architecture end to end:

    request -> agentic router -> selected capability (skills/tools)
            -> LLM factory -> selected provider -> structured result

They are not the production chat API (that is :mod:`app.api.chat`), they do not
persist messages, and they are not registered at all when
``APP_ENV=production``.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agent.agent import ApplicationAgent, create_application_agent
from app.agent.classifier import LLMIntentClassifier
from app.agent.context import AgentContext
from app.agent.router import AgentRouter
from app.agent.skills import SkillContext
from app.agent.skills.transcript_search import TranscriptSearchTool
from app.agent.tools import default_registry
from app.api.schemas import (
    AgentRespondRequest,
    AgentRespondResponse,
    CapabilitiesResponse,
    CapabilityModel,
    RouteRequest,
    RouteResponse,
    TranscriptSearchRequest,
    TranscriptSearchResponse,
)
from app.config import get_settings
from app.db.database import get_db
from app.llm.base import PROVIDER_ANTHROPIC, PROVIDER_OLLAMA
from app.llm.factory import create_llm_client, normalize_llm_mode

logger = logging.getLogger("lenny.api.agent")

router = APIRouter(
    prefix="/api/dev/agent",
    tags=["dev-agent"],
    responses={"503": {"description": "The configured LLM provider is unavailable or misconfigured"}},
)


@lru_cache
def get_application_agent() -> ApplicationAgent:
    """Build the application agent for the configured LLM mode."""
    return create_application_agent()


@lru_cache
def get_routing_only_agent() -> AgentRouter:
    """Build a router for classification-only checks.

    Classification needs no provider unless LLM-assisted routing is switched on,
    so this is usable even before a provider is configured.
    """
    settings = get_settings()
    registry = default_registry()
    llm_classifier = None
    if settings.llm_router_llm_classification:
        llm_classifier = LLMIntentClassifier(create_llm_client(settings=settings))
    return AgentRouter(registry, llm_classifier=llm_classifier)


@router.get("/capabilities", response_model=CapabilitiesResponse)
def list_capabilities() -> CapabilitiesResponse:
    """List every capability the agent knows about and whether it is implemented."""
    settings = get_settings()
    registry = default_registry()
    return CapabilitiesResponse(
        llm_mode=normalize_llm_mode(settings.llm_mode),
        providers=[PROVIDER_ANTHROPIC, PROVIDER_OLLAMA],
        available_tools=list(registry.available_capabilities()),
        capabilities=[
            CapabilityModel(**descriptor.to_dict()) for descriptor in registry.descriptors()
        ],
    )


@router.post("/route", response_model=RouteResponse)
async def route_request(payload: RouteRequest) -> RouteResponse:
    """Classify a request and report the pathway it maps to, without executing it."""
    routing = get_routing_only_agent()
    context = AgentContext(user_message=payload.message)
    decision = await routing.route(context)
    capability, available = routing.capability_state(decision.intent)
    return RouteResponse(
        intent=decision.intent.value,
        confidence=decision.confidence,
        execution_path=decision.execution_path.value,
        capability=capability,
        capability_available=available,
        classifier=decision.classifier,
        secondary_intents=[intent.value for intent in decision.secondary_intents],
        signals=list(decision.signals),
    )


@router.post("/respond", response_model=AgentRespondResponse)
async def respond(payload: AgentRespondRequest, db: Session = Depends(get_db)) -> AgentRespondResponse:
    """Run one request through the agent and return the structured result.

    When ``session_id`` is given, that session's history is loaded so session
    isolation can be verified. Nothing is written back to the session.
    """
    agent = get_application_agent()
    temporary_agent: ApplicationAgent | None = None
    try:
        if payload.llm_mode is not None and normalize_llm_mode(payload.llm_mode, origin="llm_mode") != agent.llm_mode:
            # Explicit per-request provider selection (the same mechanism the
            # production chat endpoint uses for the LLM toggle).
            temporary_agent = create_application_agent(mode=payload.llm_mode)
            agent = temporary_agent

        if payload.session_id is not None:
            context = AgentContext.from_session(
                db,
                session_id=payload.session_id,
                user_message=payload.message,
                llm_mode=payload.llm_mode,
            )
        else:
            context = AgentContext(user_message=payload.message, llm_mode=payload.llm_mode)

        result = await agent.handle(context, db=db)
        return AgentRespondResponse.model_validate(result.to_dict())
    finally:
        if temporary_agent is not None:
            await temporary_agent.aclose()


@router.post("/search", response_model=TranscriptSearchResponse)
async def search_transcripts(
    payload: TranscriptSearchRequest,
    db: Session = Depends(get_db),
) -> TranscriptSearchResponse:
    """Retrieve transcript chunks through the Phase 4 search capability.

    Retrieval needs no language model, so this route works with the knowledge
    base alone and is what the real-verification script uses to prove the agent
    reaches the ingested transcripts through the registered tool.
    """
    context = SkillContext(request=payload.query, registry=default_registry(), db=db)
    result = await TranscriptSearchTool().run({"query": payload.query, "top_k": payload.top_k}, context)
    return TranscriptSearchResponse(
        query=result.metadata["query"],
        result_count=result.metadata["result_count"],
        results=result.metadata["passages"],
    )
