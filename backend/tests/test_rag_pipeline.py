"""Unit tests for the ingestion pipeline's selection and failure handling.

These run dry (no embedding, no database) with a fake tokenizer.
"""

from pathlib import Path

from app.config import Settings
from app.rag.embeddings import EmbeddingProvider
from app.rag.pipeline import ingest_transcripts

GOOD_TRANSCRIPT = """---
guest: Ada Chen Rekhi
title: Feeling stuck
video_id: l-T8sNRcWQk
---

# Feeling stuck

## Transcript

Ada (00:00:00):
I felt stuck for a long time.
"""


class WordTokenizer:
    def encode(self, text: str) -> list[int]:
        return list(range(len(text.split())))

    def decode(self, tokens) -> str:
        return " ".join("tok" for _ in tokens)


class FakeProvider(EmbeddingProvider):
    name = "fake"
    model = "fake-384"

    @property
    def dimension(self) -> int:
        return 384

    @property
    def tokenizer(self):  # noqa: ANN201 - test double
        return WordTokenizer()

    @property
    def max_tokens(self) -> int | None:
        return None

    def embed_documents(self, texts):  # noqa: ANN001, ANN201 - not called in dry runs
        raise AssertionError("dry runs must not embed")

    def embed_query(self, text: str) -> list[float]:  # noqa: ARG002
        raise AssertionError("dry runs must not embed")


def _episode(root: Path, slug: str, content: str) -> Path:
    directory = root / "episodes" / slug
    directory.mkdir(parents=True)
    path = directory / "transcript.md"
    path.write_text(content, encoding="utf-8")
    return path


def _settings(root: Path) -> Settings:
    return Settings(database_url="postgresql://user:pw@host:5432/db", transcripts_path=str(root))


def _ingest(root: Path, **kwargs):
    files = sorted((root / "episodes").glob("*/transcript.md"))
    return ingest_transcripts(files=files, dry_run=True, provider=FakeProvider(), settings=_settings(root), **kwargs)


def test_a_malformed_transcript_does_not_abort_the_run(tmp_path: Path) -> None:
    _episode(tmp_path, "ada-chen-rekhi", GOOD_TRANSCRIPT)
    _episode(tmp_path, "broken-episode", "---\nguest: [unclosed\n---\n\nbroken\n")
    _episode(tmp_path, "brian-balfour", GOOD_TRANSCRIPT)

    metrics = _ingest(tmp_path, progress_every=10)

    assert metrics.files_discovered == 3
    assert metrics.episodes_processed == 2
    assert len(metrics.failures) == 1
    assert metrics.failures[0].path.endswith("broken-episode\\transcript.md") or metrics.failures[0].path.endswith(
        "broken-episode/transcript.md"
    )
    assert "malformed YAML" in metrics.failures[0].error
    assert metrics.chunks_generated > 0


def test_episode_selection_and_limit(tmp_path: Path) -> None:
    _episode(tmp_path, "ada-chen-rekhi", GOOD_TRANSCRIPT)
    _episode(tmp_path, "brian-balfour", GOOD_TRANSCRIPT)
    _episode(tmp_path, "camille-ricketts", GOOD_TRANSCRIPT)

    only_one = _ingest(tmp_path, episodes=["brian-balfour"])
    assert only_one.files_discovered == 1
    assert only_one.episodes_processed == 1

    limited = _ingest(tmp_path, limit=2)
    assert limited.files_discovered == 2
    assert limited.episodes_processed == 2

    unknown = _ingest(tmp_path, episodes=["nobody-here"])
    assert unknown.files_discovered == 0
    assert unknown.episodes_processed == 0


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    _episode(tmp_path, "ada-chen-rekhi", GOOD_TRANSCRIPT)

    metrics = _ingest(tmp_path)

    assert metrics.episodes_processed == 1
    assert metrics.chunks_inserted == 0
    assert metrics.chunks_updated == 0
