#!/usr/bin/env python
"""Real end-to-end verification for the Phase 4 skills and tools.

This script performs the verification the automated suite deliberately avoids: it
runs the Phase 4 capabilities against the real knowledge base (the ingested
Lenny's Podcast transcripts) and the real configured provider, and reports what
actually happened.

Checks:

    1. database and knowledge base     - the ingested transcripts are reachable
    2. transcript search tool          - real embedding + ``match_transcript_chunks``
    3. grounded Q&A                    - real retrieval, real generation, evidence preserved
    4. insufficient evidence           - stated without a provider call, no fallback
    5. Ship30for30 article             - real generation, structure measured
    6. artifact generation (markdown)  - structured JSON artifact
    7. artifact generation (HTML/CSS)  - stylesheet kept out of the artifact body
    8. composed request                - essay first, then a markdown artifact

Usage (from the repository root)::

    backend/.venv/Scripts/python.exe backend/scripts/smoke_skills.py
    backend/.venv/Scripts/python.exe backend/scripts/smoke_skills.py --skip-writing
    backend/.venv/Scripts/python.exe backend/scripts/smoke_skills.py --timeout 3600

Local CPU inference is slow - a reasoning model spends part of every token
budget on its private thinking before writing anything - so the writing checks
are opt-out and the timeout is configurable. A check that could not be performed
because the database, the provider or the embedding model is unavailable is
reported as SKIPPED, never as PASSED. No credential value is ever printed.
"""

import argparse
import asyncio
import logging
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import func, select  # noqa: E402

from app.agent.agent import create_application_agent  # noqa: E402
from app.agent.context import AgentContext  # noqa: E402
from app.agent.skills.artifacts import ARTIFACT_TYPE_HTML, ARTIFACT_TYPE_MARKDOWN  # noqa: E402
from app.agent.intents import Intent  # noqa: E402
from app.agent.skills.base import EVIDENCE_BLOCK_EMPTY, EvidenceBundle, SkillContext  # noqa: E402
from app.agent.skills.grounded_qa import MISSING_EVIDENCE_REPLY, TranscriptQASkill  # noqa: E402
from app.agent.skills.ship30for30 import analyze_essay  # noqa: E402
from app.agent.skills.transcript_search import (  # noqa: E402
    MIN_EVIDENCE_SIMILARITY,
    SEARCH_TOOL_NAME,
    TranscriptSearchTool,
)
from app.agent.tools import AgentTool, ToolRegistry, ToolResult, default_registry  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.database import get_session_factory  # noqa: E402
from app.db.models import TranscriptChunk  # noqa: E402
from app.errors import LLMConfigurationError  # noqa: E402
from app.llm.factory import MODE_CLOUD, create_llm_client, normalize_llm_mode  # noqa: E402

from smoke_llm import FAIL, PASS, SKIPPED, Report  # noqa: E402

QA_QUESTION = "What do Lenny's guests say about product-market fit?"
SEARCH_QUERY = "product market fit before growth"
WRITING_BRIEF = "Write a 1250-word Ship30for30 article about retention before acquisition."
COMPOSED_REQUEST = (
    "Write a 1250-word essay about retention before acquisition and deliver it as a markdown artifact."
)
ARTIFACT_MARKDOWN_REQUEST = "Create a markdown product strategy document about retention."
ARTIFACT_HTML_REQUEST = "Build a simple HTML landing page for a retention-focused growth tool."
UNCERTAIN_QUESTION = "What did Lenny's guests say about cold fusion reactors?"


def _preview(text: str, limit: int = 110) -> str:
    return " ".join((text or "").split())[:limit]


def _open_session(report: Report):
    """Open a database session, or report the skip and return ``None``."""
    try:
        session = get_session_factory()()
        session.execute(select(func.count()).select_from(TranscriptChunk)).scalar_one()
        return session
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        report.add(
            "knowledge base reachable",
            SKIPPED,
            f"the database could not be queried ({type(exc).__name__}); set DATABASE_URL and migrate",
        )
        return None


