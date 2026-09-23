"""Anthropic provider tests.

The real SDK builds the request and parses the response; only the HTTP transport
is mocked, so no network call and no paid API request is made.
"""

import json

import httpx2
import pytest

from app.errors import (
    LLMConfigurationError,
    LLMModelUnavailableError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.anthropic_client import AnthropicLLMClient
from app.llm.base import LLMMessage, PROVIDER_ANTHROPIC

#: Clearly fake value mirroring the shared fixture. Never a real credential.
TEST_API_KEY = "sk-ant-test-not-a-real-key"

MESSAGES = [LLMMessage(role="user", content="What is product-market fit?")]


def _message_body(text: str = "Product-market fit means the market pulls the product.") -> dict:
    return {
        "id": "msg_test_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 21, "output_tokens": 13},
    }


def _json_response(body: dict, status_code: int = 200) -> httpx2.Response:
    return httpx2.Response(status_code, json=body)


def _error_response(status_code: int, message: str = "provider failure") -> httpx2.Response:
    return httpx2.Response(status_code, json={"type": "error", "error": {"type": "invalid_request_error", "message": message}})


def _stream_response(frames: list[tuple[str, dict]]) -> httpx2.Response:
    body = "".join(f"event: {name}\ndata: {json.dumps(payload)}\n\n" for name, payload in frames)
    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, text=body)


def _sse_frames(*deltas: str) -> list[tuple[str, dict]]:
    message = _message_body()
    message["content"] = []
    message["usage"] = {"input_tokens": 21, "output_tokens": 1}
    frames: list[tuple[str, dict]] = [("message_start", {"type": "message_start", "message": message})]
    frames.append(
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
    )
    for delta in deltas:
        frames.append(
            (
                "content_block_delta",
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": delta}},
            )
        )
    frames.append(("content_block_stop", {"type": "content_block_stop", "index": 0}))
    frames.append(
        (
            "message_delta",
            {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 13}},
        )
    )
    frames.append(("message_stop", {"type": "message_stop"}))
    return frames


async def _collect(stream) -> list:
    return [chunk async for chunk in stream]


def test_generate_sends_documented_request_and_parses_response(anthropic_stub, run_async) -> None:
    captured: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        captured["api_key_header"] = request.headers.get("x-api-key")
        return _json_response(_message_body())

    client = anthropic_stub(handler)
    response = run_async(client.generate(MESSAGES, system="Answer in one sentence."))

    assert captured["path"] == "/v1/messages"
    assert captured["payload"]["model"] == "claude-sonnet-4-5"
    assert captured["payload"]["max_tokens"] == 2048
    assert captured["payload"]["system"] == "Answer in one sentence."
    assert captured["payload"]["messages"] == [{"role": "user", "content": MESSAGES[0].content}]
    assert captured["api_key_header"] == TEST_API_KEY

    assert response.provider == PROVIDER_ANTHROPIC
    assert response.model == "claude-sonnet-4-5"
    assert response.text == "Product-market fit means the market pulls the product."
    assert response.finish_reason == "end_turn"
    assert response.usage is not None
    assert response.usage.input_tokens == 21
    assert response.usage.output_tokens == 13
    assert response.usage.total_tokens == 34
    assert response.duration_seconds is not None


def test_sampling_parameters_are_not_sent_to_the_pinned_sdk(anthropic_stub, run_async) -> None:
    """The pinned SDK version has no ``temperature`` on the Messages API.

    The provider-neutral argument is therefore dropped for Anthropic instead of
    being sent as an unsupported request field.
    """
    captured: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["payload"] = json.loads(request.content)
        return _json_response(_message_body())

    client = anthropic_stub(handler)
    run_async(client.generate(MESSAGES, temperature=0.2))

    assert "temperature" not in captured["payload"]
    assert "top_p" not in captured["payload"]


def test_max_tokens_override_is_forwarded(anthropic_stub, run_async) -> None:
    captured: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["payload"] = json.loads(request.content)
        return _json_response(_message_body())

    client = anthropic_stub(handler, max_tokens=512)
    run_async(client.generate(MESSAGES, max_tokens=64))

    assert captured["payload"]["max_tokens"] == 64


