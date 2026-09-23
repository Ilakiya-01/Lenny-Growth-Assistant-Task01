"""Request and response models for the HTTP API."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str


class SessionCreateRequest(BaseModel):
    user_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=200)


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    artifact: dict | None = None
    created_at: datetime


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]


# ---------------------------------------------------------------------------
# Agent payload models shared by the production chat routes and the
# development verification routes.
# ---------------------------------------------------------------------------


class ActivityModel(BaseModel):
    stage: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class TokenUsageModel(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ArtifactModel(BaseModel):
    """Structured artifact data, kept separate from the assistant's text."""

    type: str
    title: str
    content: str
    css: str | None = None


class SourceModel(BaseModel):
    """Provenance of one retrieved transcript passage."""

    episode_id: str
    title: str | None = None
    guest: str | None = None
    publish_date: str | None = None
    youtube_url: str | None = None
    chunk_index: int | None = None
    similarity: float | None = None
    excerpt: str | None = None


# ---------------------------------------------------------------------------
# Phase 5 - the production chat workflow. The client talks only to these routes;
# provider selection stays in the backend.
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    session_id: uuid.UUID
    message: str = Field(min_length=1, max_length=8000)
    #: Per-request provider selection (the Cloud | Ollama toggle). ``None``
    #: uses the configured ``LLM_MODE``; an unsupported value is a 503.
    llm_mode: str | None = None


class ChatResponse(BaseModel):
    """One completed turn.

    ``message`` is the persisted assistant message and ``user_message`` the
    persisted request, so the client can reconcile what it showed optimistically
    with what the database holds. ``artifact`` is structured data and is never
    embedded in the assistant text.
    """

    session_id: uuid.UUID
    message: MessageResponse
    user_message: MessageResponse
    artifact: ArtifactModel | None = None
    sources: list[SourceModel] = Field(default_factory=list)
    activity: list[ActivityModel] = Field(default_factory=list)
    llm_mode: str
    provider: str
    model: str | None = None
    intent: str
    skills: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Phase 3/4 - development verification of agent routing, providers and skills.
# These back the ``/api/dev/agent`` routes only, which are not registered in
# production; the product chat workflow uses the schemas above.
# ---------------------------------------------------------------------------


class RouteRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class RouteResponse(BaseModel):
    """Structured routing decision. Intentionally free of reasoning or prompts."""

    intent: str
    confidence: float
    execution_path: str
    capability: str | None = None
    capability_available: bool
    classifier: str
    secondary_intents: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)


class AgentRespondRequest(RouteRequest):
    session_id: uuid.UUID | None = None
    llm_mode: str | None = None


class AgentRespondResponse(BaseModel):
    status: str
    intent: str
    confidence: float
    execution_path: str
    capability: str | None = None
    capability_available: bool
    classifier: str
    secondary_intents: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    plan_steps: list[str] = Field(default_factory=list)
    llm_mode: str
    provider: str
    model: str | None = None
    reply: str | None = None
    artifact: ArtifactModel | None = None
    sources: list[SourceModel] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    skills: list[str] = Field(default_factory=list)
    usage: TokenUsageModel | None = None
    notes: list[str] = Field(default_factory=list)
    activity: list[ActivityModel] = Field(default_factory=list)


class TranscriptSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class TranscriptSearchResponse(BaseModel):
    query: str
    result_count: int
    results: list[SourceModel] = Field(default_factory=list)


class CapabilityModel(BaseModel):
    name: str
    description: str
    intents: list[str] = Field(default_factory=list)
    available: bool
    phase: int | None = None


class CapabilitiesResponse(BaseModel):
    llm_mode: str
    providers: list[str]
    available_tools: list[str]
    capabilities: list[CapabilityModel]
