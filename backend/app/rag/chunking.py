"""Token-aware transcript chunking.

``CHUNK_SIZE`` and ``CHUNK_OVERLAP`` are **tokens counted with the selected
embedding model's own tokenizer** (see :mod:`app.rag.embeddings`), not
characters and not words. ``CHUNK_SIZE`` is a hard upper bound enforced by
counting tokens. ``CHUNK_OVERLAP`` is the token budget for repeating trailing
context from the previous chunk; it is emitted at paragraph/sentence
boundaries, so the realized overlap can be slightly smaller (or, for one
oversized trailing sentence, slightly larger) than the configured value.

Strategy (appropriate for semantic retrieval over speaker-turn transcripts):

1. Split the transcript on blank lines into paragraphs, which in this dataset
   are speaker turns. If a paragraph exceeds ``CHUNK_SIZE`` it is split into
   sentences; a single sentence that still exceeds ``CHUNK_SIZE`` is split into
   hard token windows as a last resort.
2. Greedily pack units into chunks while they fit in ``CHUNK_SIZE``.
3. When a chunk closes, the trailing sentence(s) of its last paragraph are
   repeated at the start of the next chunk as overlap, so facts spanning a
   boundary remain retrievable.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.rag.parsing import split_paragraphs

SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")


class Tokenizer(Protocol):
    """Minimal tokenizer interface used for chunking."""

    def encode(self, text: str) -> list[int]: ...
    def decode(self, tokens: Sequence[int]) -> str: ...


@dataclass(frozen=True, slots=True)
class Chunk:
    """One chunk of transcript text."""

    index: int
    text: str
    token_count: int


@dataclass(frozen=True, slots=True)
class _Unit:
    """A paragraph, sentence or hard token window used for packing."""

    text: str
    tokens: int
    atomic: bool = False


def chunk_text(
    text: str,
    *,
    tokenizer: Tokenizer,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Chunk]:
    """Split ``text`` into overlapping, token-bounded chunks."""
    if chunk_size <= 0:
        raise ValueError("CHUNK_SIZE must be greater than 0")
    if chunk_overlap < 0:
        raise ValueError("CHUNK_OVERLAP must not be negative")
    if chunk_overlap >= chunk_size:
        raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")

    text = text.strip()
    if not text:
        return []

    units = _build_units(text, tokenizer, chunk_size, chunk_overlap)
    texts = _pack_units(units, tokenizer, chunk_size, chunk_overlap)
    return [Chunk(index=index, text=chunk, token_count=_count(tokenizer, chunk)) for index, chunk in enumerate(texts)]


def _count(tokenizer: Tokenizer, text: str) -> int:
    return len(tokenizer.encode(text))


def _build_units(text: str, tokenizer: Tokenizer, chunk_size: int, chunk_overlap: int) -> list[_Unit]:
    units: list[_Unit] = []
    for paragraph in split_paragraphs(text):
        paragraph_tokens = _count(tokenizer, paragraph)
        if paragraph_tokens <= chunk_size:
            units.append(_Unit(paragraph, paragraph_tokens))
            continue

        for sentence in SENTENCE_SPLIT_PATTERN.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            sentence_tokens = _count(tokenizer, sentence)
            if sentence_tokens <= chunk_size:
                units.append(_Unit(sentence, sentence_tokens))
                continue

            token_ids = tokenizer.encode(sentence)
            step = max(1, chunk_size - chunk_overlap)
            for start in range(0, len(token_ids), step):
                window = token_ids[start : start + chunk_size]
                if not window:
                    break
                units.append(_Unit(tokenizer.decode(window).strip(), len(window), atomic=True))
                if start + chunk_size >= len(token_ids):
                    break
    return units


def _pack_units(units: list[_Unit], tokenizer: Tokenizer, chunk_size: int, chunk_overlap: int) -> list[str]:
    chunks: list[str] = []
    current: list[_Unit] = []

    def fits(candidate: list[_Unit]) -> bool:
        return _count(tokenizer, _render(candidate)) <= chunk_size

    for unit in units:
        if unit.atomic:
            # Hard token windows already overlap by construction; they are
            # emitted as standalone chunks so no extra context is duplicated.
            if current:
                chunks.append(_render(current))
                current = []
            chunks.append(unit.text)
            continue

        if current and not fits([*current, unit]):
            chunks.append(_render(current))
            prefix = _tail_prefix(current, tokenizer, chunk_overlap)
            current = [prefix] if prefix else []

        current.append(unit)
        while len(current) > 1 and not fits(current):
            # The carried context does not fit next to the unit; drop it.
            current.pop(0)

    if current:
        chunks.append(_render(current))
    return chunks


def _render(units: list[_Unit]) -> str:
    return "\n\n".join(unit.text for unit in units)


def _tail_prefix(units: list[_Unit], tokenizer: Tokenizer, chunk_overlap: int) -> _Unit | None:
    """Return the trailing context repeated at the start of the next chunk."""
    if chunk_overlap <= 0 or not units:
        return None

    sentences = [sentence.strip() for sentence in SENTENCE_SPLIT_PATTERN.split(units[-1].text) if sentence.strip()]
    if not sentences:
        return None

    carried: list[str] = []
    carried_tokens = 0
    for sentence in reversed(sentences):
        sentence_tokens = _count(tokenizer, sentence)
        if carried and carried_tokens + sentence_tokens > chunk_overlap:
            break
        carried.insert(0, sentence)
        carried_tokens += sentence_tokens

    prefix = " ".join(carried).strip()
    return _Unit(prefix, carried_tokens) if prefix else None
