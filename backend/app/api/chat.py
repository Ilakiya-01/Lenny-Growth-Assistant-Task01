"""The production chat endpoints.

``POST /api/chat`` returns one complete turn as JSON. ``POST /api/chat/stream``
returns the same turn as Server-Sent Events, so the workspace can show the
agent's high-level activity while a slow local model is still working.

Both routes run :func:`app.services.chat_service.run_chat_turn`; there is one
chat workflow, not a second one for the frontend. The stream carries structured
events only - an artifact arrives as its own ``artifact_ready`` payload and is
never embedded in assistant text for the client to parse back out.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agent.activity import ActivityReporter, AgentActivity, AgentActivityKind
from app.agent.agent import error_category
from app.api.schemas import (
    ActivityModel,
    ArtifactModel,
    ChatRequest,
    ChatResponse,
    MessageResponse,
    SourceModel,
)
from app.db.database import get_db, get_session_factory
from app.errors import http_status_for, user_message_for
from app.services.chat_service import ChatTurn, run_chat_turn

logger = logging.getLogger("lenny.api.chat")

router = APIRouter(prefix="/api", tags=["chat"])

#: SSE event names. There is no ``token`` event: the skills generate through the
#: provider's non-streaming call, so partial tokens do not exist to forward and
#: inventing them would only fake progress. The finished assistant text travels
#: inside ``done``.
EVENT_ACTIVITY = "activity"
EVENT_ARTIFACT_READY = "artifact_ready"
EVENT_DONE = "done"
EVENT_ERROR = "error"

STREAM_HEADERS = {
    "Cache-Control": "no-store, no-transform",
    "Connection": "keep-alive",
    # Proxies must not hold events back: the whole point is progressive activity.
    "X-Accel-Buffering": "no",
}


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    """Run one turn through the application agent and persist it."""
    return response_body(await _run(db, payload))


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    """The same turn as progressive events.

    A failure inside a stream cannot reach the exception handlers (the response
    has already started), so errors are reported as an ``error`` event carrying
    the same client-safe detail and status the JSON route would have returned.
    """
    return StreamingResponse(stream_events(payload), media_type="text/event-stream", headers=STREAM_HEADERS)


async def _run(db: Session, payload: ChatRequest, reporter: ActivityReporter | None = None) -> ChatTurn:
    return await run_chat_turn(
        db,
        session_id=payload.session_id,
        message=payload.message,
        llm_mode=payload.llm_mode,
        reporter=reporter,
    )


class StreamingActivityReporter(ActivityReporter):
    """Collects activity like the default reporter and publishes it as it happens.

    Only the fixed, allow-listed activity events are published: no prompts, no
    model reasoning, no tool arguments.
    """

    def __init__(self, queue: asyncio.Queue[tuple[str, Any]]) -> None:
        super().__init__()
        self._queue = queue

    def emit(
        self,
        kind: AgentActivityKind,
        *,
        detail: dict[str, Any] | None = None,
    ) -> AgentActivity:
        event = super().emit(kind, detail=detail)
        self._queue.put_nowait((EVENT_ACTIVITY, event.to_dict()))
        return event


async def stream_events(payload: ChatRequest) -> AsyncIterator[str]:
    """Yield the SSE frames of one chat turn."""
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
    task: asyncio.Task[None] | None = None
    db: Session | None = None
    try:
        # The database session is owned here rather than injected: FastAPI closes
        # request dependencies before a streaming body runs.
        db = get_session_factory()()
        task = asyncio.create_task(_run_into_queue(db, payload, queue))
        while True:
            name, value = await queue.get()
            if name == EVENT_DONE:
                turn: ChatTurn = value
                if turn.artifact is not None:
                    yield _frame(EVENT_ARTIFACT_READY, ArtifactModel.model_validate(turn.artifact).model_dump())
                yield _frame(EVENT_DONE, response_body(turn).model_dump(mode="json"))
                return
            if name == EVENT_ERROR:
                yield _frame(EVENT_ERROR, error_payload(value))
                return
            yield _frame(EVENT_ACTIVITY, value)
    except Exception as exc:  # noqa: BLE001 - a stream reports any failure as an error event
        logger.error("Chat stream failed: %s", exc)
        yield _frame(EVENT_ERROR, error_payload(exc))
    finally:
        if task is not None and not task.done():
            task.cancel()
        if db is not None:
            db.close()


async def _run_into_queue(db: Session, payload: ChatRequest, queue: asyncio.Queue[tuple[str, Any]]) -> None:
    reporter = StreamingActivityReporter(queue)
    try:
        turn = await _run(db, payload, reporter=reporter)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - forwarded to the client as an error event
        logger.warning("Chat turn failed (%s): %s", error_category(exc), getattr(exc, "detail", exc))
        queue.put_nowait((EVENT_ERROR, exc))
        return
    queue.put_nowait((EVENT_DONE, turn))


def response_body(turn: ChatTurn) -> ChatResponse:
    """Client payload for one completed turn."""
    result = turn.result
    return ChatResponse(
        session_id=turn.session_id,
        message=MessageResponse.model_validate(turn.assistant_message),
        user_message=MessageResponse.model_validate(turn.user_message),
        artifact=ArtifactModel.model_validate(turn.artifact) if turn.artifact is not None else None,
        sources=[SourceModel.model_validate(source) for source in result.sources],
        activity=[ActivityModel.model_validate(event.to_dict()) for event in result.activity],
        llm_mode=result.llm_mode,
        provider=result.provider,
        model=result.model,
        intent=result.intent.value,
        skills=list(result.skills),
        metrics=turn.metrics(),
    )


def error_payload(exc: BaseException) -> dict[str, Any]:
    """Client-safe error event body. Never a stack trace or a driver message."""
    return {
        "detail": user_message_for(exc),
        "status": http_status_for(exc),
        "category": error_category(exc),
    }


def _frame(event: str, data: dict[str, Any]) -> str:
    # ``json.dumps`` escapes newlines, so one event is always exactly two lines.
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


__all__ = [
    "EVENT_ACTIVITY",
    "EVENT_ARTIFACT_READY",
    "EVENT_DONE",
    "EVENT_ERROR",
    "STREAM_HEADERS",
    "StreamingActivityReporter",
    "chat",
    "chat_stream",
    "error_payload",
    "response_body",
    "router",
    "stream_events",
]
