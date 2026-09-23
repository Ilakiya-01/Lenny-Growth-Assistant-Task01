"""Unit tests for transcript discovery."""

from pathlib import Path

import pytest

from app.errors import TranscriptSourceError
from app.rag.discovery import discover_transcript_files


def _make_episode(root: Path, slug: str, *, text: str = "Guest: hello\n\nGuest: world") -> Path:
    directory = root / "episodes" / slug
    directory.mkdir(parents=True)
    transcript = directory / "transcript.md"
    transcript.write_text(text, encoding="utf-8")
    return transcript


def test_discovery_finds_nested_transcripts_sorted(tmp_path: Path) -> None:
    _make_episode(tmp_path, "ada-chen-rekhi")
    _make_episode(tmp_path, "brian-balfour")

    files = discover_transcript_files(tmp_path)

    assert [path.parent.name for path in files] == ["ada-chen-rekhi", "brian-balfour"]


def test_discovery_ignores_unrelated_files(tmp_path: Path) -> None:
    _make_episode(tmp_path, "ada-chen-rekhi")
    (tmp_path / "episodes" / "ada-chen-rekhi" / "notes.txt").write_text("ignore me", encoding="utf-8")
    (tmp_path / "README.md").write_text("ignore me too", encoding="utf-8")

    assert len(discover_transcript_files(tmp_path)) == 1


def test_missing_transcripts_root_is_reported(tmp_path: Path) -> None:
    with pytest.raises(TranscriptSourceError, match="does not point to a directory"):
        discover_transcript_files(tmp_path / "nope")


def test_missing_episodes_directory_is_reported(tmp_path: Path) -> None:
    with pytest.raises(TranscriptSourceError, match="Episodes directory not found"):
        discover_transcript_files(tmp_path)


def test_empty_episodes_directory_is_reported(tmp_path: Path) -> None:
    (tmp_path / "episodes").mkdir()

    with pytest.raises(TranscriptSourceError, match="files found in"):
        discover_transcript_files(tmp_path)


def test_root_that_is_a_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_text("x", encoding="utf-8")

    with pytest.raises(TranscriptSourceError, match="does not point to a directory"):
        discover_transcript_files(path)
