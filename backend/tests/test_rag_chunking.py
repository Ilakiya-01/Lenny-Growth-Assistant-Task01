"""Unit tests for token-aware chunking.

The fake tokenizer treats one whitespace-separated word as one token, which
keeps the expected chunk arithmetic readable.
"""

import pytest

from app.rag.chunking import Chunk, chunk_text


class WordTokenizer:
    """Fake tokenizer where each whitespace-separated word is a token."""

    def encode(self, text: str) -> list[int]:
        return list(range(len(text.split())))

    def decode(self, tokens) -> str:
        return " ".join(f"tok{index}" for index, _ in enumerate(tokens))


def _words(count: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{index}" for index in range(count))


def _paragraphs(count: int, words: int, prefix: str = "p") -> str:
    return "\n\n".join(_words(words, f"{prefix}{index}_") for index in range(count))


def test_short_text_becomes_a_single_chunk() -> None:
    chunks = chunk_text("hello there friend", tokenizer=WordTokenizer(), chunk_size=10, chunk_overlap=2)

    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].text == "hello there friend"
    assert chunks[0].token_count == 3


def test_empty_text_produces_no_chunks() -> None:
    assert chunk_text("   \n\n  ", tokenizer=WordTokenizer(), chunk_size=10, chunk_overlap=2) == []


def test_chunks_never_exceed_chunk_size() -> None:
    text = _paragraphs(6, 20)

    chunks = chunk_text(text, tokenizer=WordTokenizer(), chunk_size=25, chunk_overlap=5)

    assert len(chunks) > 1
    assert all(chunk.token_count <= 25 for chunk in chunks)


def test_paragraphs_are_preferred_over_sentences() -> None:
    text = "first paragraph here\n\nsecond paragraph here"

    chunks = chunk_text(text, tokenizer=WordTokenizer(), chunk_size=4, chunk_overlap=0)

    assert [chunk.text for chunk in chunks] == ["first paragraph here", "second paragraph here"]


def test_oversized_paragraph_is_split_on_sentences() -> None:
    sentence = "This is a sentence with seven words."
    paragraph = " ".join([sentence] * 4)

    chunks = chunk_text(paragraph, tokenizer=WordTokenizer(), chunk_size=10, chunk_overlap=0)

    assert len(chunks) == 4
    assert all(chunk.token_count <= 10 for chunk in chunks)
    assert all(chunk.text.count("sentence") == 1 for chunk in chunks)


def test_oversized_sentence_is_split_into_token_windows() -> None:
    text = _words(30, "long")

    chunks = chunk_text(text, tokenizer=WordTokenizer(), chunk_size=10, chunk_overlap=3)

    # 30 tokens, windows of 10 with a stride of 7: 0-9, 7-16, 14-23, 21-29.
    assert [chunk.token_count for chunk in chunks] == [10, 10, 10, 9]


def test_overlap_repeats_trailing_context_at_the_next_boundary() -> None:
    first = "Alpha one two three. Four five six seven."
    second = "Beta eight nine ten."
    text = f"{first}\n\n{second}"

    # 8 + 4 tokens do not fit in one 11-token chunk, so the last sentence of
    # the first paragraph is carried into the second chunk.
    chunks = chunk_text(text, tokenizer=WordTokenizer(), chunk_size=11, chunk_overlap=6)

    assert len(chunks) == 2
    assert chunks[0].text == first
    assert chunks[1].text.startswith("Four five six seven.")
    assert chunks[1].text.endswith(second)


def test_zero_overlap_does_not_repeat_context() -> None:
    text = _paragraphs(6, 4, prefix="g")

    chunks = chunk_text(text, tokenizer=WordTokenizer(), chunk_size=10, chunk_overlap=0)

    words = [word for chunk in chunks for word in chunk.text.split()]
    assert len(words) == len(set(words))


def test_chunk_indices_are_sequential() -> None:
    text = _paragraphs(4, 15, prefix="x")

    chunks = chunk_text(text, tokenizer=WordTokenizer(), chunk_size=20, chunk_overlap=4)

    assert len(chunks) > 1
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert all(isinstance(chunk, Chunk) for chunk in chunks)


def test_all_input_words_are_preserved_across_chunks() -> None:
    text = _paragraphs(10, 6)

    chunks = chunk_text(text, tokenizer=WordTokenizer(), chunk_size=15, chunk_overlap=5)

    covered = {word for chunk in chunks for word in chunk.text.split()}
    assert covered == set(text.split())


def test_invalid_configuration_is_rejected() -> None:
    tokenizer = WordTokenizer()

    with pytest.raises(ValueError, match="CHUNK_SIZE"):
        chunk_text("text", tokenizer=tokenizer, chunk_size=0, chunk_overlap=0)
    with pytest.raises(ValueError, match="CHUNK_OVERLAP must not be negative"):
        chunk_text("text", tokenizer=tokenizer, chunk_size=10, chunk_overlap=-1)
    with pytest.raises(ValueError, match="smaller than CHUNK_SIZE"):
        chunk_text("text", tokenizer=tokenizer, chunk_size=10, chunk_overlap=10)
