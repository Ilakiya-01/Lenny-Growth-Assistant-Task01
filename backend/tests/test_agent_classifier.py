"""Intent classification tests for the heuristic and provider-backed classifiers."""

from __future__ import annotations

import pytest

from app.agent.classifier import (
    CLASSIFIER_HEURISTIC,
    CLASSIFIER_LLM,
    LLM_CLASSIFICATION_INSTRUCTION,
    HeuristicIntentClassifier,
    LLMIntentClassifier,
)
from app.agent.intents import Intent
from app.errors import AgentClassificationError, LLMUnavailableError

ROUTING_EXAMPLES = [
    ("What did Lenny's guests say about product-market fit?", Intent.RAG_QA),
    ("Write a 1250-word essay about finding product-market fit.", Intent.SHIP30FOR30),
    ("Create a markdown product strategy document from this discussion.", Intent.ARTIFACT_GENERATION),
    ("Hello, how are you?", Intent.GENERAL),
]


@pytest.fixture
def heuristic() -> HeuristicIntentClassifier:
    return HeuristicIntentClassifier()


@pytest.mark.parametrize(("prompt", "expected"), ROUTING_EXAMPLES)
def test_roadmap_routing_examples_are_classified_as_documented(heuristic, prompt, expected) -> None:
    result = heuristic.classify(prompt)

    assert result.intent is expected
    assert result.classifier == CLASSIFIER_HEURISTIC
    assert 0.0 < result.confidence <= 1.0
    assert result.signals


def test_primary_intent_clears_the_confidence_threshold(heuristic) -> None:
    result = heuristic.classify("Write a 1250-word essay about finding product-market fit.")

    assert result.confidence >= 0.5


def test_transcript_question_reports_the_search_signals_only(heuristic) -> None:
    result = heuristic.classify("What did Lenny's guests say about product-market fit?")

    assert result.signals == (
        "rag:source_terms",
        "rag:topic_terms",
        "rag:attribution_terms",
        "rag:question_form",
        "rag:interrogative",
    )
    assert all(signal.replace(":", "").replace("_", "").isalnum() for signal in result.signals)


def test_document_request_is_not_reported_as_an_essay(heuristic) -> None:
    result = heuristic.classify("Create a markdown product strategy document from this discussion.")

    assert result.intent is Intent.ARTIFACT_GENERATION
    assert Intent.SHIP30FOR30 not in result.secondary_intents


def test_plain_greeting_needs_no_provider(heuristic) -> None:
    result = heuristic.classify("Hello, how are you?")

    assert result.intent is Intent.GENERAL
    assert result.signals == ("general:greeting",)


@pytest.mark.parametrize("prompt", ["", "   ", "42", "ok"])
def test_low_signal_requests_fall_back_to_general(heuristic, prompt) -> None:
    result = heuristic.classify(prompt)

    assert result.intent is Intent.GENERAL
    assert result.signals == ("general:low_signal",)
    assert result.confidence < 0.5


def test_secondary_intents_are_reported_for_mixed_requests(heuristic) -> None:
    result = heuristic.classify(
        "What did Lenny's guests say about PMF, and then write a 1250-word essay about it?"
    )

    assert result.intent is Intent.SHIP30FOR30
    assert Intent.RAG_QA in result.secondary_intents


def test_classification_result_has_no_reasoning_field(heuristic) -> None:
    result = heuristic.classify("Write a 1250-word essay about finding product-market fit.")

    assert not hasattr(result, "reasoning")
    assert not hasattr(result, "explanation")
    assert not hasattr(result, "raw")


def test_llm_classifier_returns_only_a_label_and_confidence(scripted_client, run_async) -> None:
    client = scripted_client(text='{"intent": "ship30for30", "confidence": 0.91}')
    result = run_async(LLMIntentClassifier(client).classify("Write an essay about retention."))

    assert result.intent is Intent.SHIP30FOR30
    assert result.confidence == 0.91
    assert result.classifier == CLASSIFIER_LLM
    assert result.signals == ("llm:provider_label",)
    assert result.secondary_intents == ()


def test_llm_classifier_sends_an_instruction_not_a_chain_of_thought(scripted_client, run_async) -> None:
    client = scripted_client(text='{"intent": "general", "confidence": 0.5}')
    run_async(LLMIntentClassifier(client).classify("hi", capabilities=("transcript_search",)))

    call = client.calls[0]
    assert call["system"] == LLM_CLASSIFICATION_INSTRUCTION
    assert "transcript_search" in call["messages"][0].content
    assert call["max_tokens"] == 64
    assert call["temperature"] == 0.0


def test_llm_classifier_tolerates_a_fenced_json_block(scripted_client, run_async) -> None:
    client = scripted_client(text='```json\n{"intent": "rag_qa", "confidence": 0.8}\n```')
    result = run_async(LLMIntentClassifier(client).classify("What did guests say about churn?"))

    assert result.intent is Intent.RAG_QA


@pytest.mark.parametrize(
    "payload",
    [
        "I think this is probably a RAG question.",
        '{"intent": "ship30for30"}',
        '{"intent": "poetry", "confidence": 0.9}',
        '{"intent": "general", "confidence": "very"}',
        '{"intent": "general", "confidence": -1}',
        "{}",
    ],
)
def test_llm_classifier_rejects_unusable_labels(scripted_client, run_async, payload) -> None:
    client = scripted_client(text=payload)
    with pytest.raises(AgentClassificationError):
        run_async(LLMIntentClassifier(client).classify("something"))


def test_llm_classifier_does_not_echo_model_output_in_errors(scripted_client, run_async) -> None:
    secret_marker = "internal-reasoning-marker"
    client = scripted_client(text=f"I will consider {secret_marker} but reply with nothing usable.")
    with pytest.raises(AgentClassificationError) as excinfo:
        run_async(LLMIntentClassifier(client).classify("something"))

    assert secret_marker not in str(excinfo.value)


def test_llm_classifier_propagates_provider_failures(scripted_client, run_async) -> None:
    client = scripted_client(error=LLMUnavailableError("provider is down"))
    with pytest.raises(LLMUnavailableError):
        run_async(LLMIntentClassifier(client).classify("something"))
