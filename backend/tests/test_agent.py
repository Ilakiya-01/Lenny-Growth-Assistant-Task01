"""Application agent tests: provider selection, pathway execution, safe failures.

Capability behaviour itself is tested in the ``test_skill_*`` modules; this file
covers how the agent selects a provider, decides whether a pathway is
executable, and fails safely.
"""

from __future__ import annotations

import uuid

import pytest

from app.agent.activity import ActivityReporter, AgentActivityKind
from app.agent.agent import (
    DIRECT_RESPONSE_NOTE,
    PATHWAY_PREPARED_NOTE,
    STATUS_COMPLETED,
    STATUS_PATHWAY_PREPARED,
    ApplicationAgent,
    create_application_agent,
    error_category,
)
from app.agent.classifier import LLMIntentClassifier
from app.agent.context import AgentContext
from app.agent.intents import ExecutionPath, Intent
from app.agent.runtimes import RUNTIME_CLAUDE_AGENT_SDK, RUNTIME_PROVIDER
from app.agent.tools import AgentTool, ToolRegistry, ToolResult, default_registry
from app.config import Settings
from app.errors import (
    AgentConfigurationError,
    AgentClassificationError,
    LLMConfigurationError,
    LLMResponseError,
    LLMUnavailableError,
)
from app.llm.factory import MODE_CLOUD, MODE_OLLAMA

FAKE_KEY = "sk-ant-unit-test-placeholder"


