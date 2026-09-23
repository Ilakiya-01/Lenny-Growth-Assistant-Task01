"""Activity/status event tests.

Activity events are the only thing the agent tells the outside world while a
request is in flight, so this module checks both the wording and the guarantee
that nothing sensitive can be attached to an event.
"""

from __future__ import annotations

import pytest

from app.agent.activity import (
    ACTIVITY_MESSAGES,
    ALLOWED_DETAIL_KEYS,
    MAX_DETAIL_VALUE_LENGTH,
    ActivityReporter,
    AgentActivityKind,
)


def test_every_stage_has_fixed_user_facing_wording() -> None:
    for kind in AgentActivityKind:
        assert ACTIVITY_MESSAGES[kind].strip()

    assert ACTIVITY_MESSAGES[AgentActivityKind.PREPARING_REQUEST] == "Preparing request"
    assert ACTIVITY_MESSAGES[AgentActivityKind.CLASSIFYING_INTENT] == "Classifying request"
    assert ACTIVITY_MESSAGES[AgentActivityKind.SELECTING_PROVIDER] == "Selecting the configured LLM"
    assert ACTIVITY_MESSAGES[AgentActivityKind.PREPARING_PATHWAY] == "Preparing execution pathway"


def test_reporter_records_events_in_order() -> None:
    reporter = ActivityReporter()
    reporter.emit(AgentActivityKind.PREPARING_REQUEST)
    reporter.emit(AgentActivityKind.CLASSIFYING_INTENT, detail={"session_id": "abc"})
    reporter.emit(AgentActivityKind.COMPLETED, detail={"intent": "general", "duration_ms": 12})

    kinds = [event.kind for event in reporter.events]
    assert kinds == [
        AgentActivityKind.PREPARING_REQUEST,
        AgentActivityKind.CLASSIFYING_INTENT,
        AgentActivityKind.COMPLETED,
    ]
    assert reporter.events[1].message == "Classifying request"
    assert reporter.events[1].detail == {"session_id": "abc"}


def test_events_serialize_to_plain_data() -> None:
    reporter = ActivityReporter()
    event = reporter.emit(
        AgentActivityKind.PREPARING_PATHWAY,
        detail={"intent": "rag_qa", "execution_path": "transcript_search", "capability_available": False},
    )
    payload = event.to_dict()

    assert set(payload) == {"stage", "message", "detail", "created_at"}
    assert payload["stage"] == "preparing_pathway"
    assert payload["message"] == "Preparing execution pathway"
    assert payload["detail"]["capability_available"] is False
    assert isinstance(payload["created_at"], str)


def test_to_dicts_returns_one_dict_per_event() -> None:
    reporter = ActivityReporter()
    reporter.emit(AgentActivityKind.PREPARING_REQUEST)
    reporter.emit(AgentActivityKind.COMPLETED)

    payloads = reporter.to_dicts()
    assert len(payloads) == 2
    assert [payload["stage"] for payload in payloads] == ["preparing_request", "completed"]


@pytest.mark.parametrize(
    "key",
    ["prompt", "reasoning", "chain_of_thought", "api_key", "tool_arguments", "system_prompt", "stack_trace", "user_message"],
)
def test_sensitive_detail_keys_are_rejected(key) -> None:
    reporter = ActivityReporter()

    with pytest.raises(ValueError):
        reporter.emit(AgentActivityKind.CLASSIFYING_INTENT, detail={key: "anything"})

    assert reporter.events == ()


def test_only_allow_listed_detail_keys_are_accepted() -> None:
    reporter = ActivityReporter()
    detail = {key: "x" for key in sorted(ALLOWED_DETAIL_KEYS)}

    event = reporter.emit(AgentActivityKind.COMPLETED, detail=detail)
    assert set(event.detail) == ALLOWED_DETAIL_KEYS


def test_over_long_detail_values_are_rejected() -> None:
    reporter = ActivityReporter()

    with pytest.raises(ValueError):
        reporter.emit(AgentActivityKind.COMPLETED, detail={"status": "x" * (MAX_DETAIL_VALUE_LENGTH + 1)})

    reporter.emit(AgentActivityKind.COMPLETED, detail={"status": "x" * MAX_DETAIL_VALUE_LENGTH})


def test_detail_values_accept_scalars_only() -> None:
    reporter = ActivityReporter()

    event = reporter.emit(
        AgentActivityKind.COMPLETED,
        detail={"turns": 3, "confidence": 0.8, "capability_available": False, "intent": "general", "model": None},
    )
    assert event.detail == {"turns": 3, "confidence": 0.8, "capability_available": False, "intent": "general", "model": None}


def test_messages_are_never_interpolated() -> None:
    reporter = ActivityReporter()
    marker = "user-provided-text-marker"

    event = reporter.emit(AgentActivityKind.COMPLETED, detail={"status": marker})

    assert event.message == "Finished"
    assert marker not in event.message
