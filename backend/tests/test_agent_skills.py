"""Agent orchestration tests: routing a request to a capability and composing two.

These exercise the Phase 4 flow end to end through the existing application
agent: request -> router -> plan -> registry -> capability -> provider ->
structured result. Retrieval is replaced at the Phase 2 boundary by the shared
``fake_retrieval`` fixture; the provider is the scripted client.
"""

from __future__ import annotations

import json

import pytest

from app.agent.activity import ActivityReporter, AgentActivityKind
from app.agent.agent import (
    ARTIFACT_COMPOSITION_NOTE,
    CAPABILITY_EXECUTED_NOTE,
    EVIDENCE_COMPOSITION_NOTE,
    STATUS_COMPLETED,
    STATUS_PATHWAY_PREPARED,
    ApplicationAgent,
    error_category,
)
from app.agent.context import AgentContext
from app.agent.intents import ExecutionPath, ExecutionPlan, Intent
from app.agent.skills.artifacts import ARTIFACT_TYPE_MARKDOWN
from app.agent.tools import ToolRegistry, default_registry
from app.errors import AgentConfigurationError, TranscriptSearchError
from app.llm.factory import MODE_OLLAMA

ARTICLE = (
    "# Retention before acquisition\n\n"
    "Most growth advice starts in the wrong place.\n\n"
    "## Fix churn first\n\n"
    "- Measure churn weekly\n"
    "- Talk to churned users\n"
    "- Fix the biggest reason\n\n"
    "**Retention is the compounding asset.**\n\n"
    "## The takeaway\n\nEarn the right to grow."
)

ARTIFACT_JSON = json.dumps(
    {
        "type": "markdown",
        "title": "Product strategy",
        "content": "# Product strategy\n\nShip the retention fix first.",
    }
)


def _agent(scripted_client, **kwargs) -> ApplicationAgent:
    return ApplicationAgent(client=scripted_client, llm_mode=MODE_OLLAMA, **kwargs)


def test_a_grounded_question_runs_the_qa_capability_through_the_agent(
    scripted_client, fake_retrieval, transcript_result, run_async
) -> None:
    fake_retrieval.script(transcript_result(similarity=0.8))
    client = scripted_client(text="Ada Lovelace argues retention compounds before acquisition.")
    agent = _agent(client)

    result = run_async(
        agent.handle(AgentContext(user_message="What did Lenny's guests say about retention?"), db=object())
    )

    assert result.status == STATUS_COMPLETED
    assert result.intent is Intent.RAG_QA
    assert result.execution_path is ExecutionPath.TRANSCRIPT_SEARCH
    assert result.capability == "transcript_qa"
    assert result.skills == ("transcript_qa",)
    assert result.reply == "Ada Lovelace argues retention compounds before acquisition."
    assert result.metadata["grounded"] is True
    assert result.metadata["evidence_count"] == 1
    assert result.sources[0]["episode_id"] == "pytest-episode"
    assert result.notes == (CAPABILITY_EXECUTED_NOTE,)
    # The question reached the provider as a grounded prompt, not as raw retrieval output.
    prompt = client.calls[0]["messages"][0].content
    assert "Retention compounds" in prompt
    assert "Question: What did Lenny's guests say about retention?" in prompt


def test_the_agent_reports_retrieval_and_execution_stages(
    scripted_client, fake_retrieval, transcript_result, run_async
) -> None:
    fake_retrieval.script(transcript_result())
    agent = _agent(scripted_client(text="Answer."))
    reporter = ActivityReporter()

    result = run_async(
        agent.handle(
            AgentContext(user_message="What did Lenny's guests say about retention?"),
            db=object(),
            reporter=reporter,
        )
    )

    stages = [event.kind for event in result.activity]
    # Retrieval happens inside the QA capability, so it is reported after the
    # agent starts executing it and before the request completes.
    assert stages == [
        AgentActivityKind.PREPARING_REQUEST,
        AgentActivityKind.CLASSIFYING_INTENT,
        AgentActivityKind.SELECTING_PROVIDER,
        AgentActivityKind.PREPARING_PATHWAY,
        AgentActivityKind.EXECUTING_CAPABILITY,
        AgentActivityKind.RETRIEVING_EVIDENCE,
        AgentActivityKind.COMPLETED,
    ]
    assert reporter.events == result.activity
    assert "What did Lenny's guests say about retention?" not in str(reporter.to_dicts())
    assert "Answer." not in str(reporter.to_dicts())


