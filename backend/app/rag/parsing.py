"""Parse transcript Markdown files into structured episodes.

Each file contains YAML frontmatter followed by the transcript body::

    ---
    guest: Ada Chen Rekhi
    title: Feeling stuck? ...
    youtube_url: https://www.youtube.com/watch?v=...
    video_id: l-T8sNRcWQk
    publish_date: 2023-04-21
    ...
    ---

    # Feeling stuck? ...

    ## Transcript

    Ada Chen Rekhi (00:00:00):
    ...

Only the body after the frontmatter is searchable text; the frontmatter is
preserved as structured metadata.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from app.errors import TranscriptParseError

logger = logging.getLogger("lenny.ingestion")

FRONTMATTER_PATTERN = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
HEADING_PATTERN = re.compile(r"^#{1,6}[ \t]+\S.*$", re.MULTILINE)
TRANSCRIPT_HEADING_PATTERN = re.compile(r"^[ \t]*##[ \t]+Transcript[ \t]*$", re.MULTILINE)
BLANK_LINES_PATTERN = re.compile(r"\n{3,}")

#: Frontmatter keys promoted to their own database columns.
PROMOTED_KEYS = ("guest", "title", "youtube_url", "publish_date")

#: Values that carry no information and are dropped from metadata.
_EMPTY_VALUES = (None, "", [], {})


@dataclass(slots=True)
class TranscriptEpisode:
    """A parsed transcript file."""

    episode_id: str
    source_path: Path
    relative_path: str
    guest: str | None
    title: str | None
    youtube_url: str | None
    publish_date: date | None
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def parse_transcript_file(path: Path, *, transcripts_root: Path | None = None) -> TranscriptEpisode:
    """Read ``path`` and return the parsed episode.

    Raises :class:`TranscriptParseError` when the file cannot be read or does
    not contain valid YAML frontmatter.
    """
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TranscriptParseError(f"could not read file: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise TranscriptParseError(f"file is not valid UTF-8: {exc}") from exc

    return parse_transcript_text(raw, source_path=path, transcripts_root=transcripts_root)


def parse_transcript_text(
    raw: str,
    *,
    source_path: Path,
    transcripts_root: Path | None = None,
) -> TranscriptEpisode:
    """Parse transcript file contents."""
    match = FRONTMATTER_PATTERN.match(raw)
    if match is None:
        raise TranscriptParseError("missing YAML frontmatter (expected a '---' block at the top)")

    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise TranscriptParseError(f"malformed YAML frontmatter: {exc}") from exc

    if not isinstance(data, dict):
        raise TranscriptParseError("frontmatter is empty or is not a mapping")

    body = raw[match.end() :]
    heading = _first_heading(body)
    text = normalize_transcript_text(body)
    if not text:
        raise TranscriptParseError("transcript body is empty after normalization")

    episode_id = source_path.parent.name or source_path.stem
    metadata = _build_metadata(data, source_path, transcripts_root)

    return TranscriptEpisode(
        episode_id=episode_id,
        source_path=source_path,
        relative_path=metadata["source_path"],
        guest=_clean_text(data.get("guest")),
        title=_clean_text(data.get("title")) or heading,
        youtube_url=_clean_text(data.get("youtube_url")),
        publish_date=_parse_date(data.get("publish_date")),
        text=text,
        metadata=metadata,
    )


def normalize_transcript_text(body: str) -> str:
    """Normalize the transcript body.

    Removes the leading title heading and the ``## Transcript`` marker (they
    are structural, not transcript content), normalizes line endings, collapses
    blank runs and trims trailing whitespace. Speaker labels and timestamps are
    kept because they carry attribution.
    """
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    text = TRANSCRIPT_HEADING_PATTERN.sub("", text, count=1)

    paragraphs = split_paragraphs(text)
    if paragraphs and paragraphs[0].startswith("#"):
        paragraphs = paragraphs[1:]

    normalized = "\n\n".join(paragraphs)
    return BLANK_LINES_PATTERN.sub("\n\n", normalized).strip()


def split_paragraphs(text: str) -> list[str]:
    """Split on blank lines and tidy each paragraph."""
    paragraphs = []
    for block in re.split(r"\n[ \t]*\n", text):
        cleaned = "\n".join(line.rstrip() for line in block.split("\n")).strip()
        if cleaned:
            paragraphs.append(cleaned)
    return paragraphs


def _first_heading(body: str) -> str | None:
    match = HEADING_PATTERN.search(body)
    if match is None:
        return None
    return match.group(0).lstrip("#").strip() or None


def _clean_text(value: Any) -> str | None:
    """Return a stripped string for scalar metadata values."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        joined = ", ".join(str(item).strip() for item in value if str(item).strip())
        return joined or None
    text = str(value).strip()
    return text or None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            logger.debug("Unparseable publish_date %r; keeping it in metadata", value)
    return None


def _build_metadata(data: dict[str, Any], source_path: Path, transcripts_root: Path | None) -> dict[str, Any]:
    """Collect the source metadata stored with every chunk of the episode.

    Promoted keys are represented by their own columns and are not repeated,
    except an unparseable ``publish_date`` which is kept as source data.
    """
    metadata: dict[str, Any] = {}
    for key, value in data.items():
        if value in _EMPTY_VALUES:
            continue
        if key in PROMOTED_KEYS and not (key == "publish_date" and _parse_date(value) is None):
            continue
        metadata[key] = _json_safe(value)

    if transcripts_root is not None:
        try:
            metadata["source_path"] = str(source_path.relative_to(Path(transcripts_root)))
        except ValueError:
            metadata["source_path"] = str(source_path)
    else:
        metadata["source_path"] = source_path.name
    return metadata


def _json_safe(value: Any) -> Any:
    """Convert YAML values into JSON-serializable equivalents."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