async def _check_knowledge_base(report: Report, session) -> int:
    chunks = session.execute(select(func.count()).select_from(TranscriptChunk)).scalar_one()
    episodes = session.execute(select(func.count(func.distinct(TranscriptChunk.episode_id)))).scalar_one()
    report.add(
        "knowledge base contents",
        PASS if chunks else FAIL,
        f"{chunks} transcript chunk(s) across {episodes} episode(s)",
    )
    return int(episodes)


async def _check_transcript_search(report: Report, session) -> None:
    """Real retrieval through the Phase 4 tool, Phase 2 embeddings and pgvector."""
    tool = TranscriptSearchTool()
    context = SkillContext(request=SEARCH_QUERY, registry=default_registry(), db=session)
    started = time.perf_counter()
    try:
        result = await tool.run({"query": SEARCH_QUERY, "top_k": 3}, context)
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        report.add(
            "transcript search tool",
            SKIPPED if isinstance(exc, LLMConfigurationError) else FAIL,
            f"{type(exc).__name__}: {getattr(exc, 'user_message', exc)}",
        )
        return

    duration = round(time.perf_counter() - started, 1)
    passages = result.metadata["passages"]
    if not passages:
        report.add("transcript search tool", FAIL, f"no passage was retrieved in {duration}s")
        return

    top = passages[0]
    report.add(
        "transcript search tool",
        PASS,
        f"{len(passages)} passage(s) in {duration}s; top: '{_preview(top['title'] or top['episode_id'], 50)}' "
        f"guest={top['guest']} similarity={top['similarity']:.3f}",
    )


async def _check_grounded_qa(report: Report, agent, session) -> None:
    started = time.perf_counter()
    try:
        result = await agent.handle(AgentContext(user_message=QA_QUESTION), db=session)
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        report.add("grounded Q&A", FAIL, f"{type(exc).__name__}: {getattr(exc, 'user_message', exc)}")
        return

    duration = round(time.perf_counter() - started, 1)
    grounded = bool(result.metadata.get("grounded"))
    sources = result.sources
    first = sources[0] if sources else {}
    report.add(
        "grounded Q&A",
        PASS if result.reply and (grounded or result.metadata.get("insufficient_evidence")) else FAIL,
        f"{duration}s intent={result.intent.value} capability={result.capability} "
        f"evidence={result.metadata.get('evidence_count')} grounded={grounded} sources={len(sources)} "
        f"top_source='{_preview(first.get('title') or first.get('episode_id') or '-', 40)}' "
        f"reply='{_preview(result.reply)}'",
    )
    if sources:
        report.add(
            "source metadata preserved",
            PASS,
            "; ".join(
                f"{source.get('guest') or 'unknown guest'} / {source.get('publish_date') or 'date unknown'} "
                f"/ {source.get('youtube_url') or 'no link'}"
                for source in sources[:2]
            ),
        )


class CountingClient:
    """Wrap the real provider so a check can prove whether a model call happened."""

    def __init__(self, client) -> None:
        self._client = client
        self.calls = 0

    def __getattr__(self, name):
        return getattr(self._client, name)

    async def generate(self, *args, **kwargs):
        self.calls += 1
        return await self._client.generate(*args, **kwargs)


class RecordingClient:
    """Wrap the real provider so a check can report the raw provider outcome.

    The recorded values belong to the most recent generation, which for a
    single-capability request is the generation that check is about. Only
    provider-level facts are recorded - never prompt, reasoning or answer text.
    """

    def __init__(self, client) -> None:
        self._client = client
        self.finish_reason: str | None = None
        self.output_tokens: int | None = None
        self.duration_seconds: float | None = None
        self.calls = 0

    def __getattr__(self, name):
        return getattr(self._client, name)

    async def generate(self, *args, **kwargs):
        self.calls += 1
        response = await self._client.generate(*args, **kwargs)
        self.finish_reason = response.finish_reason
        self.output_tokens = response.usage.output_tokens if response.usage else None
        self.duration_seconds = response.duration_seconds
        return response


