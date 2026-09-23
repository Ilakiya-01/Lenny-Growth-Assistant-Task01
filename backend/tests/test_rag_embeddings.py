"""Unit tests for the embedding provider abstraction (no model download)."""

import numpy as np
import pytest

from app.config import Settings
from app.errors import EmbeddingProviderError
from app.rag.embeddings import (
    BGE_QUERY_PREFIX,
    OPENAI_MODEL_DIMENSIONS,
    OpenAIEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
    create_embedding_provider,
)


def _settings(**overrides) -> Settings:
    values = {
        "database_url": "postgresql://user:pw@host:5432/db",
        "embedding_provider": "sentence-transformers",
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "embedding_batch_size": 32,
    }
    values.update(overrides)
    return Settings(**values)


def test_default_provider_is_the_local_sentence_transformer() -> None:
    provider = create_embedding_provider(_settings())

    assert isinstance(provider, SentenceTransformerEmbeddingProvider)
    assert provider.name == "sentence-transformers"
    assert provider.model == "BAAI/bge-small-en-v1.5"


@pytest.mark.parametrize("alias", ["sentence-transformers", "sentence_transformers", "local", "LOCAL"])
def test_local_provider_aliases(alias: str) -> None:
    assert isinstance(create_embedding_provider(_settings(embedding_provider=alias)), SentenceTransformerEmbeddingProvider)


def test_openai_provider_is_selected_explicitly() -> None:
    settings = _settings(embedding_provider="openai", embedding_model="text-embedding-3-small", openai_api_key="sk-test")

    provider = create_embedding_provider(settings)

    assert isinstance(provider, OpenAIEmbeddingProvider)
    assert provider.dimension == 1536


def test_openai_without_api_key_is_rejected() -> None:
    with pytest.raises(EmbeddingProviderError, match="OPENAI_API_KEY"):
        create_embedding_provider(_settings(embedding_provider="openai", openai_api_key=""))


def test_openai_unknown_model_dimension_is_rejected() -> None:
    provider = OpenAIEmbeddingProvider("text-embedding-4-madeup", "sk-test")

    with pytest.raises(EmbeddingProviderError, match="Unknown OpenAI embedding model"):
        _ = provider.dimension


def test_openai_dimension_table_matches_documented_models() -> None:
    assert OPENAI_MODEL_DIMENSIONS["text-embedding-3-small"] == 1536
    assert OPENAI_MODEL_DIMENSIONS["text-embedding-3-large"] == 3072


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(EmbeddingProviderError, match="Unknown EMBEDDING_PROVIDER"):
        create_embedding_provider(_settings(embedding_provider="magic-embeddings"))


def test_bge_models_get_the_query_instruction_prefix() -> None:
    bge = SentenceTransformerEmbeddingProvider("BAAI/bge-small-en-v1.5")
    other = SentenceTransformerEmbeddingProvider("sentence-transformers/all-MiniLM-L6-v2")

    assert bge._query_prefix == BGE_QUERY_PREFIX
    assert other._query_prefix == ""


class _RecordingModel:
    """Stands in for a loaded SentenceTransformer."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts, **kwargs):  # noqa: ANN003, ANN201 - mirrors the real API
        self.calls.append(list(texts))
        return [np.zeros(4, dtype="float32") for _ in texts]


class _RecordingProvider(SentenceTransformerEmbeddingProvider):
    def __init__(self) -> None:
        super().__init__("BAAI/bge-small-en-v1.5")
        self.recorder = _RecordingModel()

    @property
    def _loaded_model(self):  # noqa: ANN201 - test double for the lazy model property
        return self.recorder


def test_query_embedding_uses_the_instruction_prefix_for_bge() -> None:
    provider = _RecordingProvider()

    provider.embed_query("how do I grow a marketplace?")

    assert provider.recorder.calls == [[f"{BGE_QUERY_PREFIX}how do I grow a marketplace?"]]


def test_documents_are_embedded_without_the_query_prefix() -> None:
    provider = _RecordingProvider()

    provider.embed_documents(["first document", "second document"])

    assert provider.recorder.calls == [["first document", "second document"]]


def test_embedding_empty_document_list_returns_empty() -> None:
    assert _RecordingProvider().embed_documents([]) == []
