"""Ollama provider tests.

The HTTP layer is mocked, so no local Ollama server is required and no network
call is made.
"""

import json

import httpx
import pytest

from app.errors import (
    LLMConfigurationError,
    LLMModelUnavailableError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.base import LLMMessage, PROVIDER_OLLAMA
from app.llm.ollama_client import CHAT_ENDPOINT, TAGS_ENDPOINT, OllamaLLMClient

MESSAGES = [LLMMessage(role="user", content="What did guests say about product-market fit?")]


def _chat_body(content: str = "The market pulls the product.", model: str = "llama3.1:8b") -> dict:
    return {
        "model": model,
        "created_at": "2026-01-01T00:00:00Z",
        "message": {"role": "assistant", "content": content},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 34,
        "eval_count": 21,
    }


def _json_response(body: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=body)


def _stream_response(lines: list[dict]) -> httpx.Response:
    body = "".join(f"{json.dumps(line)}\n" for line in lines)
    return httpx.Response(200, headers={"content-type": "application/x-ndjson"}, text=body)


async def _collect(stream) -> list:
    return [chunk async for chunk in stream]


def test_generate_sends_documented_request_and_normalizes_response(ollama_stub, run_async) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        return _json_response(_chat_body())

    client = ollama_stub(handler)
    response = run_async(client.generate(MESSAGES, system="Answer in one sentence.", temperature=0.1, max_tokens=256))

    assert captured["path"] == CHAT_ENDPOINT
    assert captured["payload"]["model"] == "llama3.1:8b"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["options"] == {"num_predict": 256, "temperature": 0.1}
    assert captured["payload"]["messages"] == [
        {"role": "system", "content": "Answer in one sentence."},
        {"role": "user", "content": MESSAGES[0].content},
    ]

    assert response.provider == PROVIDER_OLLAMA
    assert response.model == "llama3.1:8b"
    assert response.text == "The market pulls the product."
    assert response.finish_reason == "stop"
    assert response.usage is not None
    assert response.usage.input_tokens == 34
    assert response.usage.output_tokens == 21
    assert response.usage.total_tokens == 55
    assert response.duration_seconds is not None


def test_default_num_predict_matches_the_shared_default(ollama_stub, run_async) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return _json_response(_chat_body())

    client = ollama_stub(handler)
    run_async(client.generate(MESSAGES))

    assert captured["payload"]["options"] == {"num_predict": 2048}
    assert "think" not in captured["payload"]


def test_thinking_is_disabled_when_a_direct_answer_is_requested(ollama_stub, run_async) -> None:
    """A reasoning model otherwise spends the output budget on private thinking.

    Regression: the artifact and writing skills pass ``think=False`` so the whole
    generation budget produces answer text. The flag is a top-level payload key
    in Ollama's chat API, not an entry in ``options``.
    """
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return _json_response(_chat_body(content="# Title\n\nA complete artifact."))

    client = ollama_stub(handler)
    response = run_async(client.generate(MESSAGES, think=False))

    assert captured["payload"]["think"] is False
    assert "think" not in captured["payload"]["options"]
    assert response.text == "# Title\n\nA complete artifact."


def test_thinking_can_be_requested_and_is_forwarded(ollama_stub, run_async) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return _json_response(_chat_body())

    client = ollama_stub(handler)
    run_async(client.generate(MESSAGES, think=True))

    assert captured["payload"]["think"] is True


def test_thinking_flag_is_forwarded_when_streaming(ollama_stub, run_async) -> None:
    lines = [
        {"model": "llama3.1:8b", "message": {"role": "assistant", "content": "ok"}, "done": False},
        {"model": "llama3.1:8b", "message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"},
    ]
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return _stream_response(lines)

    client = ollama_stub(handler)
    run_async(_collect(client.stream(MESSAGES, think=False)))

    assert captured["payload"]["think"] is False


def test_the_context_window_is_only_sent_when_configured(ollama_stub, run_async) -> None:
    """The runtime default is kept unless a context window is configured explicitly."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return _json_response(_chat_body())

    default_client = ollama_stub(handler)
    run_async(default_client.generate(MESSAGES))
    assert "num_ctx" not in captured["payload"]["options"]
    assert default_client.num_ctx is None

    configured_client = ollama_stub(handler, num_ctx=8192)
    run_async(configured_client.generate(MESSAGES))
    assert captured["payload"]["options"]["num_ctx"] == 8192
    assert configured_client.num_ctx == 8192


def test_a_non_positive_context_window_is_rejected() -> None:
    with pytest.raises(LLMConfigurationError):
        OllamaLLMClient(model="llama3.1:8b", num_ctx=0)


def test_request_without_user_turn_is_rejected_before_any_http_call(ollama_stub, run_async) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return _json_response(_chat_body())

    client = ollama_stub(handler)
    with pytest.raises(LLMConfigurationError):
        run_async(client.generate([LLMMessage(role="system", content="Only instructions.")]))

    assert calls == []


def test_connection_failure_maps_to_unavailable_without_switching_provider(ollama_stub, run_async) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = ollama_stub(handler)
    with pytest.raises(LLMUnavailableError) as excinfo:
        run_async(client.generate(MESSAGES))

    assert "ollama" in excinfo.value.user_message.lower()


def test_connect_timeout_maps_to_unavailable(ollama_stub, run_async) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timed out")

    client = ollama_stub(handler)
    with pytest.raises(LLMUnavailableError):
        run_async(client.generate(MESSAGES))


def test_read_timeout_maps_to_timeout_error(ollama_stub, run_async) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    client = ollama_stub(handler)
    with pytest.raises(LLMTimeoutError):
        run_async(client.generate(MESSAGES))


def test_missing_model_is_reported_as_model_unavailable(ollama_stub, run_async) -> None:
    body = {"error": "model 'llama3.1:8b' not found, try pulling it first"}

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(body, status_code=404)

    client = ollama_stub(handler)
    with pytest.raises(LLMModelUnavailableError) as excinfo:
        run_async(client.generate(MESSAGES))

    assert "ollama pull llama3.1:8b" in excinfo.value.user_message


def test_server_error_is_reported_as_response_error(ollama_stub, run_async) -> None:
    client = ollama_stub(lambda request: _json_response({"error": "internal failure"}, status_code=500))
    with pytest.raises(LLMResponseError):
        run_async(client.generate(MESSAGES))


@pytest.mark.parametrize(
    "body",
    [
        {"done": True},
        {"message": "not-an-object"},
        {"message": {"role": "assistant", "content": 42}},
        {"message": {"role": "assistant", "content": "   "}},
    ],
)
def test_malformed_responses_are_rejected(ollama_stub, run_async, body) -> None:
    client = ollama_stub(lambda request: _json_response(body))
    with pytest.raises(LLMResponseError):
        run_async(client.generate(MESSAGES))


def test_a_reasoning_model_that_never_answers_is_reported_as_a_token_budget_problem(ollama_stub, run_async) -> None:
    body = {
        "model": "qwen3:4b",
        "message": {"role": "assistant", "content": "", "thinking": "private reasoning that is never returned"},
        "done": True,
        "done_reason": "length",
        "eval_count": 64,
    }
    client = ollama_stub(lambda request: _json_response(body))

    with pytest.raises(LLMResponseError) as excinfo:
        run_async(client.generate(MESSAGES, max_tokens=64))

    assert "budget" in excinfo.value.user_message
    assert "private reasoning" not in str(excinfo.value)
    assert "private reasoning" not in excinfo.value.user_message


def test_non_json_response_is_rejected(ollama_stub, run_async) -> None:
    client = ollama_stub(lambda request: httpx.Response(200, text="<html>not json</html>"))
    with pytest.raises(LLMResponseError):
        run_async(client.generate(MESSAGES))


def test_stream_yields_incremental_text_then_a_final_chunk(ollama_stub, run_async) -> None:
    lines = [
        {"model": "llama3.1:8b", "message": {"role": "assistant", "content": "Product"}, "done": False},
        {"model": "llama3.1:8b", "message": {"role": "assistant", "content": "-market "}, "done": False},
        {"model": "llama3.1:8b", "message": {"role": "assistant", "content": "fit."}, "done": False},
        {"model": "llama3.1:8b", "message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop", "prompt_eval_count": 34, "eval_count": 21},
    ]
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return _stream_response(lines)

    client = ollama_stub(handler)
    chunks = run_async(_collect(client.stream(MESSAGES)))

    assert captured["payload"]["stream"] is True
    assert [chunk.text for chunk in chunks] == ["Product", "-market ", "fit.", ""]
    assert [chunk.done for chunk in chunks] == [False, False, False, True]
    assert all(chunk.provider == PROVIDER_OLLAMA for chunk in chunks)
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.output_tokens == 21


def test_stream_with_a_malformed_frame_is_rejected(ollama_stub, run_async) -> None:
    client = ollama_stub(lambda request: httpx.Response(200, text='{"message": {"content": "ok"}}\nnot-json\n'))
    with pytest.raises(LLMResponseError):
        run_async(_collect(client.stream(MESSAGES)))


def test_stream_error_frame_is_rejected(ollama_stub, run_async) -> None:
    client = ollama_stub(lambda request: _stream_response([{"error": "model failed to load"}]))
    with pytest.raises(LLMResponseError):
        run_async(_collect(client.stream(MESSAGES)))


def test_stream_http_error_is_translated(ollama_stub, run_async) -> None:
    client = ollama_stub(lambda request: _json_response({"error": "model not found"}, status_code=404))
    with pytest.raises(LLMModelUnavailableError):
        run_async(_collect(client.stream(MESSAGES)))


def test_list_models_and_has_model(ollama_stub, run_async) -> None:
    body = {"models": [{"name": "llama3.1:8b", "model": "llama3.1:8b"}, {"name": "mistral:7b", "model": "mistral:7b"}]}
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return _json_response(body)

    client = ollama_stub(handler)

    assert run_async(client.list_models()) == ("llama3.1:8b", "mistral:7b")
    assert captured["path"] == TAGS_ENDPOINT
    assert run_async(client.has_model()) is True
    assert run_async(client.has_model("mistral")) is True
    assert run_async(client.has_model("qwen2.5:32b")) is False


def test_list_models_rejects_a_malformed_listing(ollama_stub, run_async) -> None:
    client = ollama_stub(lambda request: _json_response({"models": "nope"}))
    with pytest.raises(LLMResponseError):
        run_async(client.list_models())


def test_list_models_reports_an_unreachable_server(ollama_stub, run_async) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = ollama_stub(handler)
    with pytest.raises(LLMUnavailableError):
        run_async(client.list_models())


def test_missing_base_url_raises_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError):
        OllamaLLMClient(model="llama3.1:8b", base_url="")


def test_missing_model_raises_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError):
        OllamaLLMClient(model="")


def test_describe_reports_identity_and_base_url_stays_configurable(ollama_stub) -> None:
    client = ollama_stub(lambda request: _json_response(_chat_body()))

    assert client.describe() == {"provider": PROVIDER_OLLAMA, "model": "llama3.1:8b", "streaming": "true"}
    assert client.base_url == "http://localhost:11434"
