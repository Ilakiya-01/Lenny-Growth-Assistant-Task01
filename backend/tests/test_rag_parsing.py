"""Unit tests for frontmatter parsing, metadata preservation and normalization."""

from datetime import date
from pathlib import Path

import pytest

from app.errors import TranscriptParseError
from app.rag.parsing import (
    normalize_transcript_text,
    parse_transcript_file,
    parse_transcript_text,
    split_paragraphs,
)

SAMPLE = """---
guest: Ada Chen Rekhi
title: Feeling stuck? Here is how to get unstuck
youtube_url: https://www.youtube.com/watch?v=l-T8sNRcWQk
video_id: l-T8sNRcWQk
publish_date: 2023-04-21
duration: '1:23:45'
duration_seconds: 5025.0
channel: Lenny's Podcast
view_count: 123456
keywords:
  - career
  - growth
description: |
  A conversation about feeling stuck.
---

# Feeling stuck? Here is how to get unstuck

## Transcript

Ada Chen Rekhi (00:00:00):
I felt stuck for a long time.

Lenny (00:00:12):
Welcome to the podcast.
"""


def _write(tmp_path: Path, content: str, *, slug: str = "ada-chen-rekhi") -> Path:
    directory = tmp_path / "episodes" / slug
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "transcript.md"
    path.write_text(content, encoding="utf-8")
    return path


def test_frontmatter_is_parsed_into_fields(tmp_path: Path) -> None:
    path = _write(tmp_path, SAMPLE)

    episode = parse_transcript_file(path, transcripts_root=tmp_path)

    assert episode.episode_id == "ada-chen-rekhi"
    assert episode.guest == "Ada Chen Rekhi"
    assert episode.title == "Feeling stuck? Here is how to get unstuck"
    assert episode.youtube_url == "https://www.youtube.com/watch?v=l-T8sNRcWQk"
    assert episode.publish_date == date(2023, 4, 21)


def test_extra_metadata_is_preserved_including_nested_values(tmp_path: Path) -> None:
    episode = parse_transcript_file(_write(tmp_path, SAMPLE), transcripts_root=tmp_path)

    assert episode.metadata["video_id"] == "l-T8sNRcWQk"
    assert episode.metadata["duration"] == "1:23:45"
    assert episode.metadata["duration_seconds"] == 5025.0
    assert episode.metadata["channel"] == "Lenny's Podcast"
    assert episode.metadata["view_count"] == 123456
    assert episode.metadata["keywords"] == ["career", "growth"]
    assert episode.metadata["description"].strip() == "A conversation about feeling stuck."
    assert episode.metadata["source_path"] == str(Path("episodes") / "ada-chen-rekhi" / "transcript.md")


def test_promoted_keys_are_not_duplicated_in_metadata(tmp_path: Path) -> None:
    metadata = parse_transcript_file(_write(tmp_path, SAMPLE), transcripts_root=tmp_path).metadata

    assert "guest" not in metadata
    assert "title" not in metadata
    assert "youtube_url" not in metadata
    assert "publish_date" not in metadata


def test_body_excludes_frontmatter_headings_and_keeps_speaker_turns(tmp_path: Path) -> None:
    episode = parse_transcript_file(_write(tmp_path, SAMPLE), transcripts_root=tmp_path)

    assert "---" not in episode.text
    assert "Ada Chen Rekhi" not in episode.metadata
    assert episode.text.startswith("Ada Chen Rekhi (00:00:00):")
    assert "## Transcript" not in episode.text
    assert "I felt stuck for a long time." in episode.text
    assert "Welcome to the podcast." in episode.text


def test_malformed_yaml_is_reported(tmp_path: Path) -> None:
    path = _write(tmp_path, "---\nguest: [unclosed\n---\n\nGuest: hi\n")

    with pytest.raises(TranscriptParseError, match="malformed YAML"):
        parse_transcript_file(path)


def test_missing_frontmatter_is_reported(tmp_path: Path) -> None:
    path = _write(tmp_path, "# Just a heading\n\nGuest: hi\n")

    with pytest.raises(TranscriptParseError, match="missing YAML frontmatter"):
        parse_transcript_file(path)


def test_non_mapping_frontmatter_is_reported(tmp_path: Path) -> None:
    path = _write(tmp_path, "---\njust a string\n---\n\nGuest: hi\n")

    with pytest.raises(TranscriptParseError, match="not a mapping"):
        parse_transcript_file(path)


def test_empty_body_is_reported(tmp_path: Path) -> None:
    path = _write(tmp_path, "---\nguest: Someone\n---\n\n# Title only\n")

    with pytest.raises(TranscriptParseError, match="body is empty"):
        parse_transcript_file(path)


def test_title_falls_back_to_body_heading(tmp_path: Path) -> None:
    content = "---\nguest: Someone\n---\n\n# A title from the body\n\nSomeone: hello\n"
    episode = parse_transcript_text(content, source_path=tmp_path / "episodes" / "some-slug" / "transcript.md")

    assert episode.title == "A title from the body"


def test_empty_frontmatter_values_are_treated_as_absent(tmp_path: Path) -> None:
    content = '---\nguest: Daniel Lereya\nyoutube_url: ""\nvideo_id: ""\n---\n\n# T\n\nDaniel: hi\n'
    episode = parse_transcript_text(content, source_path=tmp_path / "episodes" / "daniel-lereya" / "transcript.md")

    assert episode.guest == "Daniel Lereya"
    assert episode.youtube_url is None
    assert episode.publish_date is None
    assert "video_id" not in episode.metadata


def test_unparseable_publish_date_is_kept_in_metadata() -> None:
    content = "---\nguest: Someone\npublish_date: sometime in 2021\n---\n\n# T\n\nSomeone: hi\n"
    episode = parse_transcript_text(content, source_path=Path("episodes/x/transcript.md"))

    assert episode.publish_date is None
    assert episode.metadata["publish_date"] == "sometime in 2021"


def test_normalization_collapses_blank_lines_and_crlf() -> None:
    body = "# Title\r\n\r\n\r\n## Transcript\r\n\r\nA: one\r\n\r\n\r\n\r\nB: two\r\n"

    assert normalize_transcript_text(body) == "A: one\n\nB: two"


def test_split_paragraphs_keeps_speaker_turns_separate() -> None:
    text = "A (00:00): hello\ncontinues here\n\n\nB (00:10): bye"

    assert split_paragraphs(text) == ["A (00:00): hello\ncontinues here", "B (00:10): bye"]