class EmptySearchTool(AgentTool):
    """Registered search capability that retrieves nothing.

    The no-evidence branch is what this check is about; the real retrieval path
    is covered by the transcript-search and grounded-Q&A checks above, which hit
    the live knowledge base.
    """

    name = SEARCH_TOOL_NAME
    description = "Returns no transcript passages (verification stub)."
    intents = (Intent.RAG_QA,)

    async def run(self, arguments: Mapping[str, Any], context: SkillContext) -> ToolResult:
        return ToolResult(
            tool=self.name,
            content=EVIDENCE_BLOCK_EMPTY,
            metadata={"result_count": 0, "passages": [], "results": ()},
        )


async def _check_insufficient_evidence(report: Report, client) -> None:
    """An empty evidence bundle must produce the explicit message, with no provider call.

    This is what prevents a general-knowledge answer: with nothing retrieved, the
    skill must not reach for the model at all.
    """
    counting = CountingClient(client)
    registry = ToolRegistry()
    registry.register_tool(EmptySearchTool())
    registry.register_tool(TranscriptQASkill())
    context = SkillContext(request=UNCERTAIN_QUESTION, registry=registry, client=counting)
    try:
        result = await TranscriptQASkill().run({}, context)
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        report.add("insufficient evidence behaviour", FAIL, f"{type(exc).__name__}: {getattr(exc, 'user_message', exc)}")
        return

    ok = result.content == MISSING_EVIDENCE_REPLY and result.metadata.get("grounded") is False and counting.calls == 0
    report.add(
        "insufficient evidence behaviour",
        PASS if ok else FAIL,
        f"grounded={result.metadata.get('grounded')} evidence={result.metadata.get('evidence_count')} "
        f"provider_calls={counting.calls} reply='{_preview(result.content, 80)}'",
    )


async def _check_insufficient_evidence_live(report: Report, settings, mode: str, session) -> None:
    """The same branch, reached through real retrieval against the live knowledge base.

    Two things are checked against the real data: the raw retrieval scores for a
    clearly off-topic question, and the agent's behaviour on that question. The
    agent must answer with the fixed message and no provider call, even though
    retrieval returns its usual handful of semantically-nearest rows.
    """
    label = "insufficient evidence (live retrieval)"
    if session is None:
        report.add(label, SKIPPED, "the knowledge base is not reachable")
        return

    tool = TranscriptSearchTool()
    context = SkillContext(request=UNCERTAIN_QUESTION, registry=default_registry(), db=session)
    try:
        found = await tool.run({"query": UNCERTAIN_QUESTION, "top_k": 3}, context)
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        report.add(label, FAIL, f"{type(exc).__name__}: {getattr(exc, 'user_message', exc)}")
        return

    raw = found.metadata["passages"]
    top = max((passage["similarity"] for passage in raw), default=None)
    report.add(
        "off-topic retrieval scores",
        PASS,
        f"raw retrieval returned {len(raw)} passage(s) for the off-topic question"
        + (f", best similarity {top:.4f}" if top is not None else "")
        + f"; evidence floor {MIN_EVIDENCE_SIMILARITY}",
    )

    try:
        counting = CountingClient(create_llm_client(settings=settings, mode=mode))
        agent = create_application_agent(settings=settings, mode=mode, client=counting)
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        report.add(label, FAIL, f"{type(exc).__name__}: {getattr(exc, 'user_message', exc)}")
        return

    started = time.perf_counter()
    try:
        result = await agent.handle(AgentContext(user_message=UNCERTAIN_QUESTION), db=session)
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        report.add(label, FAIL, f"{type(exc).__name__}: {getattr(exc, 'user_message', exc)}")
        return
    finally:
        try:
            await agent.aclose()
        except Exception:  # noqa: BLE001 - cleanup only
            pass

    duration = round(time.perf_counter() - started, 1)
    ok = result.reply == MISSING_EVIDENCE_REPLY and len(result.sources) == 0 and counting.calls == 0
    report.add(
        label,
        PASS if ok else FAIL,
        f"{duration}s raw_retrieval={len(raw)} passage(s) evidence={result.metadata.get('evidence_count')} "
        f"provider_calls={counting.calls} insufficient_evidence={result.metadata.get('insufficient_evidence')} "
        f"reply='{_preview(result.reply, 70)}'",
    )


