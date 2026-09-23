"""Agent runtime tests.

The Claude Agent SDK runtime is exercised through an injected fake runner: the
real SDK cannot be driven here without the Claude Code CLI and cloud
credentials, and a paid API call must never be part of the test suite.
"""

from __future__ import annotations

import claude_agent_sdk
import pytest
from claude_agent_sdk import (
    AssistantMessage,
    CLINotFoundError,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
)

from app.agent.context import AgentContext, ConversationTurn
from app.agent.prompts import CONVERSATION_HISTORY_HEADER, CURRENT_REQUEST_HEADER
from app.agent.runtimes import (
    RUNTIME_CLAUDE_AGENT_SDK,
    RUNTIME_PROVIDER,
    ClaudeAgentRuntime,
    ProviderAgentRuntime,
    build_prompt,
)
from app.errors import LLMConfigurationError, LLMResponseError, LLMUnavailableError

MODEL = "claude-sonnet-4-5"


def _assistant(*blocks) -> AssistantMessage:
    return AssistantMessage(content=list(blocks), model=MODEL)


def _result(**overrides) -> ResultMessage:
    payload = {
        "subtype": "success",
        "duration_ms": 5,
        "duration_api_ms": 5,
        "is_error": False,
        "num_turns": 1,
        "session_id": "sdk-session",
        "result": None,
    }
    payload.update(overrides)
    return ResultMessage(**payload)


class FakeRunner:
    """Stand-in for ``claude_agent_sdk.query``."""

    def __init__(self, messages=(), error: Exception | None = None) -> None:
        self._messages = list(messages)
        self._error = error
        self.calls: list[dict] = []

    def __call__(self, *, prompt, options):
        self.calls.append({"prompt": prompt, "options": options})

        async def _iterate():
            if self._error is not None:
                raise self._error
            for message in self._messages:
                yield message

        return _iterate()


def test_provider_runtime_reuses_history_and_system_prompt(scripted_client, run_async) -> None:
    client = scripted_client(text="  Answered.  ")
    context = AgentContext(
        user_message="and what about retention?",
        history=(
            ConversationTurn(role="user", content="tell me about onboarding"),
            ConversationTurn(role="assistant", content="Onboarding matters."),
        ),
    )

    output = run_async(ProviderAgentRuntime(client).complete(context=context, system_prompt="SYSTEM"))

    assert output.reply == "Answered."
    assert output.provider == "fake"
    assert output.model == "fake-model"

    call = client.calls[0]
    assert call["system"] == "SYSTEM"
    assert [message.role for message in call["messages"]] == ["user", "assistant", "user"]
    assert call["messages"][-1].content == "and what about retention?"


def test_provider_runtime_reports_an_empty_reply(scripted_client, run_async) -> None:
    client = scripted_client(text="   ")

    with pytest.raises(LLMResponseError):
        run_async(ProviderAgentRuntime(client).complete(context=AgentContext(user_message="hi"), system_prompt="S"))


def test_runtime_names_are_distinct(scripted_client) -> None:
    assert ProviderAgentRuntime(scripted_client()).name == RUNTIME_PROVIDER
    assert ClaudeAgentRuntime().name == RUNTIME_CLAUDE_AGENT_SDK


def test_build_prompt_without_history_is_the_request_itself() -> None:
    assert build_prompt(AgentContext(user_message="just this")) == "just this"


def test_build_prompt_includes_history_and_the_current_request() -> None:
    prompt = build_prompt(
        AgentContext(
            user_message="follow-up",
            history=(ConversationTurn(role="user", content="first"), ConversationTurn(role="assistant", content="answer")),
        )
    )

    assert CONVERSATION_HISTORY_HEADER in prompt
    assert CURRENT_REQUEST_HEADER in prompt
    assert "user: first" in prompt
    assert "assistant: answer" in prompt
    assert prompt.rstrip().endswith("follow-up")


def test_claude_runtime_returns_only_text_blocks(run_async) -> None:
    runner = FakeRunner(
        messages=[
            _assistant(
                ThinkingBlock(thinking="private reasoning that must not be returned", signature="sig"),
                TextBlock(text="Public answer."),
            ),
            _result(),
        ]
    )
    runtime = ClaudeAgentRuntime(model=MODEL, api_key="sk-ant-test-not-a-real-key", runner=runner)

    output = run_async(runtime.complete(context=AgentContext(user_message="hi"), system_prompt="S"))

    assert output.reply == "Public answer."
    assert "private reasoning" not in output.reply
    assert output.provider == RUNTIME_CLAUDE_AGENT_SDK
    assert output.model == MODEL


