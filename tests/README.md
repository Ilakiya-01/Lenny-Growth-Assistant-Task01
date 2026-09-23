# tests

This directory is a placeholder for cross-stack tests. Nothing runs from here; it exists so the
repository layout matches the roadmap's directory plan.

Where the tests actually live:

| Layer | Location | Run with |
|---|---|---|
| Backend unit + integration (real database) | `backend/tests/` | `cd backend && python -m pytest -q` |
| Frontend unit + component (jsdom, `fetch` stubbed) | `frontend/tests/lib/`, `frontend/tests/components/` | `cd frontend && npm test` |
| Frontend static analysis | `frontend/` | `npm run lint`, `npx tsc --noEmit`, `npm run build` |
| Knowledge-base CLIs | `ingestion/` | `python ingestion/ingest.py --dry-run`, `python ingestion/search.py "…"` |
| Real-provider check (never collected by pytest, never run in CI) | `backend/scripts/smoke_llm.py` | see the README section on providers |

Cross-stack end-to-end behaviour (browser → Next.js → FastAPI → agent → skills → `pgvector`/Ollama →
rendered UI) was verified by the real-browser pass recorded in
[`../agent-transcripts/006-phase6-integration-and-verification.md`](../agent-transcripts/006-phase6-integration-and-verification.md)
rather than by an automated browser-test suite; adding one (for example Playwright) would be new scope
and is listed as an optional improvement, not as completed work.