async def _check_essay(report: Report, agent, session, *, recorder=None) -> None:
    started = time.perf_counter()
    try:
        result = await agent.handle(AgentContext(user_message=WRITING_BRIEF), db=session)
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        report.add("Ship30for30 article", FAIL, f"{type(exc).__name__}: {getattr(exc, 'user_message', exc)}")
        return

    duration = round(time.perf_counter() - started, 1)
    article = result.reply or ""
    structure = analyze_essay(article)
    ok = bool(article.strip()) and structure.has_title and structure.heading_count >= 2
    provider_detail = ""
    if recorder is not None and recorder.finish_reason is not None:
        provider_detail = f" done_reason={recorder.finish_reason} output_tokens={recorder.output_tokens}"
    report.add(
        "Ship30for30 article",
        PASS if ok else FAIL,
        f"{duration}s skill={','.join(result.skills)} words={structure.word_count} "
        f"target={result.metadata.get('target_words')} reading_time={structure.reading_time_minutes}min "
        f"headings={structure.heading_count} bullets={structure.bullet_count} bold={structure.bold_count} "
        f"takeaway={structure.has_takeaway}{provider_detail}",
    )
    report.add("article preview", PASS if article else FAIL, _preview(article, 140))


#: The artifact requests this harness verifies, in execution order.
ARTIFACT_REQUESTS = (
    ("artifact generation (markdown)", ARTIFACT_MARKDOWN_REQUEST, ARTIFACT_TYPE_MARKDOWN),
    ("artifact generation (HTML/CSS)", ARTIFACT_HTML_REQUEST, ARTIFACT_TYPE_HTML),
)


def _looks_like_html(text: str) -> bool:
    stripped = text.strip().lower()
    return stripped.startswith("<!doctype html") or stripped.startswith("<html") or "<body" in stripped


async def _check_artifacts(report: Report, agent, session, *, types: set[str] | None = None, recorder=None) -> None:
    for label, request, expected_type in ARTIFACT_REQUESTS:
        if types is not None and expected_type not in types:
            continue

        started = time.perf_counter()
        try:
            result = await agent.handle(AgentContext(user_message=request), db=session)
        except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
            report.add(label, FAIL, f"{type(exc).__name__}: {getattr(exc, 'user_message', exc)}")
            continue

        duration = round(time.perf_counter() - started, 1)
        artifact = result.artifact or {}
        content = artifact.get("content") or ""
        css = artifact.get("css") or ""
        contents_ok = bool(content)
        structure_ok = artifact.get("type") == expected_type and bool(artifact.get("title")) and contents_ok
        if expected_type == ARTIFACT_TYPE_HTML:
            structure_ok = (
                structure_ok
                and isinstance(artifact.get("css"), str)
                and _looks_like_html(content)
                and "<style" not in content
                and "{" in css
                and "}" in css
            )
        separate = bool(result.reply) and content not in result.reply
        provider_detail = ""
        if recorder is not None and recorder.finish_reason is not None:
            provider_detail = (
                f" done_reason={recorder.finish_reason} output_tokens={recorder.output_tokens} "
                f"generation_seconds={recorder.duration_seconds}"
            )
        report.add(
            label,
            PASS if structure_ok and separate else FAIL,
            f"{duration}s type={artifact.get('type')} title='{_preview(artifact.get('title') or '', 50)}' "
            f"content_chars={len(content)} css_chars={len(css)}{provider_detail} "
            f"reply='{_preview(result.reply, 70)}'"
            + ("" if separate else " [artifact body leaked into the reply]"),
        )


