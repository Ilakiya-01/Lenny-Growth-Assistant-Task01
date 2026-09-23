"""Provider selection.

``LLM_MODE`` decides which concrete :class:`~app.llm.base.BaseLLMClient` the
application agent uses. Selection is explicit and configuration driven: an
invalid mode or a provider without usable configuration raises
:class:`~app.errors.LLMConfigurationError` instead of falling back to another
provider.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.config import Settings, get_settings
from app.errors import LLMConfigurationError
from app.llm.anthropic_client import AnthropicLLMClient
from app.llm.base import BaseLLMClient
from app.llm.ollama_client import OllamaLLMClient

logger = logging.getLogger("lenny.llm.factory")

MODE_CLOUD = "cloud"
MODE_OLLAMA = "ollama"

SUPPORTED_MODES: tuple[str, ...] = (MODE_CLOUD, MODE_OLLAMA)
MODE_ALIASES: dict[str, str] = {"local": MODE_OLLAMA}

_MODE_SUMMARY = "LLM_MODE must be 'cloud' or 'ollama' ('local' is accepted as an alias of 'ollama')"


def normalize_llm_mode(value: str | None, *, origin: str = "LLM_MODE") -> str:
    """Return the canonical provider mode for a configured or requested value."""
    candidate = (value or "").strip().lower()
    if not candidate:
        raise LLMConfigurationError(
            f"{origin} is empty. {_MODE_SUMMARY}.",
        )
    candidate = MODE_ALIASES.get(candidate, candidate)
    if candidate not in SUPPORTED_MODES:
        raise LLMConfigurationError(
            f"{origin}='{value}' is not a supported LLM mode. {_MODE_SUMMARY}.",
        )
    return candidate


def create_llm_client(*, settings: Settings | None = None, mode: str | None = None) -> BaseLLMClient:
    """Build the provider client for ``mode`` (default: the configured mode).

    ``mode`` exists for the per-request provider selection described in the
    architecture's LLM toggle flow; when it is omitted the environment decides.
    """
    settings = settings or get_settings()
    resolved = normalize_llm_mode(mode if mode is not None else settings.llm_mode)

    if resolved == MODE_CLOUD:
        if not (settings.anthropic_api_key or "").strip():
            raise LLMConfigurationError(
                "LLM_MODE=cloud requires ANTHROPIC_API_KEY. Set it in the repository root .env file. "
                "No other provider is used automatically.",
            )
        if not (settings.anthropic_model or "").strip():
            raise LLMConfigurationError(
                "LLM_MODE=cloud requires ANTHROPIC_MODEL. Set it in the repository root .env file.",
            )
        logger.info("LLM provider selected: %s (model=%s)", MODE_CLOUD, settings.anthropic_model)
        return AnthropicLLMClient(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    if not (settings.ollama_model or "").strip():
        raise LLMConfigurationError(
            "LLM_MODE=ollama requires OLLAMA_MODEL. Pull a model with `ollama pull <model>` and set "
            "OLLAMA_MODEL in the repository root .env file. No other provider is used automatically.",
        )
    logger.info("LLM provider selected: %s (model=%s)", MODE_OLLAMA, settings.ollama_model)
    return OllamaLLMClient(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
        num_ctx=settings.ollama_num_ctx or None,
    )


@lru_cache
def get_llm_client(mode: str | None = None) -> BaseLLMClient:
    """Return the process-wide provider client for the configured mode."""
    return create_llm_client(mode=mode)


__all__ = [
    "MODE_ALIASES",
    "MODE_CLOUD",
    "MODE_OLLAMA",
    "SUPPORTED_MODES",
    "create_llm_client",
    "get_llm_client",
    "normalize_llm_mode",
]
