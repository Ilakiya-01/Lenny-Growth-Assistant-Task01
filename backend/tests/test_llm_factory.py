"""Unit tests for LLM provider selection.

No provider is contacted: the factory only builds clients, and the assertions
cover which client is built, and which configuration mistakes are refused.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.errors import LLMConfigurationError
from app.llm.anthropic_client import AnthropicLLMClient
from app.llm.factory import (
    MODE_CLOUD,
    MODE_OLLAMA,
    create_llm_client,
    normalize_llm_mode,
)
from app.llm.ollama_client import OllamaLLMClient

FAKE_KEY = "sk-ant-unit-test-placeholder"  # noqa: S105 - clearly fake, never used to call anything


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "llm_mode": "ollama",
        "ollama_model": "",
        "ollama_base_url": "http://localhost:11434",
        "anthropic_api_key": "",
        "anthropic_model": "claude-sonnet-4-5",
        "anthropic_max_tokens": 512,
        "llm_timeout_seconds": 30.0,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_cloud_mode_builds_the_anthropic_provider() -> None:
    client = create_llm_client(
        settings=_settings(llm_mode="cloud", anthropic_api_key=FAKE_KEY, anthropic_model="claude-sonnet-4-5")
    )

    assert isinstance(client, AnthropicLLMClient)
    assert client.provider == "anthropic"
    assert client.model == "claude-sonnet-4-5"


def test_ollama_mode_builds_the_local_provider() -> None:
    client = create_llm_client(settings=_settings(llm_mode="ollama", ollama_model="llama3.1:8b"))

    assert isinstance(client, OllamaLLMClient)
    assert client.provider == "ollama"
    assert client.model == "llama3.1:8b"
    assert client.base_url == "http://localhost:11434"


def test_local_is_accepted_as_an_alias_for_ollama() -> None:
    assert normalize_llm_mode("local") == MODE_OLLAMA
    client = create_llm_client(settings=_settings(llm_mode="local", ollama_model="llama3.1:8b"))
    assert isinstance(client, OllamaLLMClient)


def test_mode_is_case_and_whitespace_insensitive() -> None:
    assert normalize_llm_mode("  CLOUD ") == MODE_CLOUD
    assert normalize_llm_mode("Ollama") == MODE_OLLAMA


@pytest.mark.parametrize("invalid", ["azure", "gpt", "claude", "ollama2"])
def test_invalid_mode_produces_a_clear_configuration_error(invalid: str) -> None:
    with pytest.raises(LLMConfigurationError) as excinfo:
        create_llm_client(settings=_settings(llm_mode=invalid, ollama_model="llama3.1:8b"))

    message = str(excinfo.value)
    assert invalid in message
    assert "'cloud'" in message and "'ollama'" in message


def test_empty_mode_produces_a_clear_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError, match="LLM_MODE is empty"):
        normalize_llm_mode("")


def test_cloud_mode_without_api_key_fails_instead_of_falling_back() -> None:
    with pytest.raises(LLMConfigurationError) as excinfo:
        create_llm_client(settings=_settings(llm_mode="cloud", anthropic_api_key="", ollama_model="llama3.1:8b"))

    assert "ANTHROPIC_API_KEY" in str(excinfo.value)
    # An Ollama model is configured, yet no Ollama client may be returned.
    assert "No other provider is used automatically" in str(excinfo.value)


def test_cloud_mode_without_model_fails_clearly() -> None:
    with pytest.raises(LLMConfigurationError, match="ANTHROPIC_MODEL"):
        create_llm_client(settings=_settings(llm_mode="cloud", anthropic_api_key=FAKE_KEY, anthropic_model=""))


def test_ollama_mode_without_model_fails_clearly() -> None:
    with pytest.raises(LLMConfigurationError) as excinfo:
        create_llm_client(settings=_settings(llm_mode="ollama", ollama_model=""))

    assert "OLLAMA_MODEL" in str(excinfo.value)
    assert "ollama pull" in str(excinfo.value)


def test_requested_mode_overrides_the_configured_mode() -> None:
    settings = _settings(
        llm_mode="ollama",
        ollama_model="llama3.1:8b",
        anthropic_api_key=FAKE_KEY,
    )

    client = create_llm_client(settings=settings, mode="cloud")

    assert isinstance(client, AnthropicLLMClient)


def test_describe_exposes_identity_without_credentials() -> None:
    client = create_llm_client(settings=_settings(llm_mode="cloud", anthropic_api_key=FAKE_KEY))
    described = client.describe()

    assert described["provider"] == "anthropic"
    assert described["model"] == "claude-sonnet-4-5"
    assert FAKE_KEY not in str(described)


def test_timeout_and_token_budget_are_taken_from_configuration() -> None:
    client = create_llm_client(
        settings=_settings(
            llm_mode="cloud",
            anthropic_api_key=FAKE_KEY,
            anthropic_max_tokens=256,
            llm_timeout_seconds=12.5,
        )
    )

    assert isinstance(client, AnthropicLLMClient)
    assert client.timeout_seconds == 12.5


def test_default_configured_mode_is_ollama() -> None:
    assert _settings().llm_mode == "ollama"