async def _check_composition(report: Report, agent, session, *, recorder=None) -> None:
    started = time.perf_counter()
    calls_before = recorder.calls if recorder is not None else None
    try:
        result = await agent.handle(AgentContext(user_message=COMPOSED_REQUEST), db=session)
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        report.add("composed request", FAIL, f"{type(exc).__name__}: {getattr(exc, 'user_message', exc)}")
        return

    duration = round(time.perf_counter() - started, 1)
    artifact = result.artifact or {}
    structure = analyze_essay(result.reply or "")
    provider_calls = recorder.calls - calls_before if calls_before is not None else None
    ok = (
        result.skills == ("ship30for30", "artifact_generator")
        and artifact.get("type") == ARTIFACT_TYPE_MARKDOWN
        and bool(artifact.get("content"))
        and structure.word_count > 0
        # Wrapping the finished article is deterministic: a second model call
        # here would mean the artifact was regenerated instead of reused.
        and provider_calls == 1
    )
    report.add(
        "composed request (essay -> artifact)",
        PASS if ok else FAIL,
        f"{duration}s skills={','.join(result.skills)} article_words={structure.word_count} "
        f"artifact_type={artifact.get('type')} artifact_chars={len(artifact.get('content') or '')} "
        f"provider_calls={provider_calls}",
    )


#: Check names accepted by ``--only``, in execution order.
CHECK_NAMES = (
    "knowledge_base",
    "transcript_search",
    "grounded_qa",
    "artifacts",
    "markdown_artifact",
    "html_artifact",
    "insufficient_evidence",
    "essay",
    "composition",
)

#: Report label of every check that needs the knowledge base.
SESSION_CHECK_LABELS = {
    "knowledge_base": "knowledge base contents",
    "transcript_search": "transcript search tool",
    "grounded_qa": "grounded Q&A",
    "artifacts": "artifact generation",
    "markdown_artifact": "artifact generation (markdown)",
    "html_artifact": "artifact generation (HTML/CSS)",
    "essay": "Ship30for30 article",
    "composition": "composed request (essay -> artifact)",
}


async def run_verification(
    *,
    mode: str,
    skip_writing: bool,
    timeout: float | None,
    only: set[str] | None = None,
) -> Report:
    report = Report()
    settings = get_settings()
    if timeout is not None:
        settings = settings.model_copy(update={"llm_timeout_seconds": timeout})

    def selected(name: str) -> bool:
        return only is None or name in only

    print(f"Phase 4 skill verification - mode={mode}, LLM_TIMEOUT_SECONDS={settings.llm_timeout_seconds}")
    if only is not None:
        print(f"Checks: {', '.join(name for name in CHECK_NAMES if name in only)}")
    print("-" * 78)

    needs_session = only is None or any(name in only for name in SESSION_CHECK_LABELS)
    session = _open_session(report) if needs_session else None
    if needs_session and session is None:
        reported: set[str] = set()
        for name, label in SESSION_CHECK_LABELS.items():
            if selected(name) and label not in reported:
                reported.add(label)
                report.add(label, SKIPPED, "the knowledge base is not reachable")

    if mode == MODE_CLOUD and not (settings.anthropic_api_key or "").strip():
        report.add(
            "real provider calls",
            SKIPPED,
            "ANTHROPIC_API_KEY is not configured, so no cloud call was attempted "
            "(cloud execution is covered by the mocked unit tests)",
        )
        return report

    try:
        client = create_llm_client(settings=settings, mode=mode)
        recorder = RecordingClient(client)
        agent = create_application_agent(settings=settings, mode=mode, client=recorder)
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        report.add("provider and agent construction", FAIL, f"{type(exc).__name__}: {getattr(exc, 'user_message', exc)}")
        return report

    num_ctx = getattr(client, "num_ctx", None)
    report.add(
        "provider and agent construction",
        PASS,
        f"provider={client.provider} model={client.model} "
        f"num_ctx={num_ctx if num_ctx is not None else 'runtime default'} "
        f"timeout={settings.llm_timeout_seconds}s "
        f"capabilities={', '.join(agent.registry.available_capabilities())}",
    )

    try:
        if session is not None:
            if selected("knowledge_base"):
                await _check_knowledge_base(report, session)
            if selected("transcript_search"):
                await _check_transcript_search(report, session)
            if selected("grounded_qa"):
                await _check_grounded_qa(report, agent, session)
            artifact_types: set[str] = set()
            if selected("artifacts"):
                artifact_types.update((ARTIFACT_TYPE_MARKDOWN, ARTIFACT_TYPE_HTML))
            if selected("markdown_artifact"):
                artifact_types.add(ARTIFACT_TYPE_MARKDOWN)
            if selected("html_artifact"):
                artifact_types.add(ARTIFACT_TYPE_HTML)
            if artifact_types:
                await _check_artifacts(report, agent, session, types=artifact_types, recorder=recorder)

        if selected("insufficient_evidence"):
            await _check_insufficient_evidence(report, client)
            await _check_insufficient_evidence_live(report, settings, mode, session)

        if selected("essay") or selected("composition"):
            if skip_writing:
                report.add("Ship30for30 article", SKIPPED, "--skip-writing was given")
                report.add("composed request (essay -> artifact)", SKIPPED, "--skip-writing was given")
            else:
                if selected("essay"):
                    await _check_essay(report, agent, session, recorder=recorder)
                if selected("composition"):
                    await _check_composition(report, agent, session, recorder=recorder)
    finally:
        _close_quietly(session)
        try:
            await agent.aclose()
        except Exception as exc:  # noqa: BLE001 - closing must never hide the results
            print(f"note: closing the agent reported {type(exc).__name__}")
        try:
            await client.aclose()
        except Exception as exc:  # noqa: BLE001 - closing must never hide the results
            print(f"note: closing the provider reported {type(exc).__name__}")

    return report


