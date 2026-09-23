"""Local provider that talks to an Ollama instance over its HTTP API.

Ollama is called directly through httpx (``/api/chat``, ``/api/tags`` and
``/api/show``) rather than through the Claude Agent SDK: the SDK targets the
Anthropic runtime, so the local mode has its own explicit implementation behind
the shared :class:`~app.llm.base.BaseLLMClient` interface.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Sequence

import httpx

from app.errors import (
    OLLAMA_UNAVAILABLE_MESSAGE,
    LLMConfigurationError,
    LLMModelUnavailableError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.base import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    PROVIDER_OLLAMA,
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

logger = logging.getLogger("lenny.llm.ollama")

CHAT_ENDPOINT = "/api/chat"
TAGS_ENDPOINT = "/api/tags"
SHOW_ENDPOINT = "/api/show"
DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaLLMClient(BaseLLMClient):
    """Local generation through a running Ollama server."""

    provider = PROVIDER_OLLAMA
    supports_streaming = True

    def __init__(
        self,
        *,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float | None = DEFAULT_TIMEOUT_SECONDS,
        num_ctx: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(model=model, timeout_seconds=timeout_seconds)

        base_url = (base_url or "").strip()
        if not base_url and client is None:
            raise LLMConfigurationError(
                "OLLAMA_BASE_URL is not set while LLM_MODE=ollama. Set it in the repository root .env file.",
            )

        if num_ctx is not None and num_ctx <= 0:
            raise LLMConfigurationError(
                f"OLLAMA_NUM_CTX must be a positive token count when set, got {num_ctx}.",
            )

        self._base_url = (base_url or str(getattr(client, "base_url", ""))).rstrip("/")
        self._num_ctx = num_ctx
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self.timeout_seconds, connect=10.0),
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def num_ctx(self) -> int | None:
        """The configured context window, or ``None`` for the runtime default."""
        return self._num_ctx

    async def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        think: bool | None = None,
    ) -> LLMResponse:
        system_text, turns = split_system_message(messages, system)
        validate_turns(turns, provider=self.provider)

        payload = self._chat_payload(turns, system_text, max_tokens, temperature, stream=False, think=think)
        started = time.perf_counter()
        data = await self._post_json(CHAT_ENDPOINT, payload)

        message = data.get("message")
        if not isinstance(message, dict):
            raise self._malformed("the response had no 'message' object")
        content = message.get("content")
        if not isinstance(content, str):
            raise self._malformed("the response 'message.content' was not a string")
        if not content.strip():
            # A reasoning model (for example qwen3) can spend the whole token
            # budget on its private thinking and return no answer text at all.
            # That thinking is never used as an answer here.
            if data.get("done_reason") == "length":
                logger.warning(
                    "Ollama stopped at the token limit before returning any answer text (model=%s)",
                    self.model,
                )
                raise LLMResponseError(
                    "Ollama exhausted the token budget before returning any answer text.",
                    user_message=(
                        f"The local model '{self.model}' used the whole token budget without returning an answer. "
                        "Disable its thinking mode, raise the token limit, or configure a model that does not "
                        "spend the budget on reasoning."
                    ),
                )
            raise self._malformed("the response 'message.content' was empty")

        return LLMResponse(
            text=content.strip(),
            provider=self.provider,
            model=str(data.get("model") or self.model),
            usage=self._usage_from(data),
            finish_reason=data.get("done_reason") if isinstance(data.get("done_reason"), str) else None,
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

        payload = self._chat_payload(turns, system_text, max_tokens, temperature, stream=True, think=think)

        try:
            async with self._client.stream("POST", CHAT_ENDPOINT, json=payload) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise self._translate_http_error(response.status_code, body)
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        frame = json.loads(line)
                    except json.JSONDecodeError:
                        raise self._malformed("a streamed frame was not valid JSON") from None
                    if not isinstance(frame, dict):
                        raise self._malformed("a streamed frame was not a JSON object")
                    if "error" in frame:
                        raise self._malformed(f"the provider reported: {frame['error']}")
                    chunk_message = frame.get("message")
                    text = chunk_message.get("content") if isinstance(chunk_message, dict) else None
                    if frame.get("done") is True:
                        yield LLMStreamChunk(
                            text="",
                            provider=self.provider,
                            model=str(frame.get("model") or self.model),
                            done=True,
                            usage=self._usage_from(frame),
                        )
                        return
                    if isinstance(text, str) and text:
                        yield LLMStreamChunk(text=text, provider=self.provider, model=self.model)
        except Exception as exc:  # noqa: BLE001 - translated below into structured LLM errors
            if isinstance(exc, (LLMUnavailableError, LLMResponseError, LLMModelUnavailableError, LLMTimeoutError)):
                raise
            raise self._translate_error(exc) from exc

    async def list_models(self) -> tuple[str, ...]:
        """Return the model names installed in the configured Ollama instance."""
        data = await self._request_json("GET", TAGS_ENDPOINT, None)
        models = data.get("models")
        if not isinstance(models, list):
            raise self._malformed("the model listing had no 'models' array")
        names: list[str] = []
        for entry in models:
            if isinstance(entry, dict):
                name = entry.get("model") or entry.get("name")
                if isinstance(name, str) and name:
                    names.append(name)
        return tuple(names)

    async def has_model(self, model: str | None = None) -> bool:
        """Return True when the configured (or given) model is installed locally."""
        wanted = (model or self.model).strip()
        installed = await self.list_models()
        return any(name == wanted or name.split(":")[0] == wanted.split(":")[0] for name in installed)

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except Exception as exc:  # noqa: BLE001 - shutdown must never mask the real result
            logger.debug("Ignoring error while closing the Ollama client: %s", sanitize_error_text(str(exc)))

    def _chat_payload(
        self,
        turns: Sequence[LLMMessage],
        system_text: str | None,
        max_tokens: int | None,
        temperature: float | None,
        *,
        stream: bool,
        think: bool | None = None,
    ) -> dict[str, object]:
        messages: list[dict[str, str]] = []
        if system_text:
            messages.append({"role": "system", "content": system_text})
        messages.extend(turn.to_dict() for turn in turns)

        options: dict[str, object] = {"num_predict": max_tokens or DEFAULT_MAX_TOKENS}
        if temperature is not None:
            options["temperature"] = temperature
        if self._num_ctx is not None:
            # Ollama loads every model with a default context window (4096
            # tokens for the installed qwen3 build, well below what the model
            # itself supports). Raising it costs KV-cache memory, so it is opt-in
            # through configuration rather than set to the model's maximum.
            options["num_ctx"] = self._num_ctx

        payload: dict[str, object] = {"model": self.model, "messages": messages, "stream": stream, "options": options}
        if think is not None:
            # Top-level in Ollama's chat API, not part of ``options``. Sending
            # False on a reasoning model stops it from spending the output
            # budget on private thinking that is never returned as an answer.
            payload["think"] = think
        return payload

    async def _post_json(self, endpoint: str, payload: dict[str, object]) -> dict[str, object]:
        return await self._request_json("POST", endpoint, payload)

    async def _request_json(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, object] | None,
    ) -> dict[str, object]:
        try:
            response = await self._client.request(method, endpoint, json=payload)
        except Exception as exc:  # noqa: BLE001 - translated below into structured LLM errors
            raise self._translate_error(exc) from exc

        if response.status_code >= 400:
            raise self._translate_http_error(response.status_code, response.content)

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise self._malformed(f"the response was not valid JSON ({sanitize_error_text(str(exc))})") from exc

        if not isinstance(data, dict):
            raise self._malformed("the response was not a JSON object")
        if isinstance(data.get("error"), str):
            raise self._malformed(f"the provider reported: {data['error']}")
        return data

    def _translate_http_error(self, status_code: int, body: bytes) -> Exception:
        detail = sanitize_error_text(body.decode("utf-8", errors="replace")) if body else ""
        lowered = detail.lower()

        if status_code == 404 or "not found" in lowered or "no such model" in lowered:
            logger.warning("Ollama model '%s' is not installed (HTTP %s): %s", self.model, status_code, detail)
            return LLMModelUnavailableError(
                f"Ollama does not have the model '{self.model}' installed (HTTP {status_code}): {detail}",
                user_message=(
                    f"The local model '{self.model}' is not installed in Ollama. "
                    f"Run `ollama pull {self.model}` and try again."
                ),
            )

        logger.error("Ollama returned HTTP %s: %s", status_code, detail)
        return LLMResponseError(
            f"Ollama returned HTTP {status_code}: {detail}",
            user_message="The local model returned an error. Check the Ollama server log and try again.",
        )

    def _translate_error(self, exc: Exception) -> Exception:
        detail = sanitize_error_text(f"{type(exc).__name__}: {exc}")

        if isinstance(exc, httpx.ConnectTimeout):
            logger.warning("Timed out connecting to Ollama at %s: %s", self._base_url, detail)
            return LLMUnavailableError(
                f"Timed out connecting to Ollama at {self._base_url}: {detail}",
                user_message=OLLAMA_UNAVAILABLE_MESSAGE,
            )

        if isinstance(exc, httpx.TimeoutException):
            logger.warning("Ollama request timed out: %s", detail)
            return LLMTimeoutError(f"Ollama request timed out: {detail}")

        if isinstance(exc, httpx.TransportError):
            logger.warning("Ollama is unreachable at %s: %s", self._base_url, detail)
            return LLMUnavailableError(
                f"Ollama is unreachable at {self._base_url}: {detail}",
                user_message=OLLAMA_UNAVAILABLE_MESSAGE,
            )

        logger.error("Unexpected Ollama client failure: %s", detail)
        return LLMUnavailableError(
            f"Unexpected Ollama client failure: {detail}",
            user_message=OLLAMA_UNAVAILABLE_MESSAGE,
        )

    def _malformed(self, reason: str) -> LLMResponseError:
        logger.error("Ollama returned a malformed response: %s", reason)
        return LLMResponseError(
            f"Ollama returned a malformed response: {reason}",
            user_message="The local model returned an unusable response. Please try again.",
        )

    def _usage_from(self, data: dict[str, object]) -> LLMUsage | None:
        input_tokens = data.get("prompt_eval_count")
        output_tokens = data.get("eval_count")
        if input_tokens is None and output_tokens is None:
            return None
        return LLMUsage(
            input_tokens=int(input_tokens) if isinstance(input_tokens, int) else None,
            output_tokens=int(output_tokens) if isinstance(output_tokens, int) else None,
        )


__all__ = ["DEFAULT_BASE_URL", "OllamaLLMClient"]