def test_system_role_inside_messages_is_hoisted_out(anthropic_stub, run_async) -> None:
    captured: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["payload"] = json.loads(request.content)
        return _json_response(_message_body())

    client = anthropic_stub(handler)
    run_async(client.generate([LLMMessage(role="system", content="Be brief."), *MESSAGES]))

    assert captured["payload"]["system"] == "Be brief."
    assert captured["payload"]["messages"] == [{"role": "user", "content": MESSAGES[0].content}]


def test_request_without_user_turn_is_rejected_before_any_http_call(anthropic_stub, run_async) -> None:
    calls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request.url.path)
        return _json_response(_message_body())

    client = anthropic_stub(handler)
    with pytest.raises(LLMConfigurationError):
        run_async(client.generate([LLMMessage(role="system", content="Only instructions.")]))

    assert calls == []


def test_empty_text_response_is_reported_as_response_error(anthropic_stub, run_async) -> None:
    client = anthropic_stub(lambda request: _json_response(_message_body("")))
    with pytest.raises(LLMResponseError):
        run_async(client.generate(MESSAGES))


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, LLMConfigurationError),
        (403, LLMConfigurationError),
        (404, LLMModelUnavailableError),
        (429, LLMUnavailableError),
        (500, LLMResponseError),
        (502, LLMResponseError),
    ],
)
def test_http_status_errors_map_to_structured_llm_errors(anthropic_stub, run_async, status_code, expected) -> None:
    client = anthropic_stub(lambda request: _error_response(status_code))
    with pytest.raises(expected):
        run_async(client.generate(MESSAGES))


def test_connection_failure_maps_to_unavailable(anthropic_stub, run_async) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused")

    client = anthropic_stub(handler)
    with pytest.raises(LLMUnavailableError) as excinfo:
        run_async(client.generate(MESSAGES))

    assert excinfo.value.user_message
    assert TEST_API_KEY not in str(excinfo.value)


def test_timeout_maps_to_timeout_error(anthropic_stub, run_async) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timed out")

    client = anthropic_stub(handler)
    with pytest.raises(LLMTimeoutError):
        run_async(client.generate(MESSAGES))


def test_provider_error_text_never_exposes_the_api_key(anthropic_stub, run_async) -> None:
    client = anthropic_stub(
        lambda request: _error_response(401, f"invalid api_key={TEST_API_KEY} supplied")
    )
    with pytest.raises(LLMConfigurationError) as excinfo:
        run_async(client.generate(MESSAGES))

    error = excinfo.value
    assert TEST_API_KEY not in str(error)
    assert TEST_API_KEY not in error.detail
    assert TEST_API_KEY not in error.user_message


def test_stream_yields_incremental_text_then_a_final_chunk(anthropic_stub, run_async) -> None:
    client = anthropic_stub(lambda request: _stream_response(_sse_frames("Product", "-market ", "fit.")))
    chunks = run_async(_collect(client.stream(MESSAGES)))

    assert [chunk.text for chunk in chunks] == ["Product", "-market ", "fit.", ""]
    assert [chunk.done for chunk in chunks] == [False, False, False, True]
    assert all(chunk.provider == PROVIDER_ANTHROPIC for chunk in chunks)
    final = chunks[-1]
    assert final.usage is not None
    assert final.usage.output_tokens == 13


def test_streaming_failure_is_mapped_to_a_structured_error(anthropic_stub, run_async) -> None:
    client = anthropic_stub(lambda request: _error_response(500))
    with pytest.raises(LLMResponseError):
        run_async(_collect(client.stream(MESSAGES)))


def test_missing_api_key_without_injected_client_raises_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError) as excinfo:
        AnthropicLLMClient(api_key="", model="claude-sonnet-4-5")

    assert "ANTHROPIC_API_KEY" in str(excinfo.value)


def test_missing_model_raises_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError):
        AnthropicLLMClient(api_key=TEST_API_KEY, model="  ")


def test_describe_reports_identity_without_credentials(anthropic_stub) -> None:
    client = anthropic_stub(lambda request: _json_response(_message_body()))
    described = client.describe()

    assert described == {"provider": PROVIDER_ANTHROPIC, "model": "claude-sonnet-4-5", "streaming": "true"}
    assert TEST_API_KEY not in json.dumps(described)
