"""Artifact generation capability tests.

An artifact is structured data (``type``/``title``/``content``/``css``), never
prose: the skill parses the model's JSON, validates it, and hands the artifact
back as metadata so the artifact body can never leak into the assistant text.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.agent.skills.artifacts import (
    ARTIFACT_MAX_TOKENS,
    ARTIFACT_SYSTEM_PROMPT,
    ARTIFACT_TOOL_NAME,
    ARTIFACT_TYPE_HTML,
    ARTIFACT_TYPE_MARKDOWN,
    MAX_ARTIFACT_CHARS,
    MAX_TITLE_CHARS,
    WRAPPED_ARTIFACT_FALLBACK_TITLE,
    Artifact,
    ArtifactSkill,
    build_artifact_prompt,
    build_wrapped_artifact,
    detect_artifact_type,
    normalize_artifact_type,
    parse_artifact,
)
from app.agent.skills.base import EvidenceBundle, SkillContext, format_evidence_block
from app.agent.tools import default_registry
from app.errors import ArtifactGenerationError, LLMConfigurationError, LLMUnavailableError

MARKDOWN_ARTIFACT = {
    "type": "markdown",
    "title": "Product strategy",
    "content": "# Product strategy\n\nShip the retention fix first.",
}

HTML_ARTIFACT = {
    "type": "html",
    "title": "Pricing page",
    "content": "<!doctype html><html><body><h1>Pricing</h1></body></html>",
    "css": "h1 { color: rebeccapurple; }",
}


def _context(client: Any, **overrides: Any) -> SkillContext:
    values: dict[str, Any] = {
        "request": "Create a markdown product strategy document.",
        "registry": default_registry(),
        "client": client,
    }
    values.update(overrides)
    return SkillContext(**values)


def test_a_markdown_artifact_is_returned_as_structured_data(scripted_client, run_async) -> None:
    client = scripted_client(text=json.dumps(MARKDOWN_ARTIFACT))

    result = run_async(ArtifactSkill().run({}, _context(client)))

    assert result.tool == ARTIFACT_TOOL_NAME
    assert result.metadata["artifact"] == {
        "type": ARTIFACT_TYPE_MARKDOWN,
        "title": "Product strategy",
        "content": "# Product strategy\n\nShip the retention fix first.",
    }
    assert result.metadata["artifact_type"] == ARTIFACT_TYPE_MARKDOWN
    assert result.metadata["title"] == "Product strategy"
    assert result.metadata["provider"] == "fake"
    # The tool's content is the artifact body; the reply is built by the agent.
    assert result.content == MARKDOWN_ARTIFACT["content"]


def test_an_html_artifact_keeps_its_stylesheet_separate(scripted_client, run_async) -> None:
    client = scripted_client(text=json.dumps(HTML_ARTIFACT))

    result = run_async(ArtifactSkill().run({"artifact_type": "html"}, _context(client)))

    artifact = result.metadata["artifact"]
    assert artifact["type"] == ARTIFACT_TYPE_HTML
    assert artifact["css"] == "h1 { color: rebeccapurple; }"
    assert "<style>" not in artifact["content"]
    assert "rebeccapurple" not in artifact["content"]


def test_the_html_type_alias_is_normalized(scripted_client, run_async) -> None:
    payload = dict(HTML_ARTIFACT, type="html_css")
    client = scripted_client(text=json.dumps(payload))

    result = run_async(ArtifactSkill().run({}, _context(client)))

    assert result.metadata["artifact"]["type"] == ARTIFACT_TYPE_HTML
    assert result.metadata["artifact"]["css"] == "h1 { color: rebeccapurple; }"


def test_the_artifact_type_is_detected_from_the_request(scripted_client, run_async) -> None:
    client = scripted_client(text=json.dumps(dict(HTML_ARTIFACT, css="")))

    result = run_async(ArtifactSkill().run({}, _context(client, request="Build a landing page for the pricing launch.")))

    assert result.metadata["artifact_type"] == ARTIFACT_TYPE_HTML
    assert "landing page" in client.calls[0]["messages"][0].content.lower()


def test_the_prompt_requires_json_only(scripted_client, run_async) -> None:
    client = scripted_client(text=json.dumps(MARKDOWN_ARTIFACT))

    run_async(ArtifactSkill().run({}, _context(client)))

    call = client.calls[0]
    assert call["system"] == ARTIFACT_SYSTEM_PROMPT
    assert call["max_tokens"] == ARTIFACT_MAX_TOKENS
    assert call["think"] is None
    assert "JSON only" in call["system"]
    assert "never inline the stylesheet" in call["system"]
    assert "chain-of-thought" in call["system"]


def test_the_reasoning_switch_is_not_set_by_the_artifact_skill(scripted_client, run_async) -> None:
    """Both artifact types use the provider default, on measured grounds.

    The reasoning switch is implemented and available at the provider level, but
    the live HTML verification showed that neither setting made the local
    reasoning model return the document: thinking on spent the whole budget in
    the reasoning channel, and thinking off spent it writing content that was not
    the requested JSON. Sending no flag keeps non-reasoning providers on their
    normal path.
    """
    markdown = scripted_client(text=json.dumps(MARKDOWN_ARTIFACT))
    html = scripted_client(text=json.dumps(HTML_ARTIFACT))

    run_async(ArtifactSkill().run({}, _context(markdown)))
    run_async(ArtifactSkill().run({"artifact_type": ARTIFACT_TYPE_HTML}, _context(html)))

    assert markdown.calls[0]["think"] is None
    assert html.calls[0]["think"] is None


def test_an_artifact_can_be_built_from_evidence_and_another_skills_output(transcript_result) -> None:
    passages = (transcript_result(),)
    bundle = EvidenceBundle(passages=passages, text=format_evidence_block(passages))

    prompt = build_artifact_prompt(
        "Create a markdown strategy document.",
        ARTIFACT_TYPE_MARKDOWN,
        evidence=bundle,
        source_output="# Retention before acquisition\n\nFix churn first.",
        source_label="generated article",
    )

    assert "Retention compounds" in prompt
    assert "generated article" in prompt
    assert "Fix churn first." in prompt
    assert "Create a markdown strategy document." in prompt


def test_output_without_json_is_rejected() -> None:
    with pytest.raises(ArtifactGenerationError) as excinfo:
        parse_artifact("Sure! Here is your artifact: it is a strategy document.")

    assert "JSON" in str(excinfo.value)
    assert "Traceback" not in excinfo.value.user_message


def test_a_fenced_json_block_is_accepted() -> None:
    artifact = parse_artifact(f"```json\n{json.dumps(MARKDOWN_ARTIFACT)}\n```")

    assert artifact.title == "Product strategy"
    assert artifact.type == ARTIFACT_TYPE_MARKDOWN


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "markdown", "content": "body without a title"},
        {"type": "markdown", "title": "No content"},
        {"type": "markdown", "title": "Blank", "content": "   "},
        {"type": "poster", "title": "Unsupported type", "content": "body"},
    ],
)
def test_malformed_artifact_structures_are_rejected(payload) -> None:
    with pytest.raises(ArtifactGenerationError):
        parse_artifact(json.dumps(payload))


def test_an_oversized_artifact_is_rejected() -> None:
    payload = {"type": "markdown", "title": "Huge", "content": "x" * (MAX_ARTIFACT_CHARS + 1)}

    with pytest.raises(ArtifactGenerationError) as excinfo:
        parse_artifact(json.dumps(payload))

    assert str(MAX_ARTIFACT_CHARS) in str(excinfo.value)


def test_a_long_title_is_truncated() -> None:
    artifact = parse_artifact(
        json.dumps({"type": "markdown", "title": "T" * (MAX_TITLE_CHARS + 50), "content": "body"})
    )

    assert len(artifact.title) == MAX_TITLE_CHARS


def test_a_malformed_provider_answer_fails_the_capability(scripted_client, run_async) -> None:
    client = scripted_client(text="I could not build that artifact.")

    with pytest.raises(ArtifactGenerationError):
        run_async(ArtifactSkill().run({}, _context(client)))


def test_a_provider_failure_is_propagated(scripted_client, run_async) -> None:
    client = scripted_client(error=LLMUnavailableError("provider down", user_message="Provider down."))

    with pytest.raises(LLMUnavailableError):
        run_async(ArtifactSkill().run({}, _context(client)))


def test_a_missing_provider_is_an_actionable_error(run_async) -> None:
    with pytest.raises(LLMConfigurationError) as excinfo:
        run_async(ArtifactSkill().run({}, _context(None)))

    assert ".env" in excinfo.value.user_message


def test_artifact_types_are_normalized_and_detected() -> None:
    assert normalize_artifact_type(None) == ARTIFACT_TYPE_MARKDOWN
    assert normalize_artifact_type("MD") == ARTIFACT_TYPE_MARKDOWN
    assert normalize_artifact_type(" HTML ") == ARTIFACT_TYPE_HTML
    assert normalize_artifact_type("HTML/CSS") == ARTIFACT_TYPE_HTML
    with pytest.raises(ArtifactGenerationError):
        normalize_artifact_type("pdf")

    assert detect_artifact_type("Build a dashboard for retention") == ARTIFACT_TYPE_HTML
    assert detect_artifact_type("Write a strategy memo") == ARTIFACT_TYPE_MARKDOWN


def test_the_artifact_shape_stays_canonical() -> None:
    markdown = Artifact(type=ARTIFACT_TYPE_MARKDOWN, title="T", content="C")
    html = Artifact(type=ARTIFACT_TYPE_HTML, title="T", content="C", css="body{}")

    assert markdown.to_dict() == {"type": "markdown", "title": "T", "content": "C"}
    assert html.to_dict() == {"type": "html", "title": "T", "content": "C", "css": "body{}"}


def test_an_existing_document_can_be_wrapped_without_a_model_call() -> None:
    article = "# Retention before acquisition\n\nMost growth advice starts in the wrong place."

    artifact = build_wrapped_artifact(article)

    assert artifact.type == ARTIFACT_TYPE_MARKDOWN
    assert artifact.title == "Retention before acquisition"
    assert artifact.content == article
    assert artifact.to_dict() == {
        "type": ARTIFACT_TYPE_MARKDOWN,
        "title": "Retention before acquisition",
        "content": article,
    }


def test_a_wrapped_document_without_a_heading_gets_a_fallback_title() -> None:
    assert build_wrapped_artifact("Just a paragraph.").title == WRAPPED_ARTIFACT_FALLBACK_TITLE


def test_wrapping_empty_output_is_rejected() -> None:
    with pytest.raises(ArtifactGenerationError):
        build_wrapped_artifact("   \n  ")