def _settings(**overrides) -> Settings:
    values: dict = {
        "llm_mode": MODE_OLLAMA,
        "ollama_model": "llama3.1:8b",
        "ollama_base_url": "http://localhost:11434",
        "anthropic_api_key": "",
        "anthropic_model": "claude-sonnet-4-5",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def agent(scripted_client) -> ApplicationAgent:
    return ApplicationAgent(client=scripted_client(text="Hello! How can I help?"), llm_mode=MODE_OLLAMA)


def test_agent_initializes_with_the_configured_provider(scripted_client) -> None:
    client = scripted_client(text="hi")
    built = create_application_agent(settings=_settings(), client=client)

    assert built.client is client
    assert built.llm_mode == MODE_OLLAMA
    assert built.registry.available_capabilities() == (
        "artifact_generator",
        "ship30for30",
        "transcript_qa",
        "transcript_search",
    )
    assert built.registry.planned_capabilities() == ()


def test_agent_builds_the_cloud_runtime_in_cloud_mode(scripted_client) -> None:
    built = create_application_agent(
        settings=_settings(llm_mode=MODE_CLOUD, anthropic_api_key=FAKE_KEY),
        client=scripted_client(text="hi"),
    )

    assert built.llm_mode == MODE_CLOUD
    runtime = built._runtime_for(MODE_CLOUD)
    assert runtime.name == RUNTIME_CLAUDE_AGENT_SDK


def test_agent_uses_the_provider_runtime_in_ollama_mode(agent) -> None:
    assert agent._runtime_for(MODE_OLLAMA).name == RUNTIME_PROVIDER


def test_agent_rejects_an_unknown_runtime_mode(scripted_client) -> None:
    built = ApplicationAgent(client=scripted_client(text="hi"), llm_mode=MODE_OLLAMA)

    with pytest.raises(AgentConfigurationError):
        built._runtime_for("something-else")


def test_agent_never_constructs_a_provider_it_was_not_configured_for() -> None:
    with pytest.raises(LLMConfigurationError):
        create_application_agent(settings=_settings(llm_mode=MODE_CLOUD, anthropic_api_key=""))

    with pytest.raises(LLMConfigurationError):
        create_application_agent(settings=_settings(ollama_model=""))


def test_llm_assisted_routing_is_off_unless_configured(scripted_client) -> None:
    built = create_application_agent(settings=_settings(), client=scripted_client(text="hi"))
    assert built.router.uses_llm_classification is False

    assisted = create_application_agent(
        settings=_settings(llm_router_llm_classification=True),
        client=scripted_client(text='{"intent": "general", "confidence": 0.9}'),
    )
    assert assisted.router.uses_llm_classification is True


def test_general_request_is_answered_by_the_provider(agent, run_async) -> None:
    result = run_async(agent.handle(AgentContext(user_message="Hello, how are you?")))

    assert result.status == STATUS_COMPLETED
    assert result.intent is Intent.GENERAL
    assert result.execution_path is ExecutionPath.DIRECT_RESPONSE
    assert result.reply == "Hello! How can I help?"
    assert result.provider == "fake"
    assert result.capability is None
    assert result.skills == ()
    assert result.sources == ()
    assert result.artifact is None
    assert result.notes == (DIRECT_RESPONSE_NOTE,)
    assert result.usage is not None


def test_a_capability_that_is_not_registered_is_prepared_but_not_executed(scripted_client, run_async) -> None:
    client = scripted_client(text="This text must never be produced.")
    agent = ApplicationAgent(client=client, llm_mode=MODE_OLLAMA, registry=ToolRegistry())

    result = run_async(agent.handle(AgentContext(user_message="Write a 1250-word essay about growth.")))

    assert result.status == STATUS_PATHWAY_PREPARED
    assert result.intent is Intent.SHIP30FOR30
    assert result.capability == "ship30for30"
    assert result.capability_available is False
    assert result.reply is None
    assert result.skills == ()
    assert result.notes == (PATHWAY_PREPARED_NOTE,)
    assert client.calls == []


def test_agent_reports_its_activity_sequence(scripted_client, run_async) -> None:
    client = scripted_client(text="hi")
    agent = ApplicationAgent(client=client, llm_mode=MODE_OLLAMA)
    reporter = ActivityReporter()

    result = run_async(agent.handle(AgentContext(user_message="Hello there"), reporter=reporter))

    assert [event.kind for event in result.activity] == [
        AgentActivityKind.PREPARING_REQUEST,
        AgentActivityKind.CLASSIFYING_INTENT,
        AgentActivityKind.SELECTING_PROVIDER,
        AgentActivityKind.PREPARING_PATHWAY,
        AgentActivityKind.GENERATING_RESPONSE,
        AgentActivityKind.COMPLETED,
    ]
    assert reporter.events == result.activity


def test_capability_activity_omits_the_generation_stage_used_for_direct_replies(scripted_client, run_async) -> None:
    agent = ApplicationAgent(client=scripted_client(text="An article."), llm_mode=MODE_OLLAMA)

    result = run_async(agent.handle(AgentContext(user_message="Write a 1250-word essay about growth.")))

    stages = [event.kind for event in result.activity]
    assert AgentActivityKind.GENERATING_RESPONSE not in stages
    assert AgentActivityKind.EXECUTING_CAPABILITY in stages
    assert stages[-1] is AgentActivityKind.COMPLETED


def test_activity_never_contains_the_prompt_or_the_reply(agent, run_async) -> None:
    prompt = "private-question-marker"
    result = run_async(agent.handle(AgentContext(user_message=prompt)))
    serialized = str(result.to_dict()["activity"])

    assert prompt not in serialized
    assert "Hello! How can I help?" not in serialized


def test_result_serializes_without_prompts_or_reasoning(agent, run_async) -> None:
    result = run_async(agent.handle(AgentContext(user_message="Hello, how are you?")))
    payload = result.to_dict()

    assert set(payload) >= {"status", "intent", "execution_path", "llm_mode", "provider", "reply", "activity"}
    assert payload["llm_mode"] == MODE_OLLAMA
    assert not any(key in payload for key in ("prompt", "system_prompt", "reasoning", "chain_of_thought", "api_key"))
    assert "Hello, how are you?" not in str(payload)


def test_a_provider_failure_fails_the_request_safely(scripted_client, run_async) -> None:
    client = scripted_client(error=LLMUnavailableError("provider is down", user_message="The provider is unavailable."))
    agent = ApplicationAgent(client=client, llm_mode=MODE_OLLAMA)
    reporter = ActivityReporter()

    with pytest.raises(LLMUnavailableError):
        run_async(agent.handle(AgentContext(user_message="Hello there"), reporter=reporter))

    assert reporter.events[-1].kind is AgentActivityKind.FAILED
    assert reporter.events[-1].detail == {"status": "llm_unavailable"}
    assert "down" not in str(reporter.to_dicts())


def test_a_classification_failure_fails_the_request_safely(scripted_client, run_async) -> None:
    client = scripted_client(text="no json")
    agent = ApplicationAgent(
        client=client,
        llm_mode=MODE_OLLAMA,
        router=None,
    )
    agent._router._llm_classifier = LLMIntentClassifier(client)
    reporter = ActivityReporter()

    with pytest.raises(AgentClassificationError):
        run_async(agent.handle(AgentContext(user_message="hmm"), reporter=reporter))

    assert reporter.events[-1].detail == {"status": "agent_classification"}


def test_an_empty_provider_reply_is_reported(scripted_client, run_async) -> None:
    agent = ApplicationAgent(client=scripted_client(text=""), llm_mode=MODE_OLLAMA)

    with pytest.raises(LLMResponseError):
        run_async(agent.handle(AgentContext(user_message="Hello there")))


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (LLMConfigurationError("x"), "llm_configuration"),
        (LLMUnavailableError("x"), "llm_unavailable"),
        (LLMResponseError("x"), "llm_response"),
        (AgentConfigurationError("x"), "agent_configuration"),
        (AgentClassificationError("x"), "agent_classification"),
        (RuntimeError("x"), "unexpected"),
    ],
)
def test_error_categories_are_coarse_and_safe(error, category) -> None:
    assert error_category(error) == category


