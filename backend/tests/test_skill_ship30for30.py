"""Ship30for30 writing capability tests.

The skill owns its prompt template and reports deterministic measurements of the
article it produced (word count, reading time, headings, bullets, bold phrases,
takeaway). Word count is a target, not a gate, so a short article is reported
honestly rather than rejected.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.skills.base import EvidenceBundle, SkillContext, format_evidence_block
from app.agent.skills.ship30for30 import (
    ESSAY_MAX_TOKENS,
    MIN_SECTION_WORDS,
    MIN_TARGET_WORDS,
    SECTION_TARGET,
    SHIP30FOR30_SYSTEM_PROMPT,
    SHIP30FOR30_TOOL_NAME,
    TARGET_WORDS,
    WORDS_PER_MINUTE,
    Ship30For30Skill,
    analyze_essay,
    build_essay_prompt,
)
from app.agent.tools import default_registry
from app.errors import LLMConfigurationError

ARTICLE = (
    "# Retention before acquisition\n"
    "\n"
    "Most growth advice starts in the wrong place.\n"
    "\n"
    "## Fix churn first\n"
    "\n"
    "- Measure churn weekly\n"
    "- Talk to every churned user\n"
    "- Fix the biggest reason\n"
    "\n"
    "**Retention is the compounding asset.** Every later channel works better when the bucket "
    "holds water.\n"
    "\n"
    "## Then buy growth\n"
    "\n"
    "Paid acquisition amplifies whatever you already have. **Amplify a leak and you buy a bigger "
    "leak.** **Fix retention first.**\n"
    "\n"
    "## The takeaway\n"
    "\n"
    "Earn the right to grow before you pay for it.\n"
)


def _context(client: Any, **overrides: Any) -> SkillContext:
    values: dict[str, Any] = {"request": "Write a 1250-word essay about retention.", "registry": default_registry(), "client": client}
    values.update(overrides)
    return SkillContext(**values)


def test_the_article_is_generated_with_the_ship30for30_structure(scripted_client, run_async) -> None:
    client = scripted_client(text=ARTICLE)

    result = run_async(Ship30For30Skill().run({}, _context(client)))

    assert result.tool == SHIP30FOR30_TOOL_NAME
    assert result.content == ARTICLE.strip()
    structure = analyze_essay(result.content)
    assert structure.has_title is True
    assert structure.has_takeaway is True
    assert structure.heading_count >= 3
    assert structure.bullet_count >= 3
    assert structure.bold_count >= 3


def test_word_count_and_reading_time_are_reported(scripted_client, run_async) -> None:
    client = scripted_client(text=ARTICLE)

    result = run_async(Ship30For30Skill().run({}, _context(client)))
    metadata = result.metadata

    assert metadata["skill"] == SHIP30FOR30_TOOL_NAME
    assert metadata["word_count"] == analyze_essay(ARTICLE).word_count
    assert metadata["target_words"] == TARGET_WORDS
    assert metadata["reading_time_minutes"] == max(1, round(metadata["word_count"] / WORDS_PER_MINUTE))
    assert metadata["headings"] == analyze_essay(ARTICLE).heading_count
    assert metadata["bullets"] >= 3
    assert metadata["bold_phrases"] >= 3
    assert metadata["provider"] == "fake"


def test_the_prompt_asks_for_the_full_article(scripted_client, run_async) -> None:
    client = scripted_client(text=ARTICLE)

    run_async(Ship30For30Skill().run({}, _context(client)))
    call = client.calls[0]

    assert call["system"] == SHIP30FOR30_SYSTEM_PROMPT
    assert call["max_tokens"] == ESSAY_MAX_TOKENS
    # The model's own thinking mode is left alone: on the local reasoning model,
    # think=False moved the planning text into the article instead of removing it.
    assert call["think"] is None
    prompt = call["messages"][0].content
    assert "Write a 1250-word essay about retention." in prompt
    assert str(TARGET_WORDS) in prompt
    assert "complete article, not notes or an outline" in call["system"]
    assert "at least three" in call["system"]
    assert "takeaway heading" in call["system"]


def test_the_prompt_states_the_length_contract_in_two_places() -> None:
    """Length is asked for per section as well as in total.

    Measured on the local model: a bare "approximately 1250 words" produced
    articles of 589-761 words that ended cleanly, because the model checks
    completeness section by section, not against a document total. The contract
    therefore names the section count and the per-section floor, and the user
    turn repeats the same numbers.
    """
    assert f"exactly {SECTION_TARGET} sections" in SHIP30FOR30_SYSTEM_PROMPT
    assert f"at least {MIN_SECTION_WORDS} words" in SHIP30FOR30_SYSTEM_PROMPT
    assert f"never fewer than {MIN_TARGET_WORDS}" in SHIP30FOR30_SYSTEM_PROMPT

    prompt = build_essay_prompt("Write an article about retention.")
    assert f"{SECTION_TARGET} sections of at least {MIN_SECTION_WORDS} words each" in prompt
    assert str(TARGET_WORDS) in prompt
    assert str(MIN_TARGET_WORDS) in prompt


def test_a_short_article_is_reported_honestly(scripted_client, run_async) -> None:
    client = scripted_client(text="Growth is good. Retention is better.")

    result = run_async(Ship30For30Skill().run({}, _context(client)))

    assert result.metadata["word_count"] == 6
    assert result.metadata["has_title"] is False
    assert result.metadata["has_takeaway"] is False
    assert result.metadata["headings"] == 0
    assert result.content == "Growth is good. Retention is better."


def test_evidence_is_passed_into_the_essay_prompt(fake_retrieval, transcript_result, scripted_client, run_async) -> None:
    passages = (transcript_result(),)
    bundle = EvidenceBundle(passages=passages, text=format_evidence_block(passages))
    client = scripted_client(text=ARTICLE)

    result = run_async(
        Ship30For30Skill().run({"evidence": bundle}, _context(client))
    )

    prompt = client.calls[0]["messages"][0].content
    assert "Retention compounds: the fastest growers fix churn before they buy growth." in prompt
    assert "Growth loops that compound" in prompt
    assert result.metadata["evidence_count"] == 1
    assert fake_retrieval.calls == []


def test_a_missing_provider_is_an_actionable_error(run_async) -> None:
    with pytest.raises(LLMConfigurationError) as excinfo:
        run_async(Ship30For30Skill().run({}, _context(None)))

    assert ".env" in excinfo.value.user_message


def test_a_provider_failure_is_propagated(scripted_client, run_async) -> None:
    from app.errors import LLMUnavailableError

    client = scripted_client(error=LLMUnavailableError("ollama is not running", user_message="Ollama is not running."))

    with pytest.raises(LLMUnavailableError):
        run_async(Ship30For30Skill().run({}, _context(client)))


def test_analyze_essay_measures_markdown_structure() -> None:
    structure = analyze_essay(
        "# Title\n\nhook line\n\n## Section\n\n- one\n- two\n* three\n\n**bold one** and **bold two**\n\n## The takeaway\n\nremember this\n"
    )

    assert structure.has_title is True
    assert structure.has_takeaway is True
    assert structure.heading_count == 2
    assert structure.bullet_count == 3
    assert structure.bold_count == 2
    assert structure.word_count > 0
    assert structure.reading_time_minutes == 1


def test_analyze_essay_reports_zero_for_an_empty_article() -> None:
    structure = analyze_essay("")

    assert structure.word_count == 0
    assert structure.reading_time_minutes == 0
    assert structure.has_title is False
    assert structure.has_takeaway is False


def test_build_essay_prompt_targets_the_word_count() -> None:
    prompt = build_essay_prompt("Write about pricing.")

    assert "Write about pricing." in prompt
    assert f"approximately {TARGET_WORDS} words" in prompt
    assert "required structure" in prompt
