# 007 — Phase 7: Documentation, Submission & Demo Preparation

**Date:** 2026-09-23
**Scope (from the Phase 7 directive):** finalize README and setup documentation, verify repository and
submission cleanliness, verify environment-configuration documentation, confirm the agent transcripts are
complete, prepare the public GitHub state, prepare the demo flow, produce the final submission
checklist, and run one lightweight sanity pass.

**Explicit exclusions honoured:** no new product capability, no frontend/backend/agent/router redesign,
no RAG or embedding architecture change, no database schema change, no new provider, no model swap, the
`qwen3:4b` HTML limitation was not reopened, no token-level streaming, no analytics, no long
local-model experiments. Nothing was pushed to GitHub and nothing was committed: `master` still has
zero commits and no remote is configured, and both require explicit authorization.

> **Redaction note.** The repository-root `.env` was never opened, printed as a whole, copied or
> committed. One incident is recorded honestly in §5: a repository-wide pattern search included `.env`
> in its scope, so the local database URL line surfaced in a tool result before the scan was re-run with
> `.env` excluded. The file itself is unchanged, still git-ignored and still untracked; the consequence
> to act on is a credential-rotation recommendation, not a repository change. No credential value,
> connection string, hidden reasoning or private prompt is reproduced in this transcript.

---

## 1. Repository inspection

`git status`, `git remote -v`, the tree, every documentation file and both application trees were
reviewed first. Findings:

- **No missing submission file.** `README.md`, `docs/PRD.md`, `docs/architecture.md`, `docs/design.md`,
  `docs/roadmap.md`, `agent-transcripts/001…006`, `.gitignore`, `.env.example`, `backend/` (175 files),
  `frontend/` (54 files), `ingestion/` and `tests/` all present.
- **No accidental generated file inside the tree.** The only generated artefacts found were
  `frontend/.next/`, `frontend/next-env.d.ts`, `frontend/tsconfig.tsbuildinfo`, `backend/.pytest_cache/`,
  `backend/**/__pycache__/` and `backend/.venv/` — every one of them matched an ignore rule (verified
  with `git status --porcelain --ignored`).
- **No temporary/debug artefact** (no stray `.log`, `.jsonl`, `.png`, `.bak`, `.orig`, `.swp`, `.pid`,
  `.sqlite` or scratch script inside the repository; Phase 6 probes live outside it, under the OS temp
  directory).
- **No machine-specific absolute path** anywhere in tracked candidates: a scan for the current Windows
  user directory and username returned zero matches.
- **Incorrect phase-status statements** were the main defect class — see §3.
- **Nothing was deleted.** The only candidate for removal was the placeholder directory `tests/`, which
  instead got an accurate README (see §4) because deleting a documented part of the roadmap layout is a
  change an evaluator would read as removal of the integration-test story.

## 2. README finalization

`README.md` grew from 652 to 843 lines, restructured so a fresh evaluator can run the project top to
bottom:

| New / rewritten | Content |
|---|---|
| Opening paragraph | Phases 1–6 complete, Phase 7 is this documentation pass; links to the transcripts |
| **Core capabilities** (new) | Grounded Q&A, Ship30for30, markdown artifacts, HTML/CSS artifact support, session persistence, Cloud/Ollama modes, Artifact Viewer, agentic routing |
| **What works today (Phases 1–6)** | Phase 6 integration verification added as its own bullet; the verification-status paragraph now states exactly which scenarios were live-verified, which were fixture-verified, and that no cloud generation is claimed |
| **Architecture** | The requested end-to-end chain `Browser → Next.js → FastAPI → ApplicationAgent → Router/Skills → Supabase pgvector / LLM provider → structured response → frontend rendering`, drawn with the real numbers (303 episodes / 22,327 chunks) and the "browser talks only to FastAPI" rule |
| **Requirements** (was *Prerequisites*) | Python 3.12+, Node 20+, PostgreSQL with `pgvector`, Ollama or an Anthropic key, the dataset clone, rough ingestion cost |
| **Local setup** (was *Installation*) | The mandated numbered 10 steps in one block: clone → venv → backend deps → frontend deps → `.env` → start Ollama → pull the model → dataset path → migrations + ingestion → run both processes, with Windows and POSIX spellings |
| **Environment variables** | States that `.env.example` is the source of truth, that every listed variable exists there, that Phases 5 and 6 added none, and records the settings actually used for verification (`LLM_MODE=ollama`, `OLLAMA_MODEL=qwen3:4b`, `LLM_TIMEOUT_SECONDS=1800`) |
| **Artifact Viewer** (new section) | Markdown rendering, HTML/CSS rendering, the sandbox and CSP mechanics, what the hostile-fixture proof showed, Preview \| Code, error isolation, and the persistence behaviour of artifacts vs sources |
| **LLM providers → Local mode** | Config block matching the verified settings plus an explicit "expect CPU inference to be slow" step quoting the Phase 6 measurements and naming what removes the wait |
| **LLM providers → Cloud mode** | A boxed verification status: implemented, mocked-tested, config-error path live-verified, **no live cloud generation claimed anywhere** |
| **Ingestion / searching** | Corpus size after a full verified run, and the stale "later phases call it as a tool" sentence replaced by the actual caller |
| **Testing** | Real commands (`python -m pytest -q`, `npm test`, `npm run lint`, `npx tsc --noEmit`, `npm run build`), the Phase 6 regression test described, and the verified counts in bold |
| **Known limitations** (new section) | Table of the five mandated limitations plus the model-budget case, each labelled verified limitation / unavailable credential / cosmetic issue / optional improvement |
| **Demo and submission**, transcripts table, docs list, roadmap table | Links to the two new documents, all seven transcripts listed, Phases 6 and 7 marked complete |

No credential, connection string or real key value appears in it, and no capability the code does not
have is described.

## 3. Documentation consistency

- **Phase statuses:** the README roadmap table said Phases 6 and 7 were "Not started" — the one
  materially wrong statement in the repository. Now 1–6 Complete, 7 complete as this pass.
- **`docs/architecture.md`:** one stale sentence corrected — it claimed `.env.example` "currently lists
  the Phase 1, Phase 2 and Phase 3 variables". The file now covers database/backend/CORS/frontend,
  ingestion, embedding, chunking and both providers, and the sentence says so. No other planning
  document was edited.
- **Planning documents left alone deliberately:** `docs/PRD.md`, `docs/design.md` and `docs/roadmap.md`
  carry no per-phase status claims, and a check for contradictions found none that needed edits — e.g.
  the PRD lists "Response streaming, **if implemented**", so the deliberate per-turn activity design is
  not a contradiction, and the architecture's `CLOUD_LLM_API_KEY` note is already a reconciliation
  note. Rewriting them would have been unnecessary churn.
- **Cloud runtime claim verified against code rather than trusted:** the README's statement that cloud
  mode needs the Claude Code runtime is correct — `app/agent/runtimes.py` imports `claude_agent_sdk` and
  `agent.py` wires `ClaudeAgentRuntime` for the `cloud` mode, while `anthropic==1.7.0` provides the
  provider client. Both pins are in `requirements.txt`.
- **Transcripts** 001–006 exist and were not rewritten; their redaction notes are consistent with this
  phase's.

## 4. Repository cleanliness and generated files

- `tests/README.md` claimed end-to-end tests "are added in the integration phase". Phase 6 verified the
  stack with a real browser pass and a backend regression test rather than adding a browser-test
  framework, so the file now maps every test layer to its real location and command, states that the
  cross-stack check was the Phase 6 browser pass, and names an automated browser suite as new scope
  rather than pretending it exists.
