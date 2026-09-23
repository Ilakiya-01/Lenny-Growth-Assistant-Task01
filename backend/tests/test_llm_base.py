"""Common LLM interface tests: message model, usage math, redaction, defaults."""

from __future__ import annotations

import pytest

from app.errors import LLMConfigurationError
from app.llm.base import (
    PROVIDER_ANTHROPIC,
    PROVIDER_OLLAMA,
    BaseLLMClient,
    LLMMessage,
    LLMResponse,
    LLMStreamChunk,
    LLMUsage,
    sanitize_error_text,
    split_system_message,
    validate_turns,
)


class StaticClient(BaseLLMClient):
    """Client whose generation is fixed, used to check the shared defaults."""

    provider = "test"

    async def generate(self, messages, *, system=None, max_tokens=None, temperature=None, think=None) -> LLMResponse:
        return LLMResponse(text="complete text", provider=self.provider, model=self.model, usage=LLMUsage(1, 1))


async def _collect(stream) -> list[LLMStreamChunk]:
    return [chunk async for chunk in stream]


def test_llm_message_rejects_unknown_roles_and_non_string_content() -> None:
    with pytest.raises(ValueError):
        LLMMessage(role="tool", content="x")
    with pytest.raises(ValueError):
        LLMMessage(role="user", content=42)  # type: ignore[arg-type]


def test_llm_message_serializes_to_the_provider_shape() -> None:
    assert LLMMessage(role="assistant", content="hi").to_dict() == {"role": "assistant", "content": "hi"}


def test_usage_totals_and_serialization() -> None:
    assert LLMUsage(2, 3).total_tokens == 5
    assert LLMUsage(2, None).total_tokens == 2
    assert LLMUsage(None, None).total_tokens is None
    assert LLMUsage(2, 3).to_dict() == {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}


def test_split_system_message_merges_system_turns_and_keeps_order() -> None:
    system_text, turns = split_system_message(
        [
            LLMMessage(role="system", content="First instruction."),
            LLMMessage(role="user", content="q1"),
            LLMMessage(role="assistant", content="a1"),
        ],
        "Second instruction.",
    )

    assert system_text == "Second instruction.\n\nFirst instruction."
    assert [turn.role for turn in turns] == ["user", "assistant"]


def test_split_system_message_without_system_input_returns_none() -> None:
    system_text, turns = split_system_message([LLMMessage(role="user", content="q")], None)

    assert system_text is None
    assert len(turns) == 1


def test_validate_turns_requires_at_least_one_turn() -> None:
    with pytest.raises(LLMConfigurationError):
        validate_turns([], provider="ollama")


def test_sanitize_error_text_redacts_credentials() -> None:
    text = "401 from provider: api_key=sk-ant-abcdef123456 and bearer abcdefgh12345678 rejected"
    sanitized = sanitize_error_text(text)

    assert "sk-ant-abcdef123456" not in sanitized
    assert "abcdefgh12345678" not in sanitized
    assert "[redacted]" in sanitized


def test_sanitize_error_text_caps_length_and_collapses_whitespace() -> None:
    sanitized = sanitize_error_text("a\n\n b\t" + "x" * 1000, limit=50)

    assert len(sanitized) <= 53
    assert sanitized.endswith("...")
    assert "\n" not in sanitized


def test_sanitize_error_text_handles_empty_input() -> None:
    assert sanitize_error_text("") == ""


def test_base_client_requires_a_model() -> None:
    with pytest.raises(LLMConfigurationError):
        StaticClient(model="  ")

    assert StaticClient(model=" some-model ").model == "some-model"


def test_provider_constants_are_stable() -> None:
    assert (PROVIDER_ANTHROPIC, PROVIDER_OLLAMA) == ("anthropic", "ollama")


def test_default_stream_wraps_a_single_generation(run_async) -> None:
    client = StaticClient(model="test-model")
    chunks = run_async(_collect(client.stream([LLMMessage(role="user", content="hi")])))

    assert len(chunks) == 1
    assert chunks[0].text == "complete text"
    assert chunks[0].done is True
    assert chunks[0].usage is not None


def test_default_stream_chunk_type_is_shared_across_providers(run_async) -> None:
    client = StaticClient(model="test-model")
    chunk = run_async(_collect(client.stream([LLMMessage(role="user", content="hi")])))[0]

    assert isinstance(chunk, LLMStreamChunk)
    assert chunk.provider == "test"
    assert chunk.model == "test-model"


def test_client_describe_reports_no_credentials() -> None:
    assert StaticClient(model="test-model").describe() == {
        "provider": "test",
        "model": "test-model",
        "streaming": "false",
    }


def test_client_supports_async_context_management(run_async) -> None:
    closed: list[bool] = []

    class ClosingClient(StaticClient):
        async def aclose(self) -> None:
            closed.append(True)

    async def use() -> None:
        async with ClosingClient(model="test-model") as client:
            await client.generate([LLMMessage(role="user", content="hi")])

    run_async(use())
    assert closed == [True]
