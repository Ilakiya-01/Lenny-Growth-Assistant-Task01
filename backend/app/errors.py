"""Application errors and their HTTP representation."""

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError

logger = logging.getLogger("lenny.errors")


class SessionNotFoundError(Exception):
    """Raised when a session id does not exist."""

    def __init__(self, session_id: uuid.UUID) -> None:
        self.session_id = session_id
        super().__init__(f"Session {session_id} was not found.")


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when a database operation is attempted without DATABASE_URL."""


class TranscriptSourceError(RuntimeError):
    """Raised when the configured transcript repository cannot be used."""


class TranscriptParseError(ValueError):
    """Raised when a transcript file cannot be parsed."""


class EmbeddingProviderError(RuntimeError):
    """Raised when the configured embedding provider cannot be used."""


class EmbeddingDimensionMismatchError(RuntimeError):
    """Raised when the model dimension does not match the database column."""


class LLMError(RuntimeError):
    """Base class for LLM provider and agent runtime failures.

    ``str(error)`` is the internal, log-only detail; ``user_message`` is the
    safe, actionable text that may be returned to a client. Neither may contain
    credentials or internal stack traces.
    """

    user_message = "The language model provider is unavailable. Please try again."

    def __init__(self, detail: str = "", *, user_message: str | None = None) -> None:
        super().__init__(detail or self.user_message)
        self.detail = detail
        if user_message is not None:
            self.user_message = user_message


class LLMConfigurationError(LLMError):
    """Raised when LLM configuration is missing, invalid or inconsistent."""

    user_message = "The LLM configuration is incomplete. Check the LLM settings in the repository root .env file."


class LLMUnavailableError(LLMError):
    """Raised when the configured provider cannot be reached."""

    user_message = "The configured language model provider is unavailable. Please try again."


class LLMTimeoutError(LLMUnavailableError):
    """Raised when the configured provider did not answer in time."""

    user_message = "The language model provider did not respond in time. Please try again."


class LLMModelUnavailableError(LLMError):
    """Raised when the configured model is unknown to the provider."""

    user_message = "The configured language model is not available on the provider. Check LLM model configuration."


class LLMResponseError(LLMError):
    """Raised when a provider answered with an error or an unusable payload."""

    user_message = "The language model provider returned an unusable response. Please try again."


class AgentError(RuntimeError):
    """Base class for application-agent failures."""

    user_message = "The application agent could not complete the request. Please try again."

    def __init__(self, detail: str = "", *, user_message: str | None = None) -> None:
        super().__init__(detail or self.user_message)
        self.detail = detail
        if user_message is not None:
            self.user_message = user_message


class AgentConfigurationError(AgentError):
    """Raised when the application agent cannot be built from configuration."""

    user_message = "The application agent is not configured correctly. Check the agent and LLM settings."


class AgentClassificationError(AgentError):
    """Raised when request classification cannot produce a usable intent."""

    user_message = "The request could not be classified. Please rephrase and try again."


class AgentCapabilityError(AgentError):
    """Raised when a registered capability cannot complete its work."""

    user_message = "The requested capability could not be completed. Please try again."


class TranscriptSearchError(AgentCapabilityError):
    """Raised when transcript retrieval fails."""

    user_message = "Lenny's transcripts could not be searched right now. Please try again."


class ArtifactGenerationError(AgentCapabilityError):
    """Raised when an artifact cannot be generated or its structure is unusable."""

    user_message = "The artifact could not be generated. Try rephrasing the request."


DATABASE_UNAVAILABLE_MESSAGE = (
    "The database is currently unavailable. Please check the configured DATABASE_URL and try again."
)

DATABASE_NOT_CONFIGURED_MESSAGE = (
    "The database is not configured. Set DATABASE_URL in the repository root .env file."
)

UNEXPECTED_ERROR_MESSAGE = "The request could not be completed. Please try again."

CLOUD_LLM_UNAVAILABLE_MESSAGE = (
    "Unable to reach the configured cloud LLM. Please check the API configuration and try again."
)

OLLAMA_UNAVAILABLE_MESSAGE = (
    "Local model execution is unavailable. Make sure Ollama is running and the configured model is "
    "installed, then try again."
)

#: Status code per error class, in the same order the handlers below resolve them.
ERROR_STATUS: dict[type[BaseException], int] = {
    SessionNotFoundError: 404,
    DatabaseNotConfiguredError: 503,
    OperationalError: 503,
    InterfaceError: 503,
    LLMConfigurationError: 503,
    LLMUnavailableError: 503,
    LLMModelUnavailableError: 503,
    LLMResponseError: 502,
    AgentConfigurationError: 503,
    AgentClassificationError: 502,
    AgentCapabilityError: 502,
}


def http_status_for(exc: BaseException) -> int:
    """Status code a raised error should be reported with."""
    for klass in type(exc).__mro__:
        status = ERROR_STATUS.get(klass)
        if status is not None:
            return status
    return 500


def user_message_for(exc: BaseException) -> str:
    """Client-safe text for a raised error.

    Only messages this module owns are ever returned: an unexpected error yields
    a generic sentence, so a driver error, a connection string or a stack frame
    can never reach a client. The real detail belongs in the logs.
    """
    if isinstance(exc, SessionNotFoundError):
        return str(exc)
    if isinstance(exc, DatabaseNotConfiguredError):
        return DATABASE_NOT_CONFIGURED_MESSAGE
    if isinstance(exc, (OperationalError, InterfaceError)):
        return DATABASE_UNAVAILABLE_MESSAGE
    message = getattr(exc, "user_message", None)
    if isinstance(message, str) and message.strip():
        return message
    return UNEXPECTED_ERROR_MESSAGE


def register_exception_handlers(app: FastAPI) -> None:
    """Translate application and database errors into readable JSON responses."""

    @app.exception_handler(SessionNotFoundError)
    async def _session_not_found(request: Request, exc: SessionNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(DatabaseNotConfiguredError)
    async def _database_not_configured(request: Request, exc: DatabaseNotConfiguredError) -> JSONResponse:
        logger.warning("Database operation attempted without configuration: %s", exc)
        return JSONResponse(status_code=503, content={"detail": DATABASE_NOT_CONFIGURED_MESSAGE})

    @app.exception_handler(OperationalError)
    @app.exception_handler(InterfaceError)
    async def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Database error while handling %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=503, content={"detail": DATABASE_UNAVAILABLE_MESSAGE})

    @app.exception_handler(LLMConfigurationError)
    async def _llm_misconfigured(request: Request, exc: LLMConfigurationError) -> JSONResponse:
        logger.error("LLM configuration error while handling %s %s: %s", request.method, request.url.path, exc.detail)
        return JSONResponse(status_code=503, content={"detail": exc.user_message})

    @app.exception_handler(LLMUnavailableError)
    async def _llm_unavailable(request: Request, exc: LLMUnavailableError) -> JSONResponse:
        logger.warning("LLM provider unavailable while handling %s %s: %s", request.method, request.url.path, exc.detail)
        return JSONResponse(status_code=503, content={"detail": exc.user_message})

    @app.exception_handler(LLMModelUnavailableError)
    async def _llm_model_unavailable(request: Request, exc: LLMModelUnavailableError) -> JSONResponse:
        logger.warning("LLM model unavailable while handling %s %s: %s", request.method, request.url.path, exc.detail)
        return JSONResponse(status_code=503, content={"detail": exc.user_message})

    @app.exception_handler(LLMResponseError)
    async def _llm_bad_response(request: Request, exc: LLMResponseError) -> JSONResponse:
        logger.error("LLM provider error while handling %s %s: %s", request.method, request.url.path, exc.detail)
        return JSONResponse(status_code=502, content={"detail": exc.user_message})

    @app.exception_handler(AgentConfigurationError)
    async def _agent_misconfigured(request: Request, exc: AgentConfigurationError) -> JSONResponse:
        logger.error("Agent configuration error while handling %s %s: %s", request.method, request.url.path, exc.detail)
        return JSONResponse(status_code=503, content={"detail": exc.user_message})

    @app.exception_handler(AgentClassificationError)
    async def _agent_classification_failed(request: Request, exc: AgentClassificationError) -> JSONResponse:
        logger.warning(
            "Agent classification failed while handling %s %s: %s", request.method, request.url.path, exc.detail
        )
        return JSONResponse(status_code=502, content={"detail": exc.user_message})

    @app.exception_handler(AgentCapabilityError)
    async def _agent_capability_failed(request: Request, exc: AgentCapabilityError) -> JSONResponse:
        logger.error(
            "Agent capability failed while handling %s %s (%s): %s",
            request.method,
            request.url.path,
            type(exc).__name__,
            exc.detail,
        )
        return JSONResponse(status_code=502, content={"detail": exc.user_message})
