"""Configurable embedding providers.

The provider and model are selected with ``EMBEDDING_PROVIDER`` and
``EMBEDDING_MODEL``. Two providers are implemented:

``sentence-transformers`` (default, local)
    Runs an open model on this machine. No API key. The default model is
    ``BAAI/bge-small-en-v1.5`` (384 dimensions, 512-token input limit), which
    is downloaded from Hugging Face on first use and cached locally.

``openai`` (cloud)
    Calls the OpenAI embeddings API. Requires ``OPENAI_API_KEY`` and network
    access; the vector dimension then comes from the OpenAI model.

The PostgreSQL ``vector(N)`` column must match the selected model. Ingestion
and retrieval validate this against the database and fail with
:class:`EmbeddingDimensionMismatchError` instead of storing unusable vectors.
"""

import abc
import logging
from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

from app.config import Settings, get_settings
from app.errors import EmbeddingProviderError

logger = logging.getLogger("lenny.embeddings")

#: Instruction prefix recommended for bge models when embedding a search query.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

#: Known dimensions of OpenAI embedding models.
OPENAI_MODEL_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class EmbeddingTokenizer(Protocol):
    """Tokenizer used to count tokens for chunking."""

    def encode(self, text: str) -> list[int]: ...
    def decode(self, tokens: Sequence[int]) -> str: ...


class EmbeddingProvider(abc.ABC):
    """Common interface for embedding providers."""

    name: str
    model: str

    @property
    @abc.abstractmethod
    def dimension(self) -> int:
        """Vector length produced by this provider."""

    @property
    @abc.abstractmethod
    def tokenizer(self) -> EmbeddingTokenizer:
        """Tokenizer matching the embedding model."""

    @property
    def max_tokens(self) -> int | None:
        """Maximum input length in tokens, when the model documents one."""
        return None

    @abc.abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed texts for storage (no query instruction)."""

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""
        return self.embed_documents([text])[0]


class _HuggingFaceTokenizer:
    """Adapter exposing HF/tiktoken tokenizers through :class:`EmbeddingTokenizer`."""

    def __init__(self, tokenizer) -> None:
        self._tokenizer = tokenizer

    def encode(self, text: str) -> list[int]:
        return list(self._tokenizer.encode(text, add_special_tokens=False))

    def decode(self, tokens: Sequence[int]) -> str:
        return self._tokenizer.decode(list(tokens), skip_special_tokens=True)


def _model_dimension(model) -> int:
    """Read the embedding dimension across sentence-transformers versions."""
    getter = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
    return int(getter())


class _TiktokenTokenizer:
    def __init__(self, encoding) -> None:
        self._encoding = encoding

    def encode(self, text: str) -> list[int]:
        return list(self._encoding.encode(text))

    def decode(self, tokens: Sequence[int]) -> str:
        return self._encoding.decode(list(tokens))


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Local embeddings through sentence-transformers."""

    name = "sentence-transformers"

    def __init__(self, model: str, *, batch_size: int = 64, query_prefix: str | None = None) -> None:
        self.model = model
        self._batch_size = max(1, batch_size)
        self._query_prefix = query_prefix if query_prefix is not None else self._default_query_prefix(model)
        self._model = None
        self._tokenizer: EmbeddingTokenizer | None = None

    @staticmethod
    def _default_query_prefix(model: str) -> str:
        return BGE_QUERY_PREFIX if "bge" in model.lower() else ""

    @property
    def _loaded_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - dependency is pinned
                raise EmbeddingProviderError(
                    "The 'sentence-transformers' package is not installed. "
                    "Run: pip install -r backend/requirements.txt"
                ) from exc

            logger.info("Loading local embedding model %s (first run downloads it)", self.model)
            try:
                self._model = SentenceTransformer(self.model)
            except Exception as exc:  # noqa: BLE001 - any load failure is reported to the caller
                raise EmbeddingProviderError(
                    f"Could not load local embedding model '{self.model}': {exc}. "
                    "Check the model name and that this machine can reach huggingface.co for the first download."
                ) from exc
            logger.info("Embedding model ready (dimension=%s)", _model_dimension(self._model))
        return self._model

    @property
    def dimension(self) -> int:
        return int(_model_dimension(self._loaded_model))

    @property
    def max_tokens(self) -> int | None:
        value = getattr(self._loaded_model, "max_seq_length", None)
        return int(value) if value else None

    @property
    def tokenizer(self) -> EmbeddingTokenizer:
        if self._tokenizer is None:
            self._tokenizer = _HuggingFaceTokenizer(self._loaded_model.tokenizer)
        return self._tokenizer

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._loaded_model
        vectors = model.encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [vector.tolist() for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([f"{self._query_prefix}{text}"])[0]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Cloud embeddings through the OpenAI API."""

    name = "openai"

    def __init__(self, model: str, api_key: str, *, batch_size: int = 64) -> None:
        if not api_key:
            raise EmbeddingProviderError(
                "EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY to be set in the repository root .env file."
            )
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency is pinned
            raise EmbeddingProviderError(
                "The 'openai' package is not installed. Run: pip install -r backend/requirements.txt"
            ) from exc

        self.model = model
        self._batch_size = max(1, batch_size)
        self._client = OpenAI(api_key=api_key)
        self._tokenizer: EmbeddingTokenizer | None = None

    @property
    def dimension(self) -> int:
        dimension = OPENAI_MODEL_DIMENSIONS.get(self.model)
        if dimension is None:
            raise EmbeddingProviderError(
                f"Unknown OpenAI embedding model '{self.model}'. "
                f"Known models: {', '.join(sorted(OPENAI_MODEL_DIMENSIONS))}."
            )
        return dimension

    @property
    def tokenizer(self) -> EmbeddingTokenizer:
        if self._tokenizer is None:
            try:
                import tiktoken
            except ImportError as exc:  # pragma: no cover - dependency is pinned
                raise EmbeddingProviderError(
                    "The 'tiktoken' package is not installed. Run: pip install -r backend/requirements.txt"
                ) from exc
            self._tokenizer = _TiktokenTokenizer(tiktoken.get_encoding("cl100k_base"))
        return self._tokenizer

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(texts), self._batch_size):
                batch = list(texts[start : start + self._batch_size])
                response = self._client.embeddings.create(model=self.model, input=batch)
                vectors.extend(item.embedding for item in sorted(response.data, key=lambda item: item.index))
        except Exception as exc:  # noqa: BLE001 - surface any API failure with context
            raise EmbeddingProviderError(f"OpenAI embeddings request failed: {exc}") from exc
        return vectors


def create_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Build the provider selected by ``EMBEDDING_PROVIDER``."""
    settings = settings or get_settings()
    provider = settings.embedding_provider.strip().lower()
    model = settings.embedding_model.strip()

    if provider in ("sentence-transformers", "sentence_transformers", "local"):
        return SentenceTransformerEmbeddingProvider(model, batch_size=settings.embedding_batch_size)
    if provider == "openai":
        return OpenAIEmbeddingProvider(model, settings.openai_api_key, batch_size=settings.embedding_batch_size)

    raise EmbeddingProviderError(
        f"Unknown EMBEDDING_PROVIDER '{settings.embedding_provider}'. Supported values: sentence-transformers, openai."
    )


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    """Process-wide provider (the local model is loaded once)."""
    return create_embedding_provider()
