"""Agent runtimes: how a prepared plan is turned into a reply.

There are two runtimes because the two provider modes have genuinely different
runtime requirements:

* :class:`ClaudeAgentRuntime` uses the Anthropic Claude Agent SDK, the approved
  runtime for the application agent. The SDK drives the agentic loop and is
  where the Phase 4 skills would be exposed as SDK tools for cloud mode.
* :class:`ProviderAgentRuntime` calls the configured :class:`BaseLLMClient`
  directly. It is the runtime for local Ollama execution, because the Claude
  Agent SDK targets the Anthropic runtime and cannot simply be pointed at
  Ollama.

Both produce the same :class:`AgentRunOutput`, so the agent and the API do not
care which one ran.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import claude_agent_sdk
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    CLINotFoundError,
    ResultMessage,
    TextBlock,
    ThinkingConfigDisabled,
)

from app.agent.context import AgentContext
from app.agent.prompts import CONVERSATION_HISTORY_HEADER, CURRENT_REQUEST_HEADER
from app.errors import (
    CLOUD_LLM_UNAVAILABLE_MESSAGE,
    LLMConfigurationError,
    LLMResponseError,
    LLMUnavailableError,
)
from app.llm.base import BaseLLMClient, LLMMessage, LLMUsage, sanitize_error_text

logger = logging.getLogger("lenny.agent.runtime")

RUNTIME_CLAUDE_AGENT_SDK = "claude-agent-sdk"
RUNTIME_PROVIDER = "llm-provider"

DEFAULT_MAX_TURNS = 1


@dataclass(frozen=True, slots=True)
class AgentRunOutput:
    """Normalized result of one agent turn."""

    reply: str
    provider: str
    model: str | None = None
    usage: LLMUsage | None = None


class AgentRuntime(Protocol):
    """Turns a request into a reply using one provider mode."""

    name: str

    async def complete(self, *, context: AgentContext, system_prompt: str) -> AgentRunOutput:
        """Produce the reply for ``context``."""


def build_prompt(context: AgentContext) -> str:
    """Flatten the session history and the request into one prompt.

    The Claude Agent SDK takes a single prompt string; embedding prior turns
    keeps the conversation context available without starting a new SDK session
    per request.
    """
    if not context.history:
        return context.user_message

    lines = [CONVERSATION_HISTORY_HEADER]
    lines.extend(f"{turn.role}: {turn.content}" for turn in context.history)
    lines.append(f"{CURRENT_REQUEST_HEADER} {context.user_message}")
    return "\n".join(lines)


class ProviderAgentRuntime:
    """Agent turn executed through the configured LLM provider client."""

    name = RUNTIME_PROVIDER

    def __init__(self, client: BaseLLMClient) -> None:
        self._client = client

    @property
    def client(self) -> BaseLLMClient:
        return self._client

    async def complete(self, *, context: AgentContext, system_prompt: str) -> AgentRunOutput:
        messages = [turn.to_llm_message() for turn in context.history]
        messages.append(LLMMessage(role="user", content=context.user_message))

        response = await self._client.generate(messages, system=system_prompt)
        if not response.text.strip():
            raise LLMResponseError(
                f"The {self._client.provider} provider returned an empty reply.",
            )
        return AgentRunOutput(
            reply=response.text.strip(),
            provider=response.provider,
            model=response.model,
            usage=response.usage,
        )


class ClaudeAgentRuntime:
    """Agent turn executed by the Anthropic Claude Agent SDK.

    The SDK spawns the Claude Code runtime, so this runtime needs the CLI to be
    installed and usable credentials to be configured. It is the cloud-mode
    counterpart of :class:`ProviderAgentRuntime`; ``tools`` and ``allowed_tools``
    are empty, so the turn is a single text answer. Capability execution is
    driven by the agent's execution plan, not by SDK tool permissions.
    """

    name = RUNTIME_CLAUDE_AGENT_SDK

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        max_turns: int = DEFAULT_MAX_TURNS,
        runner: Any | None = None,
    ) -> None:
        self._model = (model or "").strip() or None
        self._api_key = (api_key or "").strip() or None
        self._max_turns = max_turns
        self._runner = runner or claude_agent_sdk.query

    def build_options(self, system_prompt: str) -> ClaudeAgentOptions:
        """Options for one isolated, tool-free agent turn."""
        kwargs: dict[str, Any] = {
            "system_prompt": system_prompt,
            "tools": [],
            "allowed_tools": [],
            "max_turns": self._max_turns,
            # No filesystem settings, skills or plugins: the product runtime must
            # not inherit whatever happens to be configured on the machine.
            "setting_sources": [],
            "skills": [],
            "plugins": [],
            "thinking": ThinkingConfigDisabled(type="disabled"),
            "model": self._model,
        }
        if self._api_key:
            kwargs["env"] = {"ANTHROPIC_API_KEY": self._api_key}
        return ClaudeAgentOptions(**kwargs)

    async def complete(self, *, context: AgentContext, system_prompt: str) -> AgentRunOutput:
        options = self.build_options(system_prompt)
        texts: list[str] = []
        usage: LLMUsage | None = None
        model = self._model

        try:
            async for message in self._runner(prompt=build_prompt(context), options=options):
                if isinstance(message, AssistantMessage):
                    self._raise_for_assistant_error(message)
                    # Only text blocks are read. Any thinking block the runtime
                    # produced is deliberately dropped, never forwarded.
                    texts.extend(
                        block.text for block in message.content if isinstance(block, TextBlock) and block.text
                    )
                    if message.usage:
                        usage = _usage_from_sdk(message.usage) or usage
                elif isinstance(message, ResultMessage):
                    if message.is_error:
                        raise self._error_from_result(message)
                    if not texts and isinstance(message.result, str) and message.result.strip():
                        texts.append(message.result)
                    if message.usage:
                        usage = _usage_from_sdk(message.usage) or usage
        except claude_agent_sdk.ClaudeSDKError as exc:
            raise self._translate_sdk_error(exc) from exc

        reply = "".join(texts).strip()
        if not reply:
            raise LLMResponseError("The Claude Agent SDK completed without returning any text.",
                                   user_message="The cloud agent runtime returned an empty response. Please try again.")
        return AgentRunOutput(reply=reply, provider=self.name, model=model, usage=usage)

    def _raise_for_assistant_error(self, message: AssistantMessage) -> None:
        error = getattr(message, "error", None)
        if error in (None, ""):
            return
        raise self._error_for_category(str(error))

    def _error_for_category(self, category: str) -> Exception:
        logger.warning("Claude Agent SDK assistant error: %s", category)
        if category in {"authentication_failed", "billing_error"}:
            return LLMConfigurationError(
                f"The cloud agent runtime reported '{category}'. Check the configured credentials.",
                user_message=(
                    "The configured cloud LLM credentials were rejected or the account cannot be billed. "
                    "Check ANTHROPIC_API_KEY and try again."
                ),
            )
        if category == "rate_limit":
            return LLMUnavailableError(
                f"The cloud agent runtime reported '{category}'.",
                user_message="The cloud LLM is rate limited right now. Please try again shortly.",
            )
        return LLMResponseError(
            f"The cloud agent runtime reported '{category}'.",
            user_message="The cloud LLM returned an error. Please try again.",
        )

    def _error_from_result(self, message: ResultMessage) -> Exception:
        detail = sanitize_error_text(
            "; ".join(str(item) for item in (message.errors or []))
            or str(message.result or "")
            or str(message.subtype)
        )
        logger.error("Claude Agent SDK result error (%s): %s", message.subtype, detail)
        if message.api_error_status in {401, 403}:
            return LLMConfigurationError(
                f"The cloud agent runtime rejected the request (HTTP {message.api_error_status}): {detail}",
                user_message=(
                    "The configured cloud LLM credentials were rejected. Check ANTHROPIC_API_KEY and try again."
                ),
            )
        return LLMResponseError(
            f"The cloud agent runtime failed ({message.subtype}): {detail}",
        )

    def _translate_sdk_error(self, exc: Exception) -> Exception:
        detail = sanitize_error_text(f"{type(exc).__name__}: {exc}")

        if isinstance(exc, CLINotFoundError):
            logger.error("Claude Agent SDK runtime is not installed: %s", detail)
            return LLMUnavailableError(
                "The Claude Agent SDK runtime could not find the Claude Code CLI: " f"{detail}",
                user_message=(
                    "The cloud agent runtime is not available on this machine: the Claude Code runtime was "
                    "not found. Install it, or switch LLM_MODE to 'ollama' for local execution."
                ),
            )

        if isinstance(exc, claude_agent_sdk.CLIConnectionError):
            logger.warning("Claude Agent SDK runtime could not be reached: %s", detail)
            return LLMUnavailableError(
                f"The Claude Agent SDK runtime could not be reached: {detail}",
                user_message=CLOUD_LLM_UNAVAILABLE_MESSAGE,
            )

        logger.error("Claude Agent SDK failure: %s", detail)
        return LLMResponseError(f"The Claude Agent SDK failed: {detail}")


def _usage_from_sdk(usage: Any) -> LLMUsage | None:
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if not isinstance(input_tokens, int) and not isinstance(output_tokens, int):
        return None
    return LLMUsage(
        input_tokens=input_tokens if isinstance(input_tokens, int) else None,
        output_tokens=output_tokens if isinstance(output_tokens, int) else None,
    )


__all__ = [
    "DEFAULT_MAX_TURNS",
    "RUNTIME_CLAUDE_AGENT_SDK",
    "RUNTIME_PROVIDER",
    "AgentRunOutput",
    "AgentRuntime",
    "ClaudeAgentRuntime",
    "ProviderAgentRuntime",
    "build_prompt",
]