def test_agent_exposes_a_registry_tools_can_be_registered_into(agent, run_async) -> None:
    class LookupTool(AgentTool):
        name = "lookup"
        description = "Look something up."
        intents = (Intent.RAG_QA,)

        async def run(self, arguments, context) -> ToolResult:
            return ToolResult(tool=self.name, content="found")

    descriptor = agent.registry.register_tool(LookupTool())

    assert descriptor.available is True
    assert agent.registry.is_available("lookup") is True
    assert agent.registry.capabilities_for_intent(Intent.RAG_QA) == ("lookup", "transcript_qa", "transcript_search")


def test_agent_can_be_built_with_a_custom_registry(scripted_client) -> None:
    registry = ToolRegistry()
    built = ApplicationAgent(client=scripted_client(text="hi"), llm_mode=MODE_OLLAMA, registry=registry)

    assert built.registry is registry
    assert built.registry.capability_names() == ()


def test_agent_closes_its_provider_client(scripted_client, run_async) -> None:
    closed: list[bool] = []

    class ClosingClient(type(scripted_client())):
        async def aclose(self) -> None:
            closed.append(True)

    client = ClosingClient(text="hi")
    agent = ApplicationAgent(client=client, llm_mode=MODE_OLLAMA)
    run_async(agent.aclose())

    assert closed == [True]


def test_default_registry_is_used_when_none_is_given(agent) -> None:
    assert agent.registry.available_capabilities() == default_registry().available_capabilities()


def test_context_session_id_is_carried_into_events(scripted_client, run_async) -> None:
    session_id = uuid.uuid4()
    agent = ApplicationAgent(client=scripted_client(text="hi"), llm_mode=MODE_OLLAMA)
    reporter = ActivityReporter()

    run_async(agent.handle(AgentContext(user_message="Hello"), session_id=session_id, reporter=reporter))

    assert reporter.events[0].detail["session_id"] == str(session_id)
