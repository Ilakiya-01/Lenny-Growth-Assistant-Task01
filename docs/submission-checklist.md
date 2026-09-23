# Submission checklist — The Lenny Growth Assistant

Checked items were verified in Phase 6 or Phase 7; the evidence column says where. Items left
unchecked are the ones that need the reviewer/author to act (recording, pushing), not work that was
skipped silently.

## Required code

- [x] `backend/` — FastAPI app, application agent, router, skills, providers, RAG modules, Alembic
      migrations, pytest suite (`backend/app`, `backend/tests`)
- [x] `frontend/` — Next.js App Router workspace, Artifact Viewer, typed API client, Vitest suite
      (`frontend/app`, `frontend/components`, `frontend/lib`, `frontend/tests`)
- [x] `ingestion/` — `ingest.py` and `search.py` CLIs plus `ingestion/README.md`
- [x] Tests — 390 backend, 128 frontend (518 total), no test weakened or skipped to pass
- [x] `docs/` — PRD, architecture, design, roadmap, this checklist, the demo script
- [x] `agent-transcripts/` — 001…007, one per phase, failures and corrections included, plus 008
      documenting the post-Phase-7 session-switching bug fix

## Required application behavior

All live-verified over real `pgvector` (303 episodes / 22,327 chunks) and real local Ollama:

- [x] Sessions — create, list, switch, New chat, auto-title; a request that is still in flight survives
      switching and keeps its own session's state
- [x] Persistence — one user row + one assistant row per successful turn; failed turns persist nothing;
      history and artifacts restored after refresh
- [x] RAG — token-aware chunks, `bge-small-en-v1.5` embeddings, cosine search over `match_transcript_chunks`
- [x] Grounded Q&A — answers cite retrieved episodes/guests; 5 sources at 0.808–0.826 similarity in the
      verified run
- [x] Evidence floor — below the calibrated threshold the app refuses without calling the model
- [x] Ship30for30 — 1,259 words against the 1,250 target, 7 headings, 3 bullets, 8 bold phrases,
      title + takeaway, measured deterministically
- [x] Artifacts — markdown generated end to end; HTML/CSS generated, structurally validated, and
      rendered from stored structured data
- [x] Artifact Viewer — Preview | Code, Copy, Full screen, Close/reopen, error-isolated
- [x] Ollama local mode — default provider for every live check
- [x] Cloud support — implemented and mocked-tested; **live cloud generation not verified (no key)**
- [x] Agentic routing — offline intent classifier, execution pathways, tool registry, composition rules,
      general path proven to retrieve nothing
- [x] Error handling — `llm_unavailable`, `configuration`, artifact failures and database unavailability
      verified by actual category, status, user-safe copy and zero persistence
- [x] Sandbox security — `srcDoc` + `sandbox="allow-scripts"`, `default-src 'none'` CSP, opaque origin
      proven by `contentDocument === null` from the parent

## Security

- [x] No secrets in tracked files — repository-wide scan found no API keys, passwords, service-role
      values, bearer tokens or credential-bearing URLs (only synthetic test placeholders such as
      `sk-ant-test-not-a-real-key`, which exist to assert redaction)
- [x] `.env` ignored — `git check-ignore -v .env` → `.gitignore:4`; `git ls-files` shows no `.env`
- [x] `.env.example` tracked and placeholder-only
- [x] No credentials, prompts or hidden reasoning in logs, transcripts, tests or UI copy
- [x] Frontend calls only the FastAPI origin (`lib/api.ts` is the only `fetch` site)
- [x] Generated HTML contained in the sandboxed iframe

## Verification

- [x] Backend tests — `cd backend && python -m pytest -q` → 390 passed
- [x] Frontend tests — `cd frontend && npm test` → 128 passed in 10 files
- [x] Lint — `cd frontend && npm run lint` → clean
- [x] Typecheck — `cd frontend && npx tsc --noEmit` → clean
- [x] Build — `cd frontend && npm run build` → success (`/`, `/_not-found`)
- [x] Local sanity check — backend starts, frontend starts, `GET /api/health` → `{"status":"ok"}`,
      browser loads the workspace
- [x] Real-browser end-to-end pass — the 19-step Phase 6 run (`agent-transcripts/006-…md` §11)
- [x] Post-Phase-7 session-switching fix — live CASE 1 and CASE 2 in the browser plus 8 new tests
      (`agent-transcripts/008-post-phase7-session-switch-hotfix.md` §5–§6)

## Submission

- [x] README complete — overview, capabilities, architecture chain, requirements, 10-step setup,
      env variables, ingestion, Ollama, cloud honesty, testing, Artifact Viewer, known limitations
- [x] Demo script ready — `docs/demo-script.md`
- [x] This checklist complete
- [ ] GitHub repository pushed — the repository is prepared (tree, README, docs, transcripts, tests;
      `.gitignore` verified; no secrets) but **nothing has been committed or pushed**: `master` still
      has no commits and no remote is configured, and pushing requires explicit authorization
- [ ] YouTube recording — planned, not produced; follow `docs/demo-script.md`, including its
      pre-generated sessions
- [ ] Final project review — reviewer sign-off

## Remaining limitations (stated, not hidden)

| Item | Kind |
|---|---|
| Local CPU latency (2–4 tokens/s; minutes per long turn) | Verified limitation |
| Cloud mode not live-verified | Unavailable credential |
| No token-level streaming | Verified limitation, deliberate |
| Sources shown live, not persisted with history | Verified limitation |
| `qwen3:4b` cannot finish live HTML/CSS artifacts | Verified model limitation |
| Long compound questions can exhaust the token budget (`502 llm_response`) | Verified model limitation |
| "I generated a html artifact…" grammar | Cosmetic issue |
| One-time local ingestion cost; retrieval calibrated without a labelled eval set | Optional improvement |