def test_claude_runtime_falls_back_to_the_result_message_text(run_async) -> None:
    runner = FakeRunner(messages=[_result(result="Answer from the result message.")])
    runtime = ClaudeAgentRuntime(runner=runner)

    output = run_async(runtime.complete(context=AgentContext(user_message="hi"), system_prompt="S"))

    assert output.reply == "Answer from the result message."


def test_claude_runtime_usage_is_normalized(run_async) -> None:
    runner = FakeRunner(
        messages=[
            _assistant(TextBlock(text="ok")),
            _result(usage={"input_tokens": 11, "output_tokens": 7}),
        ]
    )
    runtime = ClaudeAgentRuntime(runner=runner)

    output = run_async(runtime.complete(context=AgentContext(user_message="hi"), system_prompt="S"))

    assert output.usage is not None
    assert output.usage.input_tokens == 11
    assert output.usage.output_tokens == 7


def test_claude_runtime_options_disable_tools_settings_skills_and_thinking() -> None:
    options = ClaudeAgentRuntime(model=MODEL).build_options("SYSTEM")

    assert options.system_prompt == "SYSTEM"
    assert options.tools == []
    assert options.allowed_tools == []
    assert options.setting_sources == []
    assert options.skills == []
    assert options.plugins == []
    assert options.max_turns == 1
    assert options.model == MODEL
    assert options.thinking == {"type": "disabled"}


def test_claude_runtime_passes_the_api_key_only_through_the_sdk_environment() -> None:
    key = "sk-ant-test-not-a-real-key"
    options = ClaudeAgentRuntime(model=MODEL, api_key=key).build_options("S")
    assert options.env == {"ANTHROPIC_API_KEY": key}

    without_key = ClaudeAgentRuntime(model=MODEL).build_options("S")
    assert without_key.env is None or "ANTHROPIC_API_KEY" not in (without_key.env or {})


def test_claude_runtime_rejects_an_empty_reply(run_async) -> None:
    runner = FakeRunner(messages=[_result()])

    with pytest.raises(LLMResponseError):
        run_async(ClaudeAgentRuntime(runner=runner).complete(context=AgentContext(user_message="hi"), system_prompt="S"))


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("authentication_failed", LLMConfigurationError),
        ("billing_error", LLMConfigurationError),
        ("rate_limit", LLMUnavailableError),
        ("server_error", LLMResponseError),
    ],
)
def test_claude_runtime_maps_assistant_errors(run_async, category, expected) -> None:
    runner = FakeRunner(messages=[_assistant(TextBlock(text="partial"))])
    runner._messages[0] = AssistantMessage(content=[TextBlock(text="partial")], model=MODEL, error=category)

    with pytest.raises(expected):
        run_async(ClaudeAgentRuntime(runner=runner).complete(context=AgentContext(user_message="hi"), system_prompt="S"))


def test_claude_runtime_reports_a_failed_result(run_async) -> None:
    runner = FakeRunner(messages=[_result(is_error=True, subtype="error_during_execution", errors=["boom"])])

    with pytest.raises(LLMResponseError):
        run_async(ClaudeAgentRuntime(runner=runner).complete(context=AgentContext(user_message="hi"), system_prompt="S"))


def test_claude_runtime_reports_missing_cli_as_unavailable_without_leaking_paths(run_async) -> None:
    error = CLINotFoundError("Claude Code not found at C:\\machine-specific\\path")
    runner = FakeRunner(error=error)

    with pytest.raises(LLMUnavailableError) as excinfo:
        run_async(ClaudeAgentRuntime(runner=runner).complete(context=AgentContext(user_message="hi"), system_prompt="S"))

    assert "LLM_MODE" in excinfo.value.user_message or "ollama" in excinfo.value.user_message.lower()
    assert "machine-specific" not in excinfo.value.user_message


def test_claude_runtime_reports_other_sdk_failures(run_async) -> None:
    runner = FakeRunner(error=claude_agent_sdk.ClaudeSDKError("unexpected sdk failure"))

    with pytest.raises(LLMResponseError):
        run_async(ClaudeAgentRuntime(runner=runner).complete(context=AgentContext(user_message="hi"), system_prompt="S"))
