# 001 — Phase 1: Foundation

**Date:** 2026-09-22
**Scope (from `docs/roadmap.md`):** repository structure, FastAPI backend skeleton, CORS, Next.js
frontend skeleton, Tailwind CSS, root `.env.example`, backend configuration management,
Supabase/PostgreSQL connection, initial migrations, `users`/`sessions`/`messages` tables, basic
session API endpoints, frontend ↔ backend connectivity, `agent-transcripts/` directory, and basic
health/connectivity verification.

**Explicit exclusions honoured:** transcript ingestion, chunking, embeddings, `pgvector` retrieval,
Claude Agent SDK, agentic routing, Ship30for30, artifact generation, full chat experience, Ollama
runtime integration.

> **Redaction note.** The database credential that was used during this session (a full PostgreSQL
> connection URI including the password and project reference) has been replaced with
> `<REDACTED>`/`<project-ref>`/`<region>` placeholders in this transcript. This is the only
> redaction applied; every other interaction — including failed attempts — is preserved below.

---

## 1. Starting point

The repository contained only `docs/` (`PRD.md`, `architecture.md`, `design.md`, `roadmap.md`) and an
empty `agent-transcripts/` directory. It was not a git repository.

Environment discovered:

| Tool | Version |
|---|---|
| Python | 3.12.4 |
| Node.js | 22.14.0 |
| npm | 10.9.2 |
| Git | 2.47.0 |
| PostgreSQL client / server | not installed |
| Docker | not installed |
| Ollama | installed at `%LOCALAPPDATA%\Programs\Ollama`, no models pulled |

Because no local PostgreSQL was available, the architecture's documented target (Supabase) had to be
used for the database.

---

## 2. Decisions taken before writing code

| Decision | Rationale |
|---|---|
| `git init` in the project root, no commits made | Phase 1 scope requires "git repository structure"; committing was left to the developer |
| Sync SQLAlchemy 2.x + `psycopg2-binary`, `def` endpoints | Simplest readable setup, works with Supabase's PgBouncer pooler (psycopg2 does not use server-side prepared statements by default) |
| Alembic for migrations | The task requires a schema that another developer can reproduce; a hand-written initial revision is reviewable and deterministic |
| UUID primary keys via `default=uuid.uuid4` + `server_default=gen_random_uuid()` | Python-side IDs are convenient for tests; the server default keeps raw SQL inserts working |
| `ChatSession` ORM class mapped to the `sessions` table | Avoids shadowing SQLAlchemy's `Session` type used for DB sessions |
| Single root `.env` for the backend | One documented source of configuration; `frontend/.env.local` is optional because the browser API base URL defaults to `http://localhost:8000` |
| Only Phase 1 environment variables in `.env.example` | The task states that variables needed later must not be required now; LLM/Ollama/embedding variables are added in the phases that use them |
| `transcript_chunks` and `pgvector` **not** created | The task and roadmap assign them to the Knowledge Base phase |
| No `app/api/chat.py` yet | `/api/chat` is Phase 3+; leaving the module out avoids implementing later phases |
| Backend tests live in `backend/tests/` | `architecture.md` §4 places `tests/` inside `backend/`; the root `tests/` directory from §25 is reserved for cross-stack tests in later phases |

A question was put to the developer at this point: how to obtain a working PostgreSQL instance.
Answer: **provide an existing Supabase `DATABASE_URL`** (matching the architecture's documented
target) rather than installing a local server.

---

## 3. Implementation

### 3.1 Backend

Created `backend/app/` with `main.py` (entry point, CORS, lifespan DB probe), `config.py`
(pydantic-settings + URL normalisation), `errors.py` (error classes and JSON handlers),
`api/` (`health.py`, `sessions.py`, `schemas.py`), `db/` (`database.py`, `models.py`,
`repositories/`), and `services/session_service.py`.

URL normalisation converts `postgres://` and `postgresql://` to `postgresql+psycopg2://` and strips
the `pgbouncer=true` query parameter, which psycopg2 rejects.

Error handling returns readable JSON rather than stack traces:

- `404` — session id not found (`SessionNotFoundError`).
- `503` — `DATABASE_URL` missing, or SQLAlchemy `OperationalError`/`InterfaceError`.
- `422` — FastAPI request validation.

`GET /api/health` intentionally does **not** touch the database, matching `architecture.md` §17.5;
connectivity is probed once at startup and logged instead, so a database outage cannot prevent the
API from starting.

### 3.2 Database

`backend/alembic/versions/0001_initial_schema.py` is a hand-written initial revision creating
`users`, `sessions` and `messages` with UUID primary keys, `TIMESTAMP WITH TIME ZONE` columns,
cascade-deleting foreign keys, a `role IN ('user','assistant','system')` check constraint and three
indexes. `alembic/env.py` injects the URL from the application settings instead of
`alembic.ini` — this also avoids ConfigParser interpolation problems when a password contains `%`
(the credential used here did contain `%40`).

