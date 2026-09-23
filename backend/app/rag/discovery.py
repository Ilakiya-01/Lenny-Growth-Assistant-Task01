"""Locate transcript files inside the local Lenny transcript repository.

The dataset (https://github.com/ChatPRD/lennys-podcast-transcripts) stores one
directory per episode::

    <TRANSCRIPTS_PATH>/episodes/<guest-slug>/transcript.md

Discovery is dynamic: every ``transcript.md`` below the episodes directory is
picked up, so new episodes are ingested without changing any code.
"""

import logging
from pathlib import Path

from app.errors import TranscriptSourceError

logger = logging.getLogger("lenny.ingestion")

EPISODES_DIR_NAME = "episodes"
TRANSCRIPT_FILE_NAME = "transcript.md"


def discover_transcript_files(
    transcripts_root: Path,
    *,
    episodes_dir: str | None = None,
) -> list[Path]:
    """Return the transcript files found under ``transcripts_root``.

    ``episodes_dir`` overrides the default ``episodes`` directory; relative
    values are resolved against ``transcripts_root``.
    """
    root = Path(transcripts_root)
    if not root.is_dir():
        raise TranscriptSourceError(
            f"TRANSCRIPTS_PATH does not point to a directory: {root}. "
            "Clone https://github.com/ChatPRD/lennys-podcast-transcripts and set "
            "TRANSCRIPTS_PATH in .env (relative paths are resolved from the repository root)."
        )

    base = Path(episodes_dir) if episodes_dir else Path(EPISODES_DIR_NAME)
    if not base.is_absolute():
        base = root / base
    if not base.is_dir():
        raise TranscriptSourceError(
            f"Episodes directory not found: {base}. Expected a directory named "
            f"'{EPISODES_DIR_NAME}' inside the transcript repository."
        )

    files = sorted(base.glob(f"*/{TRANSCRIPT_FILE_NAME}"))
    if not files:
        raise TranscriptSourceError(
            f"No '{TRANSCRIPT_FILE_NAME}' files found in {base}. "
            "Check that TRANSCRIPTS_PATH points at the dataset repository."
        )

    logger.info("Discovered %d transcript files in %s", len(files), base)
    return files