def test_a_writing_request_runs_the_ship30for30_capability(scripted_client, run_async) -> None:
    client = scripted_client(text=ARTICLE)
    agent = _agent(client)

    result = run_async(agent.handle(AgentContext(user_message="Write a 1250-word essay about retention.")))

    assert result.intent is Intent.SHIP30FOR30
    assert result.capability == "ship30for30"
    assert result.skills == ("ship30for30",)
    assert result.reply == ARTICLE
    assert result.metadata["word_count"] > 0
    assert result.metadata["reading_time_minutes"] >= 1
    assert result.artifact is None
    assert result.notes == (CAPABILITY_EXECUTED_NOTE,)


def test_an_artifact_request_returns_structured_data_not_prose(scripted_client, run_async) -> None:
    client = scripted_client(text=ARTIFACT_JSON)
    agent = _agent(client)

    result = run_async(agent.handle(AgentContext(user_message="Create a markdown product strategy document.")))

    assert result.intent is Intent.ARTIFACT_GENERATION
    assert result.skills == ("artifact_generator",)
    assert result.artifact == {
        "type": ARTIFACT_TYPE_MARKDOWN,
        "title": "Product strategy",
        "content": "# Product strategy\n\nShip the retention fix first.",
    }
    # The assistant text is a short confirmation; the body only travels as data.
    assert result.reply is not None
    assert "Ship the retention fix first." not in result.reply
    assert result.metadata["artifact_type"] == ARTIFACT_TYPE_MARKDOWN
    assert result.metadata["artifact_title"] == "Product strategy"


def test_a_request_that_asks_for_both_composes_writing_then_artifact(scripted_client, run_async) -> None:
    client = scripted_client(text=ARTICLE)
    agent = _agent(client)
    reporter = ActivityReporter()

    result = run_async(
        agent.handle(
            AgentContext(
                user_message="Write a 1250-word essay about retention and deliver it as a markdown artifact."
            ),
            reporter=reporter,
        )
    )

    assert result.intent is Intent.SHIP30FOR30
    assert Intent.ARTIFACT_GENERATION in result.secondary_intents
    assert result.skills == ("ship30for30", "artifact_generator")
    assert result.artifact is not None
    assert result.artifact["type"] == ARTIFACT_TYPE_MARKDOWN
    # The wrap is deterministic, so the title comes from the article's own H1.
    assert result.artifact["title"] == "Retention before acquisition"
    # The article is the assistant text and the artifact is the same document as
    # structured data, so a renderer never has to parse it back out of the prose.
    assert result.reply == ARTICLE
    assert result.artifact["content"] == ARTICLE
    # Wrapping an existing document needs no second model call.
    assert len(client.calls) == 1
    assert result.notes == (CAPABILITY_EXECUTED_NOTE, ARTIFACT_COMPOSITION_NOTE)
    assert AgentActivityKind.GENERATING_ARTIFACT in [event.kind for event in result.activity]


def test_evidence_is_added_for_a_capability_that_mentions_lenny_sources(
    scripted_client, fake_retrieval, transcript_result, run_async
) -> None:
    fake_retrieval.script(transcript_result())
    client = scripted_client(text=ARTICLE)
    agent = _agent(client)

    result = run_async(
        agent.handle(
            AgentContext(user_message="Write a 1250-word essay about Lenny's podcast lessons on retention."),
            db=object(),
        )
    )

    assert result.intent is Intent.SHIP30FOR30
    assert result.skills == ("ship30for30",)
    assert result.notes == (EVIDENCE_COMPOSITION_NOTE,)
    assert len(result.sources) == 1
    assert result.metadata["evidence_count"] == 1
    assert "Retention compounds" in client.calls[0]["messages"][0].content


