"""Anthropic cloud provider built on the official ``anthropic`` SDK.

Only documented ``AsyncAnthropic.messages`` interfaces are used: ``create`` for
single generations and ``stream`` for incremental text. Credentials come from
configuration, are never logged, and provider exceptions are translated into the
project's structured LLM errors before they leave this module.

The pinned SDK version no longer accepts sampling parameters such as
``temperature`` on ``messages.create``/``messages.stream``, so the provider
neutral ``temperature`` argument is not forwarded here.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Sequence

import anthropic
from anthropic import AsyncAnthropic

from app.errors import (
    CLOUD_LLM_UNAVAILABLE_MESSAGE,
    LLMConfigurationError,
    LLMModelUnavailableError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.base import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    PROVIDER_ANTHROPIC,
    BaseLLMClient,
    LLMMessage,
    LLMResponse,
    LLMStreamChunk,
    LLMUsage,
    elapsed_seconds,
    sanitize_error_text,
    split_system_message,
    validate_turns,
)

logger = logging.getLogger("lenny.llm.anthropic")


class AnthropicLLMClient(BaseLLMClient):
    """Cloud generation through the Anthropic Messages API."""

    provider = PROVIDER_ANTHROPIC
    supports_streaming = True

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout_seconds: float | None = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = 1,
        client: AsyncAnthropic | None = None,
    ) -> None:
        super().__init__(model=model, timeout_seconds=timeout_seconds)

        if not (api_key or "").strip() and client is None:
            raise LLMConfigurationError(
                "ANTHROPIC_API_KEY is not set while LLM_MODE=cloud. "
                "Set a valid key in the repository root .env file.",
            )
        if max_tokens <= 0:
            raise LLMConfigurationError(
                f"ANTHROPIC_MAX_TOKENS must be greater than 0, got {max_tokens}.",
            )

        self._max_tokens = max_tokens
        self._client = client or AsyncAnthropic(
            api_key=api_key.strip(),
            timeout=self.timeout_seconds,
            max_retries=max(0, max_retries),
        )

    async def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        think: bool | None = None,
    ) -> LLMResponse:
        # ``think`` is the local runtime's reasoning switch; this provider has no
        # equivalent knob and ignores it when the shared interface passes one.
        system_text, turns = split_system_message(messages, system)
        validate_turns(turns, provider=self.provider)

        started = time.perf_counter()
        try:
            message = await self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens or self._max_tokens,
                messages=[turn.to_dict() for turn in turns],
                **({"system": system_text} if system_text else {}),
            )
        except Exception as exc:  # noqa: BLE001 - translated below into structured LLM errors
            raise self._translate_error(exc) from exc

        text = "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        ).strip()
        if not text:
            raise LLMResponseError(
                "The Anthropic API returned a message without text content.",
            )

        return LLMResponse(
            text=text,
            provider=self.provider,
            model=getattr(message, "model", self.model) or self.model,
            usage=LLMUsage(
                input_tokens=getattr(getattr(message, "usage", None), "input_tokens", None),
                output_tokens=getattr(getattr(message, "usage", None), "output_tokens", None),
            ),
            finish_reason=getattr(message, "stop_reason", None),
            duration_seconds=elapsed_seconds(started),
        )

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        think: bool | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        system_text, turns = split_system_message(messages, system)
        validate_turns(turns, provider=self.provider)

        try:
            async with self._client.messages.stream(
                model=self.model,
                max_tokens=max_tokens or self._max_tokens,
                messages=[turn.to_dict() for turn in turns],
                **({"system": system_text} if system_text else {}),
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield LLMStreamChunk(text=text, provider=self.provider, model=self.model)
                final = await stream.get_final_message()
        except Exception as exc:  # noqa: BLE001 - translated below into structured LLM errors
            raise self._translate_error(exc) from exc

        yield LLMStreamChunk(
            text="",
            provider=self.provider,
            model=getattr(final, "model", self.model) or self.model,
            done=True,
            usage=LLMUsage(
                input_tokens=getattr(getattr(final, "usage", None), "input_tokens", None),
                output_tokens=getattr(getattr(final, "usage", None), "output_tokens", None),
            ),
        )

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if close is None:
            return
        try:
            await close()
        except Exception as exc:  # noqa: BLE001 - shutdown must never mask the real result
            logger.debug("Ignoring error while closing the Anthropic client: %s", sanitize_error_text(str(exc)))

    def _translate_error(self, exc: Exception) -> Exception:
        """Map SDK exceptions onto the project's structured LLM errors."""
        detail = sanitize_error_text(f"{type(exc).__name__}: {exc}")

        if isinstance(exc, anthropic.APITimeoutError):
            logger.warning("Anthropic request timed out: %s", detail)
            return LLMTimeoutError(f"Anthropic request timed out: {detail}")

        if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            logger.error("Anthropic authentication failed: %s", detail)
            return LLMConfigurationError(
                f"Anthropic rejected the configured credentials: {detail}",
                user_message=(
                    "The configured cloud LLM credentials were rejected. Check ANTHROPIC_API_KEY and try again."
                ),
            )

        if isinstance(exc, anthropic.NotFoundError):
            logger.warning("Anthropic model not available: %s", detail)
            return LLMModelUnavailableError(
                f"Anthropic does not recognize the configured model '{self.model}': {detail}",
            )

        if isinstance(exc, anthropic.APIConnectionError):
            logger.warning("Anthropic is unreachable: %s", detail)
            return LLMUnavailableError(
                f"Anthropic is unreachable: {detail}",
                user_message=CLOUD_LLM_UNAVAILABLE_MESSAGE,
            )

        if isinstance(exc, anthropic.RateLimitError):
            logger.warning("Anthropic rate limit reached: %s", detail)
            return LLMUnavailableError(
                f"Anthropic rate limit reached: {detail}",
                user_message="The cloud LLM is rate limited right now. Please try again shortly.",
            )

        if isinstance(exc, anthropic.APIStatusError):
            logger.error("Anthropic returned an error status: %s", detail)
            return LLMResponseError(f"Anthropic returned an error response: {detail}")

        logger.error("Unexpected Anthropic client failure: %s", detail)
        return LLMUnavailableError(
            f"Unexpected Anthropic client failure: {detail}",
            user_message=CLOUD_LLM_UNAVAILABLE_MESSAGE,
        )


__all__ = ["AnthropicLLMClient"]
