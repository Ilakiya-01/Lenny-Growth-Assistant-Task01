"""Agentic router tests: classification and pathway preparation.

The router only classifies and plans. Executing a plan is the application
agent's job (see ``test_agent.py``), so every test here asserts that routing
itself never calls a provider and never runs a capability.
"""

from __future__ import annotations

import pytest

from app.agent.activity import ActivityReporter, AgentActivityKind
from app.agent.classifier import HeuristicIntentClassifier, LLMIntentClassifier
from app.agent.context import AgentContext
from app.agent.intents import (
    ExecutionPath,
    ExecutionPlan,
    Intent,
    RoutingDecision,
)
from app.agent.router import (
    STEP_CLASSIFY,
    STEP_DIRECT_RESPONSE,
    STEP_INVOKE_CAPABILITY,
    STEP_RESOLVE_CAPABILITY,
    STEP_SELECT_PROVIDER,
    AgentRouter,
)
from app.agent.tools import CapabilityDescriptor, ToolRegistry, default_registry
from app.errors import AgentClassificationError

ROUTING_EXAMPLES = [
    ("What did Lenny's guests say about product-market fit?", Intent.RAG_QA, ExecutionPath.TRANSCRIPT_SEARCH),
    ("Write a 1250-word essay about finding product-market fit.", Intent.SHIP30FOR30, ExecutionPath.SHIP30FOR30),
    (
        "Create a markdown product strategy document from this discussion.",
        Intent.ARTIFACT_GENERATION,
        ExecutionPath.ARTIFACT_GENERATION,
    ),
    ("Hello, how are you?", Intent.GENERAL, ExecutionPath.DIRECT_RESPONSE),
]


@pytest.fixture
def registry() -> ToolRegistry:
    return default_registry()


@pytest.fixture
def router(registry) -> AgentRouter:
    return AgentRouter(registry)


@pytest.fixture
def client(scripted_client):
    return scripted_client()


@pytest.mark.parametrize(("prompt", "intent", "path"), ROUTING_EXAMPLES)
def test_router_classifies_the_documented_examples(router, run_async, prompt, intent, path) -> None:
    decision = run_async(router.route(AgentContext(user_message=prompt)))

    assert isinstance(decision, RoutingDecision)
    assert decision.intent is intent
    assert decision.execution_path is path
    assert 0.0 < decision.confidence <= 1.0
    assert decision.classifier == "heuristic"


def test_router_output_is_structured_and_serializable(router, run_async) -> None:
    decision = run_async(router.route(AgentContext(user_message="Hello, how are you?")))
    payload = decision.to_dict()

    assert set(payload) == {
        "intent",
        "confidence",
        "execution_path",
        "classifier",
        "signals",
        "secondary_intents",
    }
    assert all(isinstance(value, (str, float, list)) for value in payload.values())
    assert payload["intent"] == "general"


def test_router_does_not_expose_hidden_reasoning(router, run_async) -> None:
    prompt = "What did Lenny's guests say about product-market fit?"
    decision = run_async(router.route(AgentContext(user_message=prompt)))

    assert not hasattr(decision, "reasoning")
    assert not hasattr(decision, "chain_of_thought")
    assert not hasattr(decision, "prompt")
    assert prompt not in str(decision.to_dict())


def test_router_emits_a_safe_classification_activity(router, run_async) -> None:
    reporter = ActivityReporter()
    prompt = "What did Lenny's guests say about product-market fit?"
    run_async(router.route(AgentContext(user_message=prompt), reporter=reporter))

    stages = [event.kind for event in reporter.events]
    assert stages == [AgentActivityKind.CLASSIFYING_INTENT]
    assert reporter.events[0].message == "Classifying request"
    assert prompt not in str(reporter.to_dicts())


def test_heuristic_classification_never_calls_the_provider(scripted_client, run_async) -> None:
    client = scripted_client(text='{"intent": "general", "confidence": 0.9}')
    assisted = AgentRouter(default_registry(), llm_classifier=LLMIntentClassifier(client))

    decision = run_async(assisted.route(AgentContext(user_message="Write a 1250-word essay about retention.")))

    assert decision.classifier == "heuristic"
    assert client.calls == []


def test_low_confidence_requests_are_reclassified_by_the_provider(scripted_client, run_async) -> None:
    client = scripted_client(text='{"intent": "artifact_generation", "confidence": 0.88}')
    assisted = AgentRouter(default_registry(), llm_classifier=LLMIntentClassifier(client))

    decision = run_async(assisted.route(AgentContext(user_message="Make me something nice about retention.")))

    assert decision.intent is Intent.ARTIFACT_GENERATION
    assert decision.classifier == "llm"
    assert len(client.calls) == 1
    assert "transcript_search" in client.calls[0]["messages"][0].content


