"""Transcript-grounded Q&A capability tests.

Grounding is the behaviour under test: the answer must be produced from the
retrieved passages, and when there is no evidence the skill must say so instead
of answering from general knowledge. Retrieval itself is replaced by the shared
``fake_retrieval`` fixture in this module.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.activity import ActivityReporter, AgentActivityKind
from app.agent.skills.base import SkillContext
from app.agent.skills.grounded_qa import (
    ANSWER_MAX_TOKENS,
    GROUNDED_QA_SYSTEM_PROMPT,
    MISSING_EVIDENCE_REPLY,
    QA_TOOL_NAME,
    TranscriptQASkill,
    build_qa_prompt,
)
from app.agent.skills.transcript_search import MIN_EVIDENCE_SIMILARITY
from app.agent.tools import default_registry
from app.errors import LLMConfigurationError, LLMUnavailableError

PROVIDER_ANSWER = "Ada Lovelace argues that retention compounds before acquisition."


def _context(client: Any, **overrides: Any) -> SkillContext:
    values: dict[str, Any] = {"request": "What did guests say about retention?", "registry": default_registry(), "client": client}
    values.update(overrides)
    return SkillContext(**values)


def test_the_answer_is_generated_from_the_retrieved_evidence(fake_retrieval, transcript_result, scripted_client, run_async) -> None:
    fake_retrieval.script(
        transcript_result(chunk_index=0, similarity=0.81),
        transcript_result(chunk_index=4, guest="Brian", title="Pricing talk", content="Price the value you deliver.", similarity=0.75),
    )
    client = scripted_client(text=PROVIDER_ANSWER)

    result = run_async(TranscriptQASkill().run({}, _context(client)))

    assert result.tool == QA_TOOL_NAME
    assert result.content == PROVIDER_ANSWER
    assert result.metadata["grounded"] is True
    assert result.metadata["insufficient_evidence"] is False
    assert result.metadata["evidence_count"] == 2
    assert result.metadata["question"] == "What did guests say about retention?"
    assert result.metadata["provider"] == "fake"

    prompt = client.calls[0]["messages"][0].content
    assert "Retention compounds: the fastest growers fix churn before they buy growth." in prompt
    assert "Price the value you deliver." in prompt
    assert "Growth loops that compound" in prompt
    assert client.calls[0]["system"] == GROUNDED_QA_SYSTEM_PROMPT
    assert client.calls[0]["max_tokens"] == ANSWER_MAX_TOKENS


def test_source_metadata_is_preserved_on_the_answer(fake_retrieval, transcript_result, scripted_client, run_async) -> None:
    fake_retrieval.script(transcript_result())

    result = run_async(TranscriptQASkill().run({}, _context(scripted_client(text=PROVIDER_ANSWER))))

    source = result.metadata["sources"][0]
    assert source["episode_id"] == "pytest-episode"
    assert source["title"] == "Growth loops that compound"
    assert source["guest"] == "Ada Lovelace"
    assert source["publish_date"] == "2024-05-01"
    assert source["youtube_url"] == "https://www.youtube.com/watch?v=pytest"
    assert source["chunk_index"] == 0


def test_insufficient_evidence_is_stated_without_calling_the_provider(fake_retrieval, scripted_client, run_async) -> None:
    fake_retrieval.script()
    client = scripted_client(text="A confident answer invented from general knowledge.")

    result = run_async(TranscriptQASkill().run({}, _context(client)))

    assert result.content == MISSING_EVIDENCE_REPLY
    assert "transcripts" in MISSING_EVIDENCE_REPLY
    assert result.metadata["insufficient_evidence"] is True
    assert result.metadata["grounded"] is False
    assert result.metadata["evidence_count"] == 0
    assert result.metadata["sources"] == []
    assert client.calls == []


def test_weak_matches_are_treated_as_insufficient_evidence(fake_retrieval, transcript_result, scripted_client, run_async) -> None:
    """A passage below the evidence floor must not be answered from.

    Live measurement: an off-topic question still retrieves passages with cosine
    similarities around 0.68, which is semantic proximity, not evidence that the
    transcripts discuss the question.
    """
    fake_retrieval.script(transcript_result(similarity=MIN_EVIDENCE_SIMILARITY - 0.03))
    client = scripted_client(text="A confident answer invented from a weak match.")

    result = run_async(TranscriptQASkill().run({}, _context(client)))

    assert result.content == MISSING_EVIDENCE_REPLY
    assert result.metadata["insufficient_evidence"] is True
    assert result.metadata["evidence_count"] == 0
    assert result.metadata["sources"] == []
    assert client.calls == []


def test_a_strong_passage_keeps_its_weaker_neighbours_out_of_the_evidence(fake_retrieval, transcript_result, scripted_client, run_async) -> None:
    fake_retrieval.script(
        transcript_result(chunk_index=0, similarity=0.79),
        transcript_result(chunk_index=1, content="Unrelated filler about office furniture.", similarity=0.42),
    )
    client = scripted_client(text=PROVIDER_ANSWER)

    result = run_async(TranscriptQASkill().run({}, _context(client)))

    assert result.metadata["evidence_count"] == 1
    assert [source["chunk_index"] for source in result.metadata["sources"]] == [0]
    prompt = client.calls[0]["messages"][0].content
    assert "Retention compounds" in prompt
    assert "office furniture" not in prompt


def test_the_prompt_forbids_general_knowledge_fallbacks() -> None:
    lowered = GROUNDED_QA_SYSTEM_PROMPT.lower()

    assert "only source of truth" in lowered
    assert "general knowledge" in lowered
    assert "never invent" in lowered
    assert "does not contain enough information" in lowered
    assert "say so in your first sentence" in lowered
    assert "chain-of-thought" in lowered
    assert "never reveal" in lowered


def test_the_prompt_carries_the_numbered_evidence_block(transcript_result) -> None:
    from app.agent.skills.base import EvidenceBundle, format_evidence_block

    passages = (transcript_result(), transcript_result(chunk_index=1, content="Churn is a leak in the bucket."))
    bundle = EvidenceBundle(passages=passages, text=format_evidence_block(passages))

    prompt = build_qa_prompt("What did guests say about retention?", bundle.text)

    assert "What did guests say about retention?" in prompt
    assert prompt.count("Churn is a leak in the bucket.") == 1
    assert "[1]" in prompt and "[2]" in prompt


def test_a_provider_failure_reaches_the_agent_unmasked(fake_retrieval, transcript_result, scripted_client, run_async) -> None:
    fake_retrieval.script(transcript_result())
    client = scripted_client(error=LLMUnavailableError("provider is down", user_message="The provider is unavailable."))

    with pytest.raises(LLMUnavailableError):
        run_async(TranscriptQASkill().run({}, _context(client)))


def test_a_missing_provider_is_an_actionable_error(fake_retrieval, transcript_result, run_async) -> None:
    fake_retrieval.script(transcript_result())

    with pytest.raises(LLMConfigurationError) as excinfo:
        run_async(TranscriptQASkill().run({}, _context(None)))

    assert ".env" in excinfo.value.user_message


def test_retrieval_activity_never_contains_the_question(fake_retrieval, transcript_result, scripted_client, run_async) -> None:
    fake_retrieval.script(transcript_result())
    reporter = ActivityReporter()
    question = "private-question-marker"

    run_async(
        TranscriptQASkill().run({}, _context(scripted_client(text=PROVIDER_ANSWER), request=question, reporter=reporter))
    )

    stages = [event.kind for event in reporter.events]
    assert stages == [AgentActivityKind.RETRIEVING_EVIDENCE]
    assert question not in str(reporter.to_dicts())
