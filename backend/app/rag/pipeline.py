"""Transcript ingestion pipeline: discover, parse, chunk, embed, store.

The pipeline is repeatable: chunks are keyed by ``(episode_id, chunk_index)``
and only rewritten when their content or metadata changed, so an interrupted
run can simply be started again. A failure in one transcript is recorded and
does not abort the remaining files.
"""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.database import get_session_factory
from app.db.repositories.transcript_repository import (
    ChunkRecord,
    UpsertOutcome,
    check_embedding_dimension,
    upsert_episode_chunks,
)
from app.rag.chunking import Chunk, chunk_text
from app.rag.discovery import discover_transcript_files
from app.rag.embeddings import EmbeddingProvider, get_embedding_provider
from app.rag.parsing import TranscriptEpisode, parse_transcript_file

logger = logging.getLogger("lenny.ingestion")


@dataclass(slots=True)
class EpisodeFailure:
    """A transcript that could not be ingested."""

    path: str
    error: str


@dataclass(slots=True)
class IngestionMetrics:
    """Outcome of one ingestion run."""

    files_discovered: int = 0
    episodes_processed: int = 0
    chunks_generated: int = 0
    chunks_inserted: int = 0
    chunks_updated: int = 0
    chunks_unchanged: int = 0
    chunks_pruned: int = 0
    failures: list[EpisodeFailure] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def summary_lines(self, *, dry_run: bool = False) -> list[str]:
        lines = [
            f"files discovered    : {self.files_discovered}",
            f"episodes processed  : {self.episodes_processed}",
            f"chunks generated    : {self.chunks_generated}",
        ]
        if dry_run:
            lines.append("chunks written      : skipped (dry run)")
        else:
            lines.extend(
                [
                    f"chunks inserted     : {self.chunks_inserted}",
                    f"chunks updated      : {self.chunks_updated}",
                    f"chunks unchanged    : {self.chunks_unchanged}",
                    f"chunks pruned       : {self.chunks_pruned}",
                ]
            )
        lines.append(f"failures            : {len(self.failures)}")
        lines.append(f"elapsed             : {_format_duration(self.elapsed_seconds)}")
        return lines


def ingest_transcripts(
    *,
    limit: int | None = None,
    episodes: Sequence[str] | None = None,
    dry_run: bool = False,
    progress_every: int = 10,
    verbose: bool = False,
    settings: Settings | None = None,
    provider: EmbeddingProvider | None = None,
    files: Sequence[Path] | None = None,
) -> IngestionMetrics:
    """Ingest transcript files into the knowledge base.

    ``files`` bypasses discovery (used by tests); otherwise the configured
    transcript repository is scanned. ``dry_run`` parses, normalizes and chunks
    without embedding or writing to the database.
    """
    settings = settings or get_settings()
    started = time.perf_counter()
    metrics = IngestionMetrics()

    discovered = list(files) if files is not None else discover_transcript_files(settings.transcripts_root)
    selected = _select_files(discovered, episodes=episodes, limit=limit)
    metrics.files_discovered = len(selected)
    if not selected:
        logger.warning("No transcript files matched the requested selection")
        metrics.elapsed_seconds = time.perf_counter() - started
        return metrics

    provider = provider or get_embedding_provider()
    if provider.max_tokens is not None and settings.chunk_size > provider.max_tokens:
        raise ValueError(
            f"CHUNK_SIZE={settings.chunk_size} exceeds the {provider.max_tokens}-token input limit of "
            f"'{provider.model}'. Lower CHUNK_SIZE so embeddings are not silently truncated."
        )

    session: Session | None = None
    if not dry_run:
        session = get_session_factory()()
        check_embedding_dimension(session, provider.dimension, model=provider.model)

    logger.info(
        "Ingesting %d transcript(s) with %s/%s (dimension=%d, chunk_size=%d, chunk_overlap=%d%s)",
        len(selected),
        provider.name,
        provider.model,
        provider.dimension,
        settings.chunk_size,
        settings.chunk_overlap,
        ", dry run" if dry_run else "",
    )

    try:
        for index, path in enumerate(selected, start=1):
            try:
                episode = parse_transcript_file(path, transcripts_root=settings.transcripts_root)
                chunks = chunk_text(
                    episode.text,
                    tokenizer=provider.tokenizer,
                    chunk_size=settings.chunk_size,
                    chunk_overlap=settings.chunk_overlap,
                )
                metrics.chunks_generated += len(chunks)

                if not dry_run and chunks:
                    outcome = _store_episode(session, episode, chunks, provider)
                    session.commit()
                    metrics.chunks_inserted += outcome.inserted
                    metrics.chunks_updated += outcome.updated
                    metrics.chunks_unchanged += outcome.unchanged
                    metrics.chunks_pruned += outcome.pruned

                metrics.episodes_processed += 1
                if verbose or index % progress_every == 0 or index == len(selected):
                    logger.info(
                        "[%d/%d] %s: %d chunks%s | total chunks=%d | %s elapsed",
                        index,
                        len(selected),
                        episode.episode_id,
                        len(chunks),
                        ""
                        if dry_run
                        else f" (inserted {metrics.chunks_inserted}, updated {metrics.chunks_updated})",
                        metrics.chunks_generated,
                        _format_duration(time.perf_counter() - started),
                    )
            except Exception as exc:  # noqa: BLE001 - one bad transcript must not stop the run
                if session is not None:
                    session.rollback()
                metrics.failures.append(EpisodeFailure(path=str(path), error=f"{type(exc).__name__}: {exc}"))
                logger.warning(
                    "Failed to ingest %s: %s: %s",
                    path.parent.name,
                    type(exc).__name__,
                    exc,
                    exc_info=logger.isEnabledFor(logging.DEBUG),
                )
    finally:
        if session is not None:
            session.close()

    metrics.elapsed_seconds = time.perf_counter() - started
    _log_summary(metrics, dry_run=dry_run)
    return metrics


def _store_episode(
    session: Session,
    episode: TranscriptEpisode,
    chunks: Sequence[Chunk],
    provider: EmbeddingProvider,
) -> UpsertOutcome:
    embeddings = provider.embed_documents([chunk.text for chunk in chunks])
    records = [
        ChunkRecord(
            episode_id=episode.episode_id,
            chunk_index=chunk.index,
            content=chunk.text,
            embedding=embedding,
            guest=episode.guest,
            title=episode.title,
            youtube_url=episode.youtube_url,
            publish_date=episode.publish_date,
            metadata={
                **episode.metadata,
                "chunk_tokens": chunk.token_count,
                "embedding_model": provider.model,
            },
        )
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]
    return upsert_episode_chunks(session, records)


def _select_files(
    files: Sequence[Path],
    *,
    episodes: Sequence[str] | None,
    limit: int | None,
) -> list[Path]:
    selected = list(files)
    if episodes:
        wanted = {episode.strip().lower() for episode in episodes if episode.strip()}
        selected = [path for path in selected if path.parent.name.lower() in wanted]
    if limit is not None:
        selected = selected[:limit]
    return selected


def _log_summary(metrics: IngestionMetrics, *, dry_run: bool) -> None:
    logger.info("Ingestion summary:")
    for line in metrics.summary_lines(dry_run=dry_run):
        logger.info("  %s", line)
    for failure in metrics.failures:
        logger.warning("  failure: %s -> %s", failure.path, failure.error)


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(int(seconds), 60)
    return f"{minutes}m{remainder:02d}s"
