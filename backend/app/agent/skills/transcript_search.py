"""Transcript search capability.

This tool is the only place the application agent touches the knowledge base. It
wraps the Phase 2 retrieval foundation unchanged - the same
:func:`app.rag.retrieval.search_transcript_chunks` call that embeds the query with
the configured embedding model and invokes ``match_transcript_chunks`` in
PostgreSQL - so there is exactly one vector-search implementation in the project.

It retrieves and reports. It does not generate prose and it holds no prompt.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.agent.activity import AgentActivityKind
from app.agent.intents import Intent
from app.agent.skills.base import (
    EVIDENCE_BLOCK_EMPTY,
    EvidenceBundle,
    SkillContext,
    evidence_to_dict,
    format_evidence_block,
)
from app.agent.tools import AgentTool, ToolResult
from app.errors import EmbeddingDimensionMismatchError, EmbeddingProviderError, TranscriptSearchError
from app.rag.retrieval import DEFAULT_TOP_K, TranscriptSearchResult, search_transcript_chunks

logger = logging.getLogger("lenny.skills.transcript_search")

SEARCH_TOOL_NAME = "transcript_search"

#: Noise floor for retrieval: below this cosine similarity a row is not worth
#: returning at all. Retrieval itself stays generous - it reports what the
#: knowledge base contains; deciding whether a passage is evidence for an answer
#: is :data:`MIN_EVIDENCE_SIMILARITY`'s job.
MIN_RETRIEVAL_SIMILARITY = 0.3

#: Quality floor for using a retrieved passage as evidence in an answer.
#:
#: Calibrated against the live knowledge base (22,327 chunks, bge-small-en-v1.5)
#: on 2026-09-22: eleven relevant product/growth questions scored 0.740-0.797 on
#: their best passage, ten clearly unrelated ones (cold fusion reactors, sourdough
#: bread, the rules of cricket, ...) topped out at 0.686. The floor sits between
#: the two distributions. Raising it makes "no evidence" more likely; lowering it
#: lets weak semantic matches be answered as if they were evidence.
MIN_EVIDENCE_SIMILARITY = 0.71

#: Upper bound on how many passages one request may pull into a prompt.
MAX_TOP_K = 20


def run_transcript_search(
    context: SkillContext,
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float | None = MIN_RETRIEVAL_SIMILARITY,
) -> list[TranscriptSearchResult]:
    """Retrieve transcript chunks for ``query`` through the Phase 2 foundation."""
    text = (query or "").strip()
    if not text:
        raise TranscriptSearchError("A transcript search needs a non-empty query.")

    db = context.require_db()
    try:
        return search_transcript_chunks(db, text, top_k=top_k, min_similarity=min_similarity)
    except (EmbeddingProviderError, EmbeddingDimensionMismatchError) as exc:
        logger.error("Transcript search could not embed the query: %s", exc)
        raise TranscriptSearchError(
            f"The configured embedding provider could not embed the search query: {exc}",
            user_message=(
                "Lenny's transcripts could not be searched because the embedding model is unavailable. "
                "Check the EMBEDDING_* settings and try again."
            ),
        ) from exc
    except SQLAlchemyError as exc:
        logger.error("Transcript search failed against the database: %s", type(exc).__name__)
        raise TranscriptSearchError(
            f"Transcript retrieval failed in the database: {type(exc).__name__}",
            user_message=(
                "Lenny's transcripts could not be searched because the knowledge base is unreachable. "
                "Check DATABASE_URL and try again."
            ),
        ) from exc


async def gather_evidence(
    context: SkillContext,
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = MIN_EVIDENCE_SIMILARITY,
) -> EvidenceBundle:
    """Invoke the registered search capability and collect its passages as evidence.

    This is where "some semantic similarity" becomes "enough evidence to answer":
    only passages at or above ``min_similarity`` enter the bundle, and when
    nothing clears the floor the bundle is empty. The grounded answer reads that
    as "not enough evidence" instead of answering from a weak match.

    The grounded Q&A skill and the agent's composition step both use this, so
    retrieval always runs through the same registry entry and the same Phase 2
    query path.
    """
    tool = context.registry.tool(SEARCH_TOOL_NAME)
    if tool is None:
        raise TranscriptSearchError("The transcript search capability is not registered.")

    if context.reporter is not None:
        context.reporter.emit(AgentActivityKind.RETRIEVING_EVIDENCE, detail={"capability": SEARCH_TOOL_NAME})

    result = await tool.run({"query": query, "top_k": top_k}, context)
    retrieved = tuple(result.metadata.get("results") or ())
    passages = tuple(passage for passage in retrieved if passage.similarity >= min_similarity)
    if retrieved and not passages:
        logger.info(
            "Retrieved %d passage(s) but none cleared the evidence floor %.2f (best %.3f)",
            len(retrieved),
            min_similarity,
            max(passage.similarity for passage in retrieved),
        )
    logger.info("Transcript search produced %d evidence passage(s) from %d result(s)", len(passages), len(retrieved))

    if context.agent_context is not None and passages:
        # Record the evidence on the request context so downstream reporting can
        # see how much material the answer was based on.
        context.agent_context = replace(
            context.agent_context,
            retrieved_context=tuple(passage.content for passage in passages),
        )

    text = format_evidence_block(passages) if passages else EVIDENCE_BLOCK_EMPTY
    return EvidenceBundle(passages=passages, text=text)


class TranscriptSearchTool(AgentTool):
    """Retrieve relevant Lenny transcript chunks for a natural-language query."""

    name = SEARCH_TOOL_NAME
    description = "Semantic search over Lenny's Podcast transcript chunks."
    intents = (Intent.RAG_QA,)

    async def run(self, arguments: Mapping[str, Any], context: SkillContext) -> ToolResult:
        query = str(arguments.get("query") or context.request).strip()
        top_k = _coerce_top_k(arguments.get("top_k"))

        results = run_transcript_search(context, query, top_k=top_k)

        return ToolResult(
            tool=self.name,
            content=format_evidence_block(results),
            metadata={
                "query": query,
                "top_k": top_k,
                "result_count": len(results),
                "passages": [evidence_to_dict(result) for result in results],
                "results": tuple(results),
            },
        )


def _coerce_top_k(value: Any) -> int:
    if value is None:
        return DEFAULT_TOP_K
    try:
        top_k = int(value)
    except (TypeError, ValueError):
        raise TranscriptSearchError(f"Invalid transcript search size: {value!r}") from None
    if top_k <= 0:
        raise TranscriptSearchError("The transcript search size must be greater than zero.")
    return min(top_k, MAX_TOP_K)


__all__ = [
    "MAX_TOP_K",
    "MIN_EVIDENCE_SIMILARITY",
    "MIN_RETRIEVAL_SIMILARITY",
    "SEARCH_TOOL_NAME",
    "TranscriptSearchTool",
    "gather_evidence",
    "run_transcript_search",
]