### 3.3 Frontend

`create-next-app` produced Next.js 16.3.5 (App Router, Turbopack, TypeScript, Tailwind CSS v4,
ESLint). Added `lib/api.ts` (typed client with a readable `ApiError`), `types/index.ts`, design
tokens in `app/globals.css`, and a Phase 1 workspace page (`app/page.tsx`) that reports backend
connectivity, lists sessions, creates sessions and displays a session's messages. The page
deliberately contains no composer, streaming, artifacts or agent UI.

Because this Next.js version differs from older conventions, the bundled documentation at
`frontend/node_modules/next/dist/docs/` was read before writing components.

---

## 4. Failures, debugging and corrections

### 4.1 False alarm: "routers are not registered"

**Symptom.** Inspecting the app printed only `/openapi.json`, `/docs`, `/redoc`:

```python
sorted({r.path for r in app.routes if hasattr(r, "path")})
```

**Diagnosis.** Printing route types showed two `_IncludedRouter` objects. In FastAPI 0.141 the
included routers are wrapped, so they do not expose `.path` the way `APIRoute` does.

**Correction.** Verified behaviour instead of internals: `TestClient` calls to `/api/health`
returned `200`, and the session endpoints returned the expected `503` when no database was
configured. No code change was needed — the inspection method was wrong, not the application.

### 4.2 ESLint: `react-hooks/set-state-in-effect`

**Symptom.** `npm run lint` failed on `app/page.tsx`:

```text
44 |   const loadSessions = useCallback(async () => { ... }, []);
46 |     void loadSessions();
     |          ^^^^^^^^^^^^ Avoid calling setState() directly within an effect
```

**Attempt 1 (insufficient).** Moved the first `setState` call after the first `await` so no state
update happens synchronously. The rule still reported the same error.

**Diagnosis.** Four probe components were linted to find which shapes the React Compiler rule
accepts: an async function defined with `useCallback` outside the effect (rejected), a `.then()`
chain (accepted), an async IIFE inside the effect (accepted), and an async function declared *inside*
the effect and invoked with `void load()` (accepted). The rule flags functions defined outside the
effect body.

**Correction.** The data-loading effect now declares `async function load()` inside the effect, guards
state updates with an `ignore` cleanup flag, and reloads through a `reloadToken` state that the Retry
buttons increment. `npm run lint` passes with no warnings.

### 4.3 Database unreachable over IPv6

**Symptom.** `alembic upgrade head` failed:

```text
psycopg2.OperationalError: connection to server at "db.<project-ref>.supabase.co"
(2406:da14:311:1500:a411:bb49:b513:715c), port 5432 failed: Connection timed out (0x0000274C/10060)
```

**Diagnosis.** `ping -6` to that address showed 100% packet loss, and `nslookup -type=A` returned no
A record. Supabase's direct connection host is IPv6-only, and this network has a global IPv6 address
but no working route to that host.

**Correction.** Asked the developer for the Supabase **Session pooler** URI
(`aws-0-<region>.pooler.supabase.com`), which is IPv4-capable. Written to the git-ignored `.env`
(never printed back in tooling output). `alembic upgrade head` then applied `0001_initial_schema`
successfully. This is documented as a troubleshooting note in the README.

### 4.4 Frontend rendered but never hydrated

**Symptom.** The browser showed the correct server-rendered HTML but stayed on "Checking backend…"
with the **New chat** button disabled, and the action was never exposed. `evaluate_script` reported
`hydrated: false` (no React keys on the DOM node), and no request to `localhost:8000` had been made —
although a direct `fetch` from the page context returned `200` for both `/api/health` and
`/api/sessions`, proving the API and CORS configuration were correct.

**Diagnosis.** `frontend/.next` contained production build output (`BUILD_ID`, `prerender-manifest.json`)
*and* dev output (`dev/`), because `npm run build` had been run before `npm run dev`. The dev server
was serving a mix of both.

**Correction.** Stopped the dev server, deleted `.next`, restarted `npm run dev`, and reloaded. The
page hydrated, reported "Backend connected", listed the two existing sessions, created a new session
through the UI, and rendered the persisted messages of a selected session. Documented in the README as
a troubleshooting note.

### 4.5 Non-blocking warnings observed

- `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2
  instead` — emitted by FastAPI's `TestClient` import under Starlette 1.6. Tests pass; left as is
  rather than switching the test client off the supported FastAPI path.
- `DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated` — internal to Starlette, not
  caused by project code.

---

## 5. Verification performed

All commands below were executed; nothing in this list is assumed.

