#!/usr/bin/env python
"""Real-provider smoke test for the Phase 3 LLM layer and application agent.

Unlike the automated suite (which mocks every provider), this script makes real
calls to the configured provider so the wiring can be verified end to end:

    LLM factory -> provider client -> application agent -> routing decision
                -> capability execution

Usage (from the repository root)::

    backend/.venv/Scripts/python.exe backend/scripts/smoke_llm.py
    backend/.venv/Scripts/python.exe backend/scripts/smoke_llm.py --mode ollama
    backend/.venv/Scripts/python.exe backend/scripts/smoke_llm.py --mode cloud
    backend/.venv/Scripts/python.exe backend/scripts/smoke_llm.py --skip-generation

The Phase 4 skills and tools are verified by ``scripts/smoke_skills.py``.

Results are reported as PASS / FAIL / SKIPPED and are deliberately kept out of
the pytest suite: a provider that is not installed, not running or not
configured must never make the automated tests unreliable. Exit codes: 0 when
every performed check passed, 1 when a performed check failed, 2 when no real
call could be performed at all.

No credential value is ever printed - only whether one is configured.
"""

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agent.agent import create_application_agent  # noqa: E402
from app.agent.context import AgentContext  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.llm.base import LLMMessage  # noqa: E402
from app.llm.factory import MODE_CLOUD, MODE_OLLAMA, create_llm_client, normalize_llm_mode  # noqa: E402
from app.llm.ollama_client import OllamaLLMClient  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
SKIPPED = "SKIPPED"

SMOKE_PROMPT = "Reply with one short sentence about product-market fit."
ROUTING_PROBES = (
    ("What did Lenny's guests say about product-market fit?", "rag_qa"),
    ("Write a 1250-word essay about finding product-market fit.", "ship30for30"),
    ("Create a markdown product strategy document from this discussion.", "artifact_generation"),
    ("Hello, how are you?", "general"),
)


@dataclass
class Check:
    """One smoke-test observation."""

    name: str
    status: str
    detail: str = ""


class Report:
    def __init__(self) -> None:
        self.checks: list[Check] = []

    def add(self, name: str, status: str, detail: str = "") -> Check:
        check = Check(name=name, status=status, detail=detail)
        self.checks.append(check)
        print(f"[{status:^7}] {name}" + (f" - {detail}" if detail else ""))
        return check

    def count(self, status: str) -> int:
        return sum(1 for check in self.checks if check.status == status)

    def summary(self) -> str:
        return f"{self.count(PASS)} passed, {self.count(FAIL)} failed, {self.count(SKIPPED)} skipped"


def _describe_provider(mode: str, settings) -> str:
    if mode == MODE_CLOUD:
        key_state = "configured" if (settings.anthropic_api_key or "").strip() else "not configured"
        return f"anthropic (ANTHROPIC_API_KEY {key_state}, model={settings.anthropic_model or '<unset>'})"
    return f"ollama (base_url={settings.ollama_base_url}, model={settings.ollama_model or '<unset>'})"


async def _check_ollama_availability(report: Report, client) -> bool:
    try:
        models = await client.list_models()
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        report.add(
            "ollama server reachable",
            FAIL,
            f"{type(exc).__name__}: ensure the Ollama server is running at {client.base_url}",
        )
        return False

    report.add("ollama server reachable", PASS, f"{len(models)} model(s) installed")
    if await client.has_model():
        report.add("configured model installed", PASS, client.model)
        return True

    report.add(
        "configured model installed",
        FAIL,
        f"'{client.model}' is not installed - run `ollama pull {client.model}`",
    )
    if models:
        report.add("installed models", SKIPPED, ", ".join(models))
    return False


async def _check_generation(report: Report, client) -> bool:
    try:
        response = await client.generate(
            [LLMMessage(role="user", content=SMOKE_PROMPT)],
            system="You are a concise assistant.",
        )
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        report.add("single generation", FAIL, f"{type(exc).__name__}: {getattr(exc, 'user_message', exc)}")
        return False

    preview = response.text.replace("\n", " ")[:90]
    report.add(
        "single generation",
        PASS,
        f"provider={response.provider} model={response.model} chars={len(response.text)} "
        f"duration={response.duration_seconds}s text='{preview}'",
    )
    return True


async def _check_streaming(report: Report, client) -> None:
    if not client.supports_streaming:
        report.add("streaming generation", SKIPPED, f"{client.provider} does not support streaming")
        return

    chunks: list[str] = []
    try:
        async for chunk in client.stream([LLMMessage(role="user", content=SMOKE_PROMPT)]):
            if not chunk.done and chunk.text:
                chunks.append(chunk.text)
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        report.add("streaming generation", FAIL, f"{type(exc).__name__}: {getattr(exc, 'user_message', exc)}")
        return

    text = "".join(chunks)
    if not text.strip():
        report.add("streaming generation", FAIL, "the stream produced no text")
        return
    report.add("streaming generation", PASS, f"{len(chunks)} chunk(s), {len(text)} chars")