def _close_quietly(session) -> None:
    """Close the session without letting a dropped connection hide the report.

    A long verification can outlive a pooled database connection; the results
    gathered so far are still valid and must reach the summary.
    """
    if session is None:
        return
    try:
        session.close()
    except Exception as exc:  # noqa: BLE001 - cleanup only
        print(f"note: closing the database session reported {type(exc).__name__}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Phase 4 skills against the real provider and knowledge base.")
    parser.add_argument("--mode", default=None, help="provider mode to use: 'cloud' or 'ollama' (default: LLM_MODE)")
    parser.add_argument("--skip-writing", action="store_true", help="skip the two long essay checks")
    parser.add_argument("--timeout", type=float, default=None, help="provider timeout in seconds (default: LLM_TIMEOUT_SECONDS)")
    parser.add_argument(
        "--only",
        default=None,
        help=f"comma-separated subset of checks to run: {', '.join(CHECK_NAMES)}",
    )
    parser.add_argument("--verbose", action="store_true", help="show application logs")
    args = parser.parse_args(argv)

    only: set[str] | None = None
    if args.only:
        requested = {name.strip() for name in args.only.split(",") if name.strip()}
        unknown = sorted(requested - set(CHECK_NAMES))
        if unknown:
            print(f"[{FAIL:^7}] --only: unknown check name(s): {', '.join(unknown)}")
            print(f"          Known checks: {', '.join(CHECK_NAMES)}")
            return 1
        only = requested

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)-7s %(name)s: %(message)s",
    )

    try:
        mode = normalize_llm_mode(args.mode if args.mode is not None else get_settings().llm_mode)
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        print(f"[{FAIL:^7}] LLM mode")
        print(f"          {getattr(exc, 'user_message', exc)}")
        return 1

    report = asyncio.run(
        run_verification(mode=mode, skip_writing=args.skip_writing, timeout=args.timeout, only=only)
    )

    print("-" * 78)
    print(f"Result: {report.summary()}")
    if report.count(FAIL):
        print("One or more checks failed. See the statuses above.")
        return 1
    if report.count(PASS) == 0:
        print("No real check could be performed on this machine.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