| Check | Command | Result |
|---|---|---|
| Backend imports | `python -c "from app.main import app"` | OK, 3 ORM tables registered |
| Migration applied | `alembic upgrade head` | `Running upgrade -> 0001_initial_schema` |
| Schema inspection | SQLAlchemy `inspect(engine)` | `users`, `sessions`, `messages`, `alembic_version` with the expected columns, FKs, cascade rules and indexes |
| Tests | `pytest -q` | **13 passed** in 21s (unit + integration against Supabase), 2 third-party warnings |
| API health | `curl /api/health` | `200 {"status":"ok"}` |
| Create session | `curl -X POST /api/sessions` | `201` with UUID, title, timestamps |
| List sessions | `curl /api/sessions` | `200`, both created sessions listed newest-first |
| Session messages | `GET /api/sessions/{id}/messages` | `200 {"messages":[]}` for a new session; after inserting two messages through the service layer it returned them in order |
| Not-found handling | `GET /api/sessions/<random-uuid>/messages` | `404 {"detail":"Session ... was not found."}` |
| Validation handling | `GET /api/sessions/not-a-uuid/messages` | `422` |
| Persistence across restart | Stopped and restarted uvicorn, re-listed | Same 2 sessions and 2 messages returned |
| Frontend build | `npm run build` | Compiled, TypeScript passed, `/` prerendered |
| Frontend lint | `npm run lint` | No errors or warnings |
| Browser connectivity | `navigate → snapshot → screenshot` on `http://localhost:3000` | "Backend connected"; sessions listed from Supabase |
| Browser create flow | Clicked **New chat** | New session created via `POST /api/sessions`, listed first, auto-selected |
| Browser message flow | Clicked an existing session | Both persisted messages rendered with role and timestamp |
| Secret check | `git status --short`, `git check-ignore -v .env`, recursive `grep` for the credential | `.env` is ignored and is the only file containing the credential; nothing else to commit contains it |

---

## 6. Files created

```text
.gitignore, .env.example, README.md
backend/requirements.txt, backend/requirements-dev.txt, backend/pytest.ini
backend/app/{__init__,main,config,errors}.py
backend/app/api/{__init__,health,sessions,schemas}.py
backend/app/db/{__init__,database,models}.py
backend/app/db/repositories/{__init__,session_repository,message_repository}.py
backend/app/services/{__init__,session_service}.py
backend/alembic.ini, backend/alembic/env.py, backend/alembic/script.py.mako
backend/alembic/versions/0001_initial_schema.py
backend/tests/{conftest,test_config,test_health,test_sessions_api}.py
frontend/ (create-next-app scaffold) + frontend/lib/api.ts, frontend/types/index.ts
frontend/app/{layout.tsx,page.tsx,globals.css}
ingestion/README.md (placeholder for the Knowledge Base phase)
agent-transcripts/001-phase1-foundation.md (this file)
```

Modified: `frontend/app/globals.css`, `frontend/app/layout.tsx` (replaced scaffold defaults),
removed unused scaffold SVGs from `frontend/public/`.

---

## 7. Not implemented (later phases)

No transcript ingestion, parsing, chunking, embeddings, `pgvector` retrieval, semantic search, RAG,
Claude Agent SDK, application agent, agentic routing, Ship30for30, artifact generation, Artifact
Viewer, Ollama integration, LLM switching, conversational chat, SSE streaming, or advanced UI. The
`/api/chat` module does not exist yet on purpose.

---

## 8. Open items

- Supabase direct connections are IPv6-only; the Session pooler URI is required on networks like this
  one. Recorded in the README.
- `transcript_chunks` / `pgvector` are deferred to Phase 2, so migration `0002` will add the
  extension, the table and the vector index.
- Phase 1 was verified against a Supabase database reachable through the pooler; no local PostgreSQL
  server exists on this machine.
- No git commit was created — the developer asked for the implementation and verification only.

---

## 9. Final validation (re-run on the frozen tree)

After the documentation pass, every check was re-run once on the final tree:

| Check | Command | Result |
| --- | --- | --- |
| Backend tests | `backend/.venv/Scripts/python.exe -m pytest -q` | 13 passed, 2 warnings (third-party deprecations only) |
| Production build | `frontend: npm run build` | Compiled, TypeScript and static generation OK |
| Secret scan | grep for password / project ref / region across the repo (excluding `.env`) | Clean — credential appears only in the git-ignored `.env` |
| Ignore rules | `git check-ignore -v .env backend/.venv frontend/node_modules backend/.pytest_cache` | All matched by `.gitignore` rules |
| Backend live | `curl http://127.0.0.1:8000/api/health` | 200 `{"status":"ok"}` |
| Frontend live | `curl http://localhost:3000/` + browser check | 200; page hydrated, "Backend connected", sessions listed from the database |

The production build had overwritten `.next` with build output, so the dev server was restarted on a
fresh `.next` (same remedy as the hydration issue in section 5) and re-verified in the browser before
handing over. Both servers were left running: backend on `127.0.0.1:8000`, frontend on
`localhost:3000`.