async def _check_agent(report: Report, mode: str) -> None:
    try:
        agent = create_application_agent(mode=mode)
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        report.add("application agent construction", FAIL, f"{type(exc).__name__}: {getattr(exc, 'user_message', exc)}")
        return

    report.add("application agent construction", PASS, f"provider={agent.client.provider} mode={agent.llm_mode}")

    try:
        result = await agent.handle(AgentContext(user_message="Hello, how are you?"))
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        report.add("agent conversational request", FAIL, f"{type(exc).__name__}: {getattr(exc, 'user_message', exc)}")
    else:
        preview = (result.reply or "").replace("\n", " ")[:90]
        report.add(
            "agent conversational request",
            PASS if result.status == "completed" and result.reply else FAIL,
            f"status={result.status} intent={result.intent.value} reply='{preview}'",
        )

    # The knowledge-base pathway executes a capability since Phase 4, so this
    # check needs a database session and reports what the capability produced.
    db = _open_session()
    if db is None:
        report.add(
            "agent knowledge-base pathway",
            SKIPPED,
            "the database is not reachable, so the transcript capability was not executed",
        )
    else:
        try:
            prepared = await agent.handle(
                AgentContext(user_message="What did Lenny's guests say about product-market fit?"),
                db=db,
            )
        except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
            report.add("agent knowledge-base pathway", FAIL, f"{type(exc).__name__}: {getattr(exc, 'user_message', exc)}")
        else:
            ok = prepared.status == "completed" and prepared.reply is not None
            report.add(
                "agent knowledge-base pathway",
                PASS if ok else FAIL,
                f"intent={prepared.intent.value} capability={prepared.capability} "
                f"evidence={prepared.metadata.get('evidence_count')} grounded={prepared.metadata.get('grounded')} "
                f"sources={len(prepared.sources)}",
            )
        finally:
            db.close()

    await agent.aclose()


def _open_session():
    """Open a database session, or return ``None`` when the database is unreachable."""
    from app.db.database import get_session_factory

    try:
        return get_session_factory()()
    except Exception:  # noqa: BLE001 - a missing database is a skip, not a failure here
        return None


async def _check_routing(report: Report) -> None:
    """Routing must recognize all four documented intents without a provider call."""
    from app.agent.router import AgentRouter
    from app.agent.tools import default_registry

    router = AgentRouter(default_registry())
    mismatches: list[str] = []
    for message, expected in ROUTING_PROBES:
        decision = await router.route(AgentContext(user_message=message))
        if decision.intent.value != expected:
            mismatches.append(f"{expected}!={decision.intent.value}")

    report.add(
        "router recognizes the four documented intents",
        PASS if not mismatches else FAIL,
        "; ".join(mismatches) if mismatches else ", ".join(expected for _, expected in ROUTING_PROBES),
    )


async def run_smoke_test(*, mode: str, skip_generation: bool) -> Report:
    report = Report()
    settings = get_settings()

    print(f"LLM smoke test - mode={mode}, {_describe_provider(mode, settings)}")
    print("-" * 78)

    await _check_routing(report)

    if skip_generation:
        report.add("real provider calls", SKIPPED, "--skip-generation was given")
        return report

    if mode == MODE_CLOUD and not (settings.anthropic_api_key or "").strip():
        report.add(
            "real provider calls",
            SKIPPED,
            "ANTHROPIC_API_KEY is not configured, so no cloud call was attempted "
            "(the cloud provider is covered by the mocked unit tests)",
        )
        return report

    try:
        client = create_llm_client(settings=settings, mode=mode)
    except Exception as exc:  # noqa: BLE001 - a smoke test reports, it does not raise
        report.add("provider construction", FAIL, f"{type(exc).__name__}: {getattr(exc, 'user_message', exc)}")
        return report

    report.add("provider construction", PASS, _describe_provider(mode, settings))

    try:
        available = True
        if isinstance(client, OllamaLLMClient):
            available = await _check_ollama_availability(report, client)

        if available:
            await _check_generation(report, client)
            await _check_streaming(report, client)
        else:
            report.add("single generation", SKIPPED, "the configured provider is not reachable")
            report.add("streaming generation", SKIPPED, "the configured provider is not reachable")
    finally:
        await client.aclose()

    await _check_agent(report, mode)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test the configured LLM provider and agent.")
    parser.add_argument(
        "--mode",
        default=None,
        help="provider mode to test: 'cloud' or 'ollama' (default: LLM_MODE)",
    )
    parser.add_argument(
        "--skip-generation",
        action="store_true",
        help="only check routing and configuration, without calling a provider",
    )
    parser.add_argument("--verbose", action="store_true", help="show provider client logs")
    args = parser.parse_args(argv)

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

    report = asyncio.run(run_smoke_test(mode=mode, skip_generation=args.skip_generation))

    print("-" * 78)
    print(f"Result: {report.summary()}")
    if report.count(FAIL):
        print("One or more checks failed. See the statuses above.")
        return 1
    if report.count(PASS) == 0:
        print("No real provider call could be performed on this machine.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
