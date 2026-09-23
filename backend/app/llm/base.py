"""Common LLM provider interface.

The application agent talks to models through :class:`BaseLLMClient` only. Cloud
and local execution are two implementations of this interface, selected by the
LLM factory - provider specific details never leak into the agent or the API.
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import ClassVar, Literal

from app.errors import LLMConfigurationError

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OLLAMA = "ollama"

LLMRole = Literal["system", "user", "assistant"]
LLM_ROLES: frozenset[str] = frozenset({"system", "user", "assistant"})

DEFAULT_MAX_TOKENS = 2048
DEFAULT_TIMEOUT_SECONDS = 120.0

_REDACTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|secret|password)\b\s*[=:]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
)


def sanitize_error_text(text: str, *, limit: int = 500) -> str:
    """Return provider error text that is safe to log.

    Provider exceptions can quote request headers or configuration. Anything
    that looks like a credential is replaced before the text reaches a log line,
    an activity event or an API response, and the result is length-capped.
    """
    sanitized = text or ""
    for pattern in _REDACTION_PATTERNS:
        sanitized = pattern.sub("[redacted]", sanitized)
    sanitized = " ".join(sanitized.split())
    if len(sanitized) > limit:
        sanitized = sanitized[:limit].rstrip() + "..."
    return sanitized


@dataclass(frozen=True, slots=True)
class LLMMessage:
    """One turn of a provider-agnostic conversation."""

    role: LLMRole
    content: str

    def __post_init__(self) -> None:
        if self.role not in LLM_ROLES:
            raise ValueError(f"Unsupported LLM message role: {self.role!r}")
        if not isinstance(self.content, str):
            raise ValueError("LLM message content must be a string")

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True, slots=True)
class LLMUsage:
    """Token accounting reported by a provider, when it reports any."""

    input_tokens: int | None = None
    output_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None and self.output_tokens is None:
            return None
        return (self.input_tokens or 0) + (self.output_tokens or 0)

    def to_dict(self) -> dict[str, int | None]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """A completed generation, normalized across providers."""

    text: str
    provider: str
    model: str
    usage: LLMUsage | None = None
    finish_reason: str | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class LLMStreamChunk:
    """One increment of a streamed generation."""

    text: str
    provider: str
    model: str
    done: bool = False
    usage: LLMUsage | None = None


class BaseLLMClient(ABC):
    """Asynchronous generation interface implemented by every provider.

    Subclasses must implement :meth:`generate`. Providers that expose a native
    streaming API override :meth:`stream`; the default implementation delegates
    to :meth:`generate` and yields the finished text as a single chunk, so all
    clients can be consumed through the same streaming interface.
    """

    provider: ClassVar[str] = "unknown"
    supports_streaming: ClassVar[bool] = False

    def __init__(self, *, model: str, timeout_seconds: float | None = None) -> None:
        model = (model or "").strip()
        if not model:
            raise LLMConfigurationError(
                f"No model is configured for the {self.provider} provider. "
                f"Set the corresponding model variable in the repository root .env file."
            )
        self._model = model
        self._timeout_seconds = float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS)

    @property
    def model(self) -> str:
        return self._model

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    @abstractmethod
    async def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        think: bool | None = None,
    ) -> LLMResponse:
        """Return one complete generation for ``messages``.

        ``think`` is an optional reasoning switch for providers that expose one.
        ``False`` asks the model to answer directly instead of spending part of
        the output budget on a private reasoning phase; providers without such a
        mode ignore it. Reasoning text is never returned as an answer, whichever
        way the switch is set.
        """

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        think: bool | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Yield the generation incrementally.

        Providers without a native streaming API fall back to a single chunk
        produced by :meth:`generate`.
        """
        response = await self.generate(
            messages, system=system, max_tokens=max_tokens, temperature=temperature, think=think
        )
        yield LLMStreamChunk(
            text=response.text,
            provider=response.provider,
            model=response.model,
            done=True,
            usage=response.usage,
        )

    async def aclose(self) -> None:
        """Release provider resources. Safe to call more than once."""

    async def __aenter__(self) -> BaseLLMClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def describe(self) -> dict[str, str]:
        """Return the non-sensitive provider identity used in activity events."""
        return {"provider": self.provider, "model": self.model, "streaming": str(self.supports_streaming).lower()}


def split_system_message(
    messages: Sequence[LLMMessage],
    system: str | None,
) -> tuple[str | None, list[LLMMessage]]:
    """Separate system instructions from conversational turns.

    A ``system`` role inside ``messages`` is merged into the returned system
    text; the returned list contains only user/assistant turns, which is what
    both provider APIs expect.
    """
    parts: list[str] = []
    if system and system.strip():
        parts.append(system.strip())

    turns: list[LLMMessage] = []
    for message in messages:
        if message.role == "system":
            if message.content.strip():
                parts.append(message.content.strip())
            continue
        turns.append(message)

    return ("\n\n".join(parts) if parts else None), turns


def validate_turns(turns: Sequence[LLMMessage], *, provider: str) -> None:
    """Ensure at least one conversational turn exists before calling a provider."""
    if not turns:
        raise LLMConfigurationError(
            f"A {provider} request needs at least one user or assistant message.",
            user_message="The request contained no message to send to the language model provider.",
        )


def elapsed_seconds(started: float) -> float:
    return round(time.perf_counter() - started, 3)


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_TIMEOUT_SECONDS",
    "LLM_ROLES",
    "PROVIDER_ANTHROPIC",
    "PROVIDER_OLLAMA",
    "BaseLLMClient",
    "LLMMessage",
    "LLMResponse",
    "LLMStreamChunk",
    "LLMUsage",
    "elapsed_seconds",
    "sanitize_error_text",
    "split_system_message",
    "validate_turns",
]