- `.gitignore` audit (directive §6): `.env`, `.env.*` with `!.env.example`, `*.pem`, `*.key`,
  `__pycache__/`, `*.py[cod]`, `.venv/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, coverage,
  `node_modules/`, `.next/`, `out/`, `build/`, `next-env.d.ts`, `*.tsbuildinfo`, npm debug logs,
  `*.log`, `.DS_Store`, `Thumbs.db`, `.idea/`, `.vscode/` — all present. Required content (README,
  `docs/`, `agent-transcripts/`, `.env.example`, all source, both test trees, both ingestion CLIs) was
  checked individually with `git check-ignore -v`: **none of it is ignored**, and the only match in that
  list is `.env.example` being explicitly un-ignored by `.gitignore:6`.
- A fresh-clone hazard was tested rather than assumed: with `frontend/next-env.d.ts` moved away,
  `npx tsc --noEmit` still exits 0 (Next 16 supplies those types from the package), so leaving it
  ignored is safe. The file was restored.

## 5. Security sweep

- Repository-wide scan (excluding `.venv`, `node_modules`, `.next`, `.git`, `__pycache__`, `.env`) for
  provider-key shapes, JWT-shaped tokens, credential-bearing database URLs, `AWS_SECRET`,
  `ACCESS_TOKEN=`, `SECRET_KEY=`, `service_role` and inline password literals: the only hits are the
  **synthetic** values in `backend/tests/test_llm_base.py` (`api_key=sk-ant-abcdef123456`, a fake
  bearer) that exist to assert the redaction patterns remove them, plus fixtures in
  `backend/tests/conftest.py` / `test_agent.py` and a fake `OperationalError` URL in
  `test_chat_api.py`. No real key, password, service-role value or usable connection string is tracked.
- `.env` remains ignored (`.gitignore:4`) and untracked (`git ls-files` count 0); `.env.example`
  contains placeholders only.
- Frontend isolation re-confirmed: `lib/api.ts` is still the only `fetch` site in the app and it points
  at `NEXT_PUBLIC_API_BASE_URL ?? http://localhost:8000`; the only "Anthropic"/"Supabase" strings in the
  frontend are a security comment and the toggle label.
- Logs: no credential-shaped string in the Phase 6/7 server logs; the only in-tree log
  (`frontend/.next/dev/logs/next-development.log`) is inside the ignored `.next` directory.
- **Incident (recorded, not hidden).** The first sweep run did not exclude `.env`, so one grep result
  printed the local `DATABASE_URL` line — a real Supabase pooler username and password — into the
  session output. `.env` itself was not modified, is still ignored and still untracked, and nothing
  containing that value was written into the repository, this transcript or any report. Because the
  value surfaced in a session log, the correct follow-up is to **rotate that database password** in the
  Supabase dashboard; that is a credential-management action for the owner, outside this repository,
  and was not performed here. A targeted follow-up check confirmed that **none** of that line's
  identifying fragments — the project reference, the pooler username or the password — appears in any
  repository file outside `.env`; the only remaining `pooler.supabase.com` hits are the generic
  `<region>.pooler.supabase.com` templates in `README.md` and the Phase 1 transcript. The sweep was
  otherwise re-run with `.env` excluded, which is the result reported above. Lesson kept for future
  phases: exclude `.env` from any repository-wide pattern search instead of filtering its output
  afterwards.

## 6. Demo and submission preparation

Two new documents, both derived only from flows Phases 5 and 6 actually verified:

- **`docs/demo-script.md`** — a 2–3 minute narrated sequence over the 11 required beats (open → New
  chat → `hi` → grounded question → Sources → evidence-floor refusal → Ship30for30 → markdown artifact
  → viewer → Preview \| Code → mode toggle → local mode), because local generation is minutes-long and
  cannot be waited on camera: it opens with a "before you record" step that pre-generates four named
  sessions (each one a verified Phase 6 scenario) and shows two turns live. Every beat has the visible
  result and the line to say, then a "say this / not this" table covering CPU latency, cloud status,
  HTML artifacts, streaming and source persistence, and a short recovery section for the two failure
  modes most likely during a take (stale `.next` cache, Ollama not running).
- **`docs/submission-checklist.md`** — the directive's five groups (required code, required behaviour,
  security, verification, submission) as checked boxes with the measured evidence next to each item
  (390/120 tests, similarity range 0.808–0.826, 1,259-word essay, sandbox assertions, error classes),
  plus the three items deliberately left unchecked — push, YouTube recording, reviewer sign-off — since
  those belong to the owner, not to this phase. It closes with the limitations table.

## 7. Final lightweight verification (Phase 7 re-run)

No expensive scenario was regenerated; the Phase 6 measurements were reused. Commands re-run against the
final tree:

| Check | Result |
|---|---|
| `python -m pytest -q` (backend) | **390 passed**, 1 pre-existing warning, 159 s |
| `npm test` (frontend) | **120 passed** in 10 files, 9.5 s |
| `npm run lint` | clean |
| `npx tsc --noEmit` | clean |
| `npm run build` | success — `/` and `/_not-found` static |
| Backend running | `GET /api/health` → `{"status":"ok"}`, `GET /api/sessions` → `200` |
| Frontend running | `GET /` → `200`; the page renders the restored session, 37 sidebar entries, the composer, both artifact chips and the mode toggle, with no error state |