def test_a_general_request_still_takes_the_direct_pathway(scripted_client, fake_retrieval, run_async) -> None:
    client = scripted_client(text="Hello! How can I help?")
    agent = _agent(client)

    result = run_async(agent.handle(AgentContext(user_message="Hello, how are you?")))

    assert result.intent is Intent.GENERAL
    assert result.skills == ()
    assert result.artifact is None
    assert result.sources == ()
    assert fake_retrieval.calls == []


def test_an_unregistered_capability_is_never_invoked(scripted_client, run_async) -> None:
    client = scripted_client(text="This must never be returned.")
    agent = _agent(client, registry=ToolRegistry())

    result = run_async(agent.handle(AgentContext(user_message="Write a 1250-word essay about retention.")))

    assert result.status == STATUS_PATHWAY_PREPARED
    assert result.capability_available is False
    assert result.reply is None
    assert client.calls == []


def test_an_inconsistent_plan_fails_safely(scripted_client, run_async) -> None:
    """A plan that claims an available capability the registry does not hold is a bug.

    The router derives availability from the registry, so this state cannot occur
    by itself; the test pins the agent's behaviour if a future pathway ever
    introduces it.
    """

    class InconsistentRouter:
        def __init__(self) -> None:
            self._inner = ApplicationAgent(client=scripted_client(text="x"), llm_mode=MODE_OLLAMA).router

        async def route(self, context, *, reporter=None):
            return await self._inner.route(context, reporter=reporter)

        def plan(self, context, decision, *, client, llm_mode):
            return ExecutionPlan(
                decision=decision,
                capability="ship30for30",
                capability_available=True,
                provider=client.provider,
                model=client.model,
                llm_mode=llm_mode,
                steps=("classify_intent", "select_provider", "resolve_capability", "invoke_capability"),
            )

    agent = ApplicationAgent(
        client=scripted_client(text="x"),
        llm_mode=MODE_OLLAMA,
        registry=ToolRegistry(),
        router=InconsistentRouter(),
    )

    with pytest.raises(AgentConfigurationError):
        run_async(agent.handle(AgentContext(user_message="Write a 1250-word essay about retention.")))


def test_a_retrieval_failure_is_reported_in_the_activity_and_reraised(scripted_client, fake_retrieval, run_async) -> None:
    fake_retrieval.script(error=TranscriptSearchError("the vector store is unreachable"))
    agent = _agent(scripted_client(text="unused"))
    reporter = ActivityReporter()

    with pytest.raises(TranscriptSearchError):
        run_async(
            agent.handle(
                AgentContext(user_message="What did Lenny's guests say about retention?"),
                db=object(),
                reporter=reporter,
            )
        )

    assert reporter.events[-1].kind is AgentActivityKind.FAILED
    assert reporter.events[-1].detail == {"status": "transcript_search"}
    assert "vector store" not in str(reporter.to_dicts())


def test_the_result_payload_never_carries_prompts_or_reasoning(scripted_client, run_async) -> None:
    agent = _agent(scripted_client(text=ARTICLE))
    question = "private-request-marker"

    result = run_async(agent.handle(AgentContext(user_message=f"Write a 1250-word essay about retention. {question}")))
    payload = result.to_dict()

    assert not any(key in payload for key in ("prompt", "system_prompt", "reasoning", "chain_of_thought", "api_key"))
    assert question not in str(payload["activity"])
    assert question not in str(payload["metadata"])
    assert set(payload) >= {"artifact", "sources", "metadata", "skills"}


def test_error_categories_cover_the_new_capability_errors() -> None:
    assert error_category(TranscriptSearchError("x")) == "transcript_search"
    assert error_category(AgentConfigurationError("x")) == "agent_configuration"