def test_a_failing_provider_classifier_surfaces_as_a_structured_error(scripted_client, run_async) -> None:
    client = scripted_client(text="no json here")
    assisted = AgentRouter(default_registry(), llm_classifier=LLMIntentClassifier(client))

    with pytest.raises(AgentClassificationError):
        run_async(assisted.route(AgentContext(user_message="hmm")))


def test_plan_resolves_the_capability_without_running_it(router, client) -> None:
    decision = RoutingDecision(
        intent=Intent.RAG_QA,
        confidence=0.9,
        execution_path=ExecutionPath.TRANSCRIPT_SEARCH,
        classifier="test",
    )
    plan = router.plan(AgentContext(user_message="What did guests say about churn?"), decision, client=client, llm_mode="ollama")

    assert isinstance(plan, ExecutionPlan)
    assert plan.capability == "transcript_qa"
    assert plan.capability_available is True
    assert plan.executable is True
    assert plan.generates_reply is False
    assert plan.steps == (STEP_CLASSIFY, STEP_SELECT_PROVIDER, STEP_RESOLVE_CAPABILITY, STEP_INVOKE_CAPABILITY)
    assert plan.provider == "fake"
    assert plan.llm_mode == "ollama"
    assert client.calls == []


def test_plan_allows_a_direct_reply_only_for_general_requests(router, client, run_async) -> None:
    decision = run_async(router.route(AgentContext(user_message="Hello there")))
    plan = router.plan(AgentContext(user_message="Hello there"), decision, client=client, llm_mode="ollama")

    assert plan.execution_path is ExecutionPath.DIRECT_RESPONSE
    assert plan.capability is None
    assert plan.capability_available is True
    assert plan.generates_reply is True
    assert plan.steps == (STEP_CLASSIFY, STEP_SELECT_PROVIDER, STEP_DIRECT_RESPONSE)


SPECIALIZED_EXAMPLES = [
    (Intent.RAG_QA, "What did Lenny's guests say about onboarding?", "transcript_qa"),
    (Intent.SHIP30FOR30, "Write a 1250-word essay about pricing.", "ship30for30"),
    (Intent.ARTIFACT_GENERATION, "Create a markdown strategy document.", "artifact_generator"),
]


@pytest.mark.parametrize(("intent", "prompt", "capability"), SPECIALIZED_EXAMPLES)
def test_specialized_intents_resolve_to_an_available_capability(router, client, run_async, intent, prompt, capability) -> None:
    decision = run_async(router.route(AgentContext(user_message=prompt)))
    plan = router.plan(AgentContext(user_message=prompt), decision, client=client, llm_mode="ollama")

    assert decision.intent is intent
    assert plan.capability == capability
    assert plan.capability_available is True
    assert plan.executable is True
    assert plan.generates_reply is False


def test_an_unregistered_capability_is_planned_but_not_executable(scripted_client, run_async) -> None:
    registry = ToolRegistry()
    registry.register_planned(CapabilityDescriptor(name="ship30for30", description="planned", intents=(Intent.SHIP30FOR30,)))
    router = AgentRouter(registry)
    client = scripted_client(text="")
    prompt = "Write a 1250-word essay about pricing."

    decision = run_async(router.route(AgentContext(user_message=prompt)))
    plan = router.plan(AgentContext(user_message=prompt), decision, client=client, llm_mode="ollama")

    assert plan.capability == "ship30for30"
    assert plan.capability_available is False
    assert plan.executable is False


def test_capability_state_follows_the_registry(router) -> None:
    assert router.capability_state(Intent.RAG_QA) == ("transcript_qa", True)

    registry = ToolRegistry()
    registry.register_planned(CapabilityDescriptor(name="transcript_qa", description="planned", intents=(Intent.RAG_QA,)))
    assert AgentRouter(registry).capability_state(Intent.RAG_QA) == ("transcript_qa", False)


def test_router_reports_whether_llm_classification_is_enabled(registry, scripted_client) -> None:
    assert AgentRouter(registry).uses_llm_classification is False
    assisted = AgentRouter(registry, llm_classifier=LLMIntentClassifier(scripted_client(text="{}")))
    assert assisted.uses_llm_classification is True


def test_router_accepts_an_injected_heuristic_classifier(registry, run_async) -> None:
    called: list[str] = []

    class Recording(HeuristicIntentClassifier):
        def classify(self, text):
            called.append(text)
            return super().classify(text)

    router = AgentRouter(registry, classifier=Recording())
    run_async(router.route(AgentContext(user_message="Hello")))

    assert called == ["Hello"]


def test_router_rejects_an_empty_user_message(router, run_async) -> None:
    with pytest.raises(ValueError):
        run_async(router.route(AgentContext(user_message="   ")))