> Superseded on 2026-09-23 by the post-Phase-7 session-switching fix
> ([`008-post-phase7-session-switch-hotfix.md`](008-post-phase7-session-switch-hotfix.md)), which added 8
> frontend tests: the current totals are 128 frontend / 390 backend (**518**), and the transcript archive
> now runs 001–008. Every row above stays as the point-in-time Phase 7 record.

The dev server was stopped for the production build (so `.next` was not written underneath it) and
started again afterwards; the backend instance was never taken down, and the temporary Phase 6
failure-injection instance on `:8010` remains stopped.

## 8. GitHub preparation state

- `git remote -v` is empty and `master` has **no commits**, so there is nothing to inspect remotely and
  nothing was invented: no credentials, no automated login, no push.
- `git status --porcelain` lists exactly nine untracked entries — `.env.example`, `.gitignore`,
  `README.md`, `agent-transcripts/`, `backend/`, `docs/`, `frontend/`, `ingestion/`, `tests/` — which is
  the intended first-commit content. `git add -A --dry-run` resolves to **159 files** (158 before this
  transcript was written), and `git status
  --porcelain --ignored` confirms every generated directory is excluded.
- Repository name (`lenny-growth-assistant`) matches the README's clone line and the project title.
  Directory structure is meaningful, docs and transcripts are included, tests are included.
- A first commit and a push are the owner's authorized actions; this phase deliberately stopped short
  of both. The commands are recorded in §10 below so nothing is guessed.

## 9. Evaluator review, as the take-home reviewer

Aligned with the assignment and with `docs/PRD.md`/`docs/architecture.md`: agentic architecture
(routing, pathways, registry, composition rules), system design (one chat workflow behind two
transports), RAG grounding with a calibrated evidence floor and refusal instead of invention, four
skills, session management with isolation and race-safe UI, artifact generation as structured data,
a sandboxed Artifact Viewer, local Ollama mode, cloud mode support, accessible UI states, 518 automated
tests (390 backend + 128 frontend, the frontend count raised by the post-Phase-7 fix in
[`008-post-phase7-session-switch-hotfix.md`](008-post-phase7-session-switch-hotfix.md)), eight honest
transcripts including failures, and documentation a newcomer can follow.

Remaining gaps, labelled as the directive requires — none of them turned into implementation work here:

| Gap | Label |
|---|---|
| Local CPU latency; long turns pre-generated for the demo | Verified limitation |
| Cloud mode never exercised against a live API | Unavailable dependency/credential |
| `qwen3:4b` cannot finish live HTML/CSS artifacts | Verified limitation (model) |
| No token-level streaming | Verified limitation (deliberate scope decision) |
| Sources not persisted with the message | Verified limitation |
| No automated browser-level E2E suite; verification was a scripted manual pass | Optional improvement (new scope) |
| "I generated a html artifact…" grammar | Cosmetic issue |
| No evaluation set for retrieval quality beyond the calibrated floor | Optional improvement |
| Rotating the exposed-in-session database password | Security follow-up for the owner, outside the repository |

## 10. Files touched by this phase

| File | Change |
|---|---|
| `README.md` | Finalized for submission (652 → 843 lines) |
| `docs/demo-script.md` | Created |
| `docs/submission-checklist.md` | Created |
| `tests/README.md` | Rewritten to describe where each test layer actually lives |
| `docs/architecture.md` | One stale `.env.example` sentence corrected |
| `agent-transcripts/007-phase7-documentation-and-submission.md` | Created (this file) |

No file under `backend/` or `frontend/` was modified, no dependency changed, no migration added, and no
test altered. If the repository is committed, the intended sequence is
`git add -A && git commit -m "…" && git remote add origin <url> && git push -u origin master` — each
step requires the owner's explicit authorization, and none was run here.

## 11. Phase boundary

This is the last phase of the roadmap. Phases 1–6 were not restarted or redesigned; nothing was pushed
or published; the submission documentation and demo preparation are complete. **Do not start another
phase after this one.**
