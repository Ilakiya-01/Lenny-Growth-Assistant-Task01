# The Lenny Growth Assistant

A full-stack, agentic AI conversational web application for exploring product-management and growth
insights from Lenny's Podcast transcripts.

The application is built in the seven phases defined in [`docs/roadmap.md`](docs/roadmap.md), and every
phase is documented by a development-agent transcript in [`agent-transcripts/`](agent-transcripts):
**Phase 1 — Foundation** (project skeleton, FastAPI backend, Next.js frontend, PostgreSQL/Supabase
schema and session persistence), **Phase 2 — Knowledge Base & Ingestion** (transcript discovery,
parsing, token-aware chunking, embeddings and `pgvector` semantic search), **Phase 3 — Agentic Routing
& LLM Factory** (the unified LLM provider layer, the LLM factory, the application agent, the agentic
router and intent classification), **Phase 4 — Core Skills & Tools** (executable transcript search and
grounded Q&A, the Ship30for30 writing skill, markdown and HTML/CSS artifact generation, and the two
composition rules), **Phase 5 — Frontend Workspace & Artifact Viewer** (the production chat workflow,
the session sidebar and chat workspace, activity streaming, the Cloud | Ollama toggle and the Artifact
Viewer), **Phase 6 — Integration & Verification** (the whole application verified end to end, with one
integration defect fixed) and **Phase 7 — Documentation, Submission & Demo Preparation** (this
README, [`docs/demo-script.md`](docs/demo-script.md) and
[`docs/submission-checklist.md`](docs/submission-checklist.md)).

---

## Core capabilities

- **Transcript-grounded Q&A** — answers only from retrieved `pgvector` passages, with the episodes and
  guests cited, and an explicit "not enough evidence" reply instead of a guess.
- **Ship30for30 writing** — a structured ~1,250-word article with hook, headings, bullets and a
  takeaway, measured deterministically rather than self-reported.
- **Markdown artifacts** — generated as structured artifact data and rendered in the Artifact Viewer.
- **HTML/CSS artifact support** — generated as a document plus a separate stylesheet and rendered only
  inside a sandboxed iframe (see [Artifact Viewer](#artifact-viewer)).
- **Session persistence** — sessions and messages in PostgreSQL, exactly one user row and one assistant
  row per successful turn, nothing persisted for a failed turn.
- **Cloud / Ollama LLM modes** — one toggle, sent per request and remembered locally; no automatic
  provider fallback and no credential in the browser.
- **Artifact Viewer** — Preview | Code, copy, full screen, close/reopen, error-isolated.
- **Agentic routing** — a deterministic offline intent classifier feeding an execution pathway and the
  tool registry, with safe high-level activity events instead of hidden reasoning.

---

## What works today (Phases 1–6)

- FastAPI backend with health and session endpoints.
- Next.js frontend that talks to the backend and verifies connectivity.
- PostgreSQL (Supabase) connection configured through environment variables.
- Reproducible Alembic migrations creating the `users`, `sessions`, `messages` and
  `transcript_chunks` tables, plus the `pgvector` extension and the `match_transcript_chunks`
  search function.
- Session persistence: create a session, list sessions, and retrieve a session's messages.
- Graceful, user-readable errors when the database is unavailable or not configured.
- Transcript knowledge base: discovery of a local Lenny transcript repository, YAML frontmatter
  parsing with metadata preservation, token-aware chunking, configurable embeddings (local
  `sentence-transformers` by default, OpenAI by configuration), and idempotent ingestion.
- Vector similarity search over the stored chunks (cosine similarity, HNSW index) with guest and
  episode filters, usable from the `ingestion/search.py` CLI and from Python.
- Unified asynchronous LLM provider interface (`BaseLLMClient`) with generation and streaming.
- Two providers behind that interface: Anthropic cloud models (official SDK) and local Ollama
  models (documented HTTP API).
- An LLM factory selected by `LLM_MODE`, with explicit errors instead of silent provider fallback.
- The application agent: per-request context from a session, agentic routing, intent
  classification, execution-pathway preparation, safe high-level activity events and a structured
  result object.
- Intent classification for `rag_qa`, `ship30for30`, `artifact_generation` and `general`, using a
  deterministic offline classifier by default and optionally the configured provider.
- **Phase 4 capabilities**, all executed through the existing agent/registry: `transcript_search`
  (real retrieval over the Phase 2 `match_transcript_chunks` path, with a calibrated evidence-quality
  floor), `transcript_qa` (answers only from retrieved passages, and states when there is not enough
  evidence without calling the model), `ship30for30` (a structured ~1250-word article, measured
  deterministically) and `artifact_generator` (validated markdown or HTML/CSS artifacts, stylesheet
  kept out of the document body).
- Composition: evidence enrichment for a request that references Lenny's sources, and a finished
  essay wrapped into a markdown artifact without a second model call.
- A dev-only verification endpoint set (`/api/dev/agent/...`) and a real-provider smoke-test script.
- **Phase 5 production chat workflow**: `POST /api/chat` (one complete turn as JSON) and
  `POST /api/chat/stream` (the same turn as Server-Sent Events: `activity`, `artifact_ready`, `done`,
  `error`). Both call one service, `run_chat_turn`, so there is a single chat workflow — the frontend
  never gets its own agent path, and a turn is persisted only after the agent succeeds.
- **The chat workspace**: a session sidebar with New Chat and switching, message rendering with
  Markdown and inline sources, a composer (Enter to send, Shift+Enter for a newline), an optimistic
  pending row, a subtle activity line with an elapsed timer and a Stop control, retryable error
  notices, and empty-state prompt cards that fill the composer without executing.
- **The Cloud | Ollama toggle**, sent as `llm_mode` on every request and remembered locally; the
  frontend holds no provider credentials and talks only to FastAPI.
- **The Artifact Viewer**: hidden unless an artifact exists, ~40% of the desktop workspace,
  independently scrollable, with title and type, Preview | Code, Copy, Full screen, close/reopen from
  the message, and layered Escape handling. Markdown renders through `react-markdown`; `html_css`
  renders only inside a sandboxed iframe (`sandbox="allow-scripts"` plus a `default-src 'none'` CSP),
  never in the application DOM. A preview failure is contained by an error boundary and never affects
  the conversation.
- Backend tests (unit + integration against a real database) and frontend tests (Vitest +
  Testing Library), lint, type-check and production build.
- **Phase 6 integration verification**: the full chain exercised in a real browser over live
  `pgvector` and live Ollama — greeting, grounded Q&A with sources, the evidence-floor refusal, the
  Ship30for30 essay, markdown artifacts in the Artifact Viewer, HTML/CSS artifacts in the sandbox,
  session isolation and late-reply race safety, exactly-once persistence, non-persistence of failed
  turns, all four failure classes, the activity protocol and a secret/traceback sweep. The one real
  integration defect it found (a greeting answered as if it had looked for transcript evidence) was
  fixed and given a regression test.

Verification status: transcript search, grounded Q&A, the insufficient-evidence branch, markdown
artifacts, the composed essay→artifact path, the Ship30for30 essay, session isolation/persistence/race
behaviour and the whole Phase 5 workspace flow (session switching, streaming activity, markdown
artifact rendering in the viewer, Preview | Code, Full screen, close/reopen, the Cloud configuration
error and the Ollama-unavailable error) were verified live against `qwen3:4b` and the ingested corpus.
HTML/CSS artifact **generation** is implemented and tested but does not complete on that local model,
so the viewer's HTML path was verified with valid and malformed test artifacts carried through the real
persistence path — see the Phase 4 and Phase 6 transcripts
([`agent-transcripts/004-phase4-core-skills.md`](agent-transcripts/004-phase4-core-skills.md),
[`agent-transcripts/006-phase6-integration-and-verification.md`](agent-transcripts/006-phase6-integration-and-verification.md)).
**Cloud mode has no live end-to-end verification on this machine because no Anthropic API key is
configured**; what is verified is the cloud implementation's test coverage and its honest
configuration-error path in the browser. No cloud generation is claimed anywhere in this repository.

Everything the application does not do is listed in [Known limitations](#known-limitations). Deployment
and hosting are outside the seven phases of this take-home.

---

## Architecture

One request, end to end:

```text
Browser  (Next.js client, no credentials)
   │  POST /api/chat/stream  { session_id, message, llm_mode }
   ▼
Next.js  (frontend/)  — lib/api.ts is the only fetch code; lib/sse.ts reads the event stream
   ▼
FastAPI  (backend/app)  — app/services/chat_service.run_chat_turn, the single chat workflow
   ▼
ApplicationAgent  (backend/app/agent)  — session context, activity events, structured result
   ▼
Router → Tool Registry → Skills
   rag_qa → transcript_search / transcript_qa      ship30for30      artifact_generator
   │                       │                              │                   │
   ▼                       ▼                              ▼                   ▼
Supabase PostgreSQL + pgvector (303 episodes / 22,327 chunks)     LLM provider
   └────────────── structured response (reply, sources, artifact, activity) ──────────────┘
   ▼
Frontend rendering: message list + Sources disclosure + activity line + Artifact Viewer
```

[`docs/architecture.md`](docs/architecture.md) has the full architecture; the request never carries a
provider credential through the browser and the browser never talks to Supabase, Anthropic or Ollama
directly.

```text
lenny-growth-assistant/
├── backend/            FastAPI application, agent, LLM providers, RAG modules, migrations, tests
├── frontend/           Next.js (App Router, TypeScript, Tailwind CSS)
├── ingestion/          Ingestion and vector-search CLIs
├── docs/               PRD, architecture, design, roadmap, demo script, submission checklist
├── agent-transcripts/  Development-agent transcript archive (001–007) plus one post-phase fix
├── tests/              Placeholder for cross-stack tests (see tests/README.md; the suites live in
│                       backend/tests and frontend/tests)
├── .env.example
└── README.md
```

### Application agent, router, providers and skills (Phases 3-4)

The product runtime is the **application agent**. It is not the coding agent that built this
repository, and it is not the model provider:

```text
                         Application Agent  (backend/app/agent)
                                  │
                                  ▼
                         Agentic Router  ──── classify ──▶  rag_qa | ship30for30
                                  │                          artifact_generation | general
                                  ▼
                        Execution Pathway
                                  │
                                  ▼
                              Tool Registry
                                  │
      ┌───────────────┬───────────┴───────────┬──────────────────┐
      ▼               ▼                       ▼                  ▼
transcript_search  transcript_qa        ship30for30      artifact_generator
 (Phase 2 RAG)   (grounded Q&A)      (writing skill)      (md / html+css)
```

```text
                         Application Agent
                                  │
                                  ▼
                            LLM Factory  (backend/app/llm)
                                  │
                     ┌────────────┴────────────┐
                     ▼                         ▼
            Anthropic Cloud (cloud)      Ollama Local (ollama)
                     │                         │
                     └────────────┬────────────┘
                                  ▼
                    BaseLLMClient - one async interface
```

The distinction in one line each:

| Layer | What it is | Where |
|---|---|---|
| Development coding agent | The build-time agent that wrote this repository | IDE/Qoder - not shipped |
| Application Agent | The product runtime that classifies requests, prepares pathways and produces replies | `backend/app/agent/` |
| LLM Provider | The swappable model execution layer (cloud or local) | `backend/app/llm/` |

### Backend layout

```text
backend/
├── app/
│   ├── main.py                 FastAPI application entry point
│   ├── config.py               Environment-backed settings
│   ├── errors.py               Application errors and HTTP error handlers
│   ├── api/                    Routers and request/response schemas
│   ├── agent/                  Application agent, router, classifier, context, tools, runtimes
│   ├── db/                     Engine, models, repositories
│   ├── llm/                    LLM factory and provider clients (Anthropic, Ollama)
│   ├── rag/                    Discovery, parsing, chunking, embeddings, retrieval, ingestion
│   └── services/               Business logic
├── alembic/                    Migration environment and revisions
├── scripts/                    Developer tools (LLM smoke test)
├── tests/                      Pytest suite
└── requirements*.txt
```

### Frontend layout (Phase 5)

```text
frontend/
├── app/
│   ├── page.tsx                Workspace shell: sidebar, chat pane, artifact viewer
│   ├── layout.tsx              Root layout and fonts
│   └── globals.css             Theme, markdown typography, reduced-motion rules
├── components/
│   ├── Sidebar/                Sidebar, SessionList, NewChatButton
│   ├── LLMSelector/            Cloud | Ollama toggle
│   ├── Chat/                   ChatPane, MessageList, Message, Composer, EmptyState,
│   │                           AgentActivity, ErrorNotice
│   ├── ArtifactViewer/         ArtifactViewer, ArtifactHeader, MarkdownRenderer,
│   │                           HtmlRenderer, ArtifactErrorBoundary
│   └── Markdown.tsx            react-markdown + remark-gfm
├── lib/
│   ├── api.ts                  The only fetch code in the app (typed client for FastAPI)
│   ├── sse.ts                  SSE frame parser over a fetch POST body
│   ├── errors.ts               Error category → user-facing copy
│   ├── artifacts.ts            Sandboxed HTML document builder (CSP)
│   ├── useWorkspace.ts         The workspace state model and chat turn lifecycle
│   └── preferences.ts          localStorage: selected session id and LLM mode
├── tests/                      Vitest suites (lib + components)
└── types/index.ts              Shared API/response types
```

The browser talks to FastAPI and to nothing else: no Supabase, Anthropic or Ollama client, and no
credential of any kind is present in the frontend.

---

## Requirements

- **Python** 3.12+ for the backend.
- **Node.js** 20+ for the frontend (developed with 22 and 24).
- **PostgreSQL with `pgvector`** — [Supabase](https://supabase.com/) (or Railway) is the documented
  target. Migration `0002` creates the `vector` extension, so a plain managed PostgreSQL works too as
  long as `pgvector` is available.
- **Ollama** for local model execution (the mode everything here was verified with), or an Anthropic
  API key for cloud mode.
- **The transcript dataset**: a local clone of
  [`ChatPRD/lennys-podcast-transcripts`](https://github.com/ChatPRD/lennys-podcast-transcripts) outside
  this repository.
- Roughly 10 minutes and a few GB of RAM for the one-time ingestion of the full corpus on a laptop,
  plus patience for CPU inference (see [Known limitations](#known-limitations)).

---

## Local setup

Ten steps from an empty machine to a running application:

```bash
# 1. Clone the project
git clone <repository-url>
cd lenny-growth-assistant

# 2. Create the Python environment (backend)
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

# 3. Install backend dependencies (dev extras bring pytest and the test transport)
pip install -r requirements-dev.txt

# 4. Install frontend dependencies
cd ../frontend
npm install

# 5. Configure the environment — copy the template, then fill in DATABASE_URL
cd ..
cp .env.example .env

# 6. Start Ollama (the desktop app starts it automatically, or run: ollama serve)
# 7. Pull the model named by OLLAMA_MODEL in .env
ollama pull qwen3:4b

# 8. Put the transcript dataset where TRANSCRIPTS_PATH points (default: ../lennys-podcast-transcripts)
git clone --depth 1 https://github.com/ChatPRD/lennys-podcast-transcripts ../lennys-podcast-transcripts

# 9. Apply the migrations, then build the knowledge base
cd backend
alembic upgrade head
cd ..
backend/.venv/Scripts/python.exe ingestion/ingest.py      # macOS / Linux: backend/.venv/bin/python

# 10. Run it
cd backend && uvicorn app.main:app --reload --port 8000    # terminal 1
cd frontend && npm run dev                                 # terminal 2
```

Then open [http://localhost:3000](http://localhost:3000) and check the API at
[http://localhost:8000/api/health](http://localhost:8000/api/health) (expect `{"status":"ok"}`).

Steps 5, 6-7 and 9 have their own detail sections below:
[Environment variables](#environment-variables), [LLM providers: cloud and
local](#llm-providers-cloud-and-local) and [Knowledge base: ingestion and
search](#knowledge-base-ingestion-and-search).

---

## Environment variables

All variables are documented in [`.env.example`](.env.example), which is the source of truth: every
entry below exists in that file and is read by the implementation. The backend reads `.env` from the
repository root. **No real credential ever belongs in this table, in `.env.example` or in git** — only
placeholders.

The machine these phases were verified on runs `LLM_MODE=ollama`, `OLLAMA_MODEL=qwen3:4b` and
`LLM_TIMEOUT_SECONDS=1800`, because a CPU-only local model needs the longer budget; the template ships
the conservative 120 s default that suits a hosted provider.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | yes | – | PostgreSQL connection string (Supabase or Railway) |
| `APP_ENV` | no | `development` | Environment name |
| `API_HOST` | no | `0.0.0.0` | Uvicorn bind host |
| `API_PORT` | no | `8000` | Uvicorn bind port |
| `CORS_ORIGINS` | no | `http://localhost:3000` | Comma-separated browser origins allowed to call the API |
| `NEXT_PUBLIC_API_BASE_URL` | no | `http://localhost:8000` | API base URL used by the browser |
| `TRANSCRIPTS_PATH` | no | `../lennys-podcast-transcripts` | Local clone of the transcript dataset (absolute, or relative to the repository root) |
| `EMBEDDING_PROVIDER` | no | `sentence-transformers` | `sentence-transformers` (local, free) or `openai` (API key required) |
| `EMBEDDING_MODEL` | no | `BAAI/bge-small-en-v1.5` | Embedding model; must match the `vector(384)` column |
| `EMBEDDING_BATCH_SIZE` | no | `64` | Batch size for embedding calls |
| `CHUNK_SIZE` | no | `400` | Maximum chunk size **in tokens** from the model tokenizer |
| `CHUNK_OVERLAP` | no | `60` | Token budget of context repeated between neighbouring chunks |
| `OPENAI_API_KEY` | no | – | Only needed when `EMBEDDING_PROVIDER=openai` |
| `LLM_MODE` | no | `ollama` | Which provider the agent uses: `cloud` (Anthropic) or `ollama` (local). `local` is accepted as an alias of `ollama` |
| `LLM_TIMEOUT_SECONDS` | no | `120` | Timeout for a single provider call. Raise it for slow local CPU inference |
| `ANTHROPIC_API_KEY` | cloud mode only | – | Anthropic API key. Never commit a real key |
| `ANTHROPIC_MODEL` | no | `claude-sonnet-4-5` | Anthropic model alias used in cloud mode |
| `ANTHROPIC_MAX_TOKENS` | no | `2048` | Upper bound on generated tokens per cloud request |
| `OLLAMA_BASE_URL` | no | `http://localhost:11434` | Address of the local Ollama server |
| `OLLAMA_MODEL` | ollama mode only | – | Model to use, for example `llama3.1:8b` or `qwen3:4b` |
| `OLLAMA_NUM_CTX` | no | `0` (Ollama's own default, 4096 tokens) | Context window for the local runtime. A reasoning model spends part of it on its private thinking before it writes anything, so long generations need more than the default. Raising it costs RAM for the KV cache |
| `LLM_ROUTER_LLM_CLASSIFICATION` | no | `false` | Let the configured provider classify low-confidence requests instead of the built-in offline classifier |

The frontend reads `NEXT_PUBLIC_API_BASE_URL` from `frontend/.env.local`. It is optional for local
development because it defaults to `http://localhost:8000`:

```bash
# frontend/.env.local
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Only variables the implementation actually reads are listed, and every one of them exists in
`.env.example`. Phases 5 and 6 added no new variable: the workspace reads a single optional public
variable (`NEXT_PUBLIC_API_BASE_URL`) and every credential stays server-side.

---

## Database setup

1. Create a project at [supabase.com](https://supabase.com/).
2. Open **Project Settings → Database → Connection string** and copy the **URI**.
3. Put it in `.env` as `DATABASE_URL`, replacing the password placeholder with your real password.
4. Apply the schema:

```bash
cd backend
alembic upgrade head
```

The migration is idempotent in the sense that Alembic tracks the applied revision, so it can be run
again safely. To roll back the initial schema:

```bash
alembic downgrade base
```

Both `postgresql://` and `postgresql+psycopg2://` URLs are accepted; the backend normalises the URL
for SQLAlchemy and removes the `pgbouncer` parameter that psycopg2 does not understand.

> **Connection troubleshooting.** Supabase's *direct* connection host (`db.<project-ref>.supabase.co`)
> resolves to IPv6 only. On networks without working IPv6, `alembic upgrade head` fails with
> `connection timed out`. Use the **Session pooler** URI from the same dashboard page instead:
> `postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`.

### Schema

Created by `backend/alembic/versions/0001_initial_schema.py`:

| Table | Columns |
|---|---|
| `users` | `id` (UUID PK), `metadata` (JSONB), `created_at` |
| `sessions` | `id` (UUID PK), `user_id` (FK → `users.id`, cascade), `title`, `created_at`, `updated_at` |
| `messages` | `id` (UUID PK), `session_id` (FK → `sessions.id`, cascade), `role`, `content`, `artifact` (JSONB), `created_at` |

`messages.role` is constrained to `user`, `assistant` or `system`. Indexes cover
`sessions(user_id)`, `sessions(updated_at)` and `messages(session_id, created_at)`.

A single default user is created automatically on first use, because the take-home does not require
authentication.

Created by `backend/alembic/versions/0002_transcript_chunks.py` (Phase 2):

| Table | Columns |
|---|---|
| `transcript_chunks` | `id` (UUID PK), `episode_id`, `guest`, `title`, `youtube_url`, `publish_date` (DATE), `chunk_index`, `content`, `metadata` (JSONB), `embedding` (`vector(384)`), `created_at` |

The same migration issues `CREATE EXTENSION IF NOT EXISTS vector`, creates the HNSW index
`ix_transcript_chunks_embedding_hnsw` (`vector_cosine_ops`, `m = 16`, `ef_construction = 64`), the
B-tree index on `episode_id`, the unique constraint `(episode_id, chunk_index)` used for idempotent
upserts, and the `match_transcript_chunks(...)` SQL function used by retrieval.

---

## Running the application

Start the backend:

```bash
cd backend
.venv\Scripts\activate        # or: source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Start the frontend in a second terminal:

```bash
cd frontend
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The workspace lists your sessions on the left,
chats in the middle and opens the Artifact Viewer on the right when a turn produces an artifact:

1. **New chat** creates a session (the first one is created for you on a fresh workspace).
2. Type a question, an essay request or an artifact request, or click an empty-state card to fill the
   composer, then press Enter (Shift+Enter inserts a newline).
3. Watch the activity line while the model works; **Stop** cancels the request.
4. Pick **Cloud** or **Ollama** before sending — the choice is sent with the request and remembered.
5. When a reply has an artifact, the viewer opens with **Preview | Code**, **Copy source**,
   **Full screen** and **Close**; the message keeps an "Open …" chip so it can be reopened. Escape
   exits full screen first and closes the viewer on a second press.

Local model generation is slow on CPU (a full essay can take ten minutes or more); the activity line
and the elapsed timer are the progress signal, and `LLM_TIMEOUT_SECONDS` must be large enough for the
generation to finish.

- API documentation: [http://localhost:8000/docs](http://localhost:8000/docs)

> **Troubleshooting.** If the page renders but stays on "Checking backend…" and never becomes
> interactive, the `.next` directory may contain a mix of production-build and dev artifacts (for
> example after running `npm run build` and then `npm run dev`). Stop the dev server, delete the
> `.next` directory and start `npm run dev` again.

---

## Artifact Viewer

The right-hand panel exists only when a turn produces a structured artifact (`artifact_ready` on the
stream, `artifact` on the JSON response) and never blocks the conversation.

- **Markdown artifacts** render through `react-markdown` + `remark-gfm`: headings, lists, GitHub task
  lists (drawn read-only), tables, code and quotes, using the project's typography.
- **HTML/CSS artifacts** are assembled by `lib/artifacts.ts` into a standalone document (the artifact's
  stylesheet is injected as a `<style>` block, not left in the body) and rendered **only** inside an
  `<iframe srcDoc=… sandbox="allow-scripts">` — the model's markup never enters the application DOM.
- **Sandboxing.** Without `allow-same-origin` the iframe gets an opaque origin, so the generated page
  cannot read or write the parent document, cookies, storage or the API; the document additionally
  carries `default-src 'none'` (with `img-src data:`, `style-src 'unsafe-inline'`,
  `script-src 'unsafe-inline'`, `base-uri 'none'`, `form-action 'none'`), and the iframe sets
  `referrerPolicy="no-referrer"`. A Phase 6 check loaded a deliberately hostile artifact (a script
  writing into its document, a remote tracking `<img>`, a remote link and an unclosed tag) and
  confirmed the parent stayed clean and the chat stayed usable.
- **Preview | Code** tabs switch between rendered output and the raw source (a `<pre>` of the artifact's
  own text); **Copy source**, **Full screen**, and **Close** are in the header, and the message keeps an
  "Open …" chip so a closed artifact can be reopened (reopening starts on Preview). Escape exits full
  screen first and closes the panel on the second press.
- A render failure is caught by an error boundary inside the panel: the artifact may fail, the chat
  never does.
- Artifacts are stored as structured JSON on the assistant message, so they survive a refresh; the
  transcript sources for a turn are shown live and are not persisted (see
  [Known limitations](#known-limitations)).

---

## Knowledge base: ingestion and search

The knowledge base is built from a local clone of the transcript dataset. The clone lives **outside**
this repository and is never committed:

```bash
git clone --depth 1 https://github.com/ChatPRD/lennys-podcast-transcripts ../lennys-podcast-transcripts
```

Then set `TRANSCRIPTS_PATH` in `.env` (the default `../lennys-podcast-transcripts` resolves from the
repository root, so the command above needs no change). Every `episodes/<slug>/transcript.md` found
below that path is ingested — there is no hard-coded episode list.

### Chunking and embeddings

`CHUNK_SIZE` and `CHUNK_OVERLAP` are **tokens**, counted with the selected model's own tokenizer —
never characters. The default `400`/`60` fits the 512-token window of the default model.

The default embedding provider is local and free: `sentence-transformers` with
`BAAI/bge-small-en-v1.5` (384 dimensions, downloaded from Hugging Face on first run). To use OpenAI
instead, set `EMBEDDING_PROVIDER=openai`, `EMBEDDING_MODEL=text-embedding-3-small` and
`OPENAI_API_KEY`. The database column is `vector(384)`: a model with a different dimension requires a
new migration, and ingestion fails fast with a clear message if the two do not match.

### Running ingestion

```bash
# Validate parsing/chunking without embedding or writing (no model download)
backend/.venv/Scripts/python.exe ingestion/ingest.py --dry-run

# One episode, then the whole corpus
backend/.venv/Scripts/python.exe ingestion/ingest.py --episode ada-chen-rekhi
backend/.venv/Scripts/python.exe ingestion/ingest.py
```

Useful flags: `--limit N` (first N episodes), `--episode SLUG` (repeatable), `--dry-run`,
`--verbose` (log every episode). The run prints a summary — files discovered, episodes processed,
chunks generated/inserted/updated/unchanged/pruned, failures and elapsed time — and exits non-zero if
any episode failed while still processing the rest.

Ingestion is idempotent: chunk identity is `(episode_id, chunk_index)`, unchanged chunks are not
rewritten at all, and each episode is committed separately, so an interrupted run is resumed by
running the same command again.

### Searching

```bash
# Ranks the stored chunks most similar to a question
backend/.venv/Scripts/python.exe ingestion/search.py "how do I find product-market fit?" --top-k 5

# Optional filters
backend/.venv/Scripts/python.exe ingestion/search.py "pricing mistakes" --guest "Madhavan Ramanujam" --min-similarity 0.5
```

From Python, use `app.rag.retrieval.search_transcript_chunks(db, query, top_k=..., guest=...)`, which
embeds the query and calls the `match_transcript_chunks` database function. Retrieval is independent
of the agent; the `transcript_search` tool is the only thing that calls it during a chat turn.

After a full run against the dataset clone, the verified database holds **303 episodes in 22,327
chunks**; `ingestion/README.md` documents the CLI in more detail.

---

## LLM providers: cloud and local

The application agent talks to models through one interface and never switches provider on its own.
`LLM_MODE` decides which provider runs; if that provider is not configured or not reachable, the request
fails with an actionable error instead of quietly using the other one.

### Local mode (Ollama)

1. **Install Ollama** from [ollama.com/download](https://ollama.com/download) and make sure the
   `ollama` command is on your `PATH`.
2. **Pull a model**, for example:

   ```bash
   ollama pull llama3.1:8b
   ```

   Choose a model that fits your machine; a small model answers faster on CPU. Reasoning models
   (such as `qwen3`) work too, but spend part of the token budget on their private thinking, so they
   should be given a higher `LLM_TIMEOUT_SECONDS`. Ollama loads every model with a small default
   context window (4096 tokens) that thinking and the answer both draw from; raise `OLLAMA_NUM_CTX`
   when a long artifact or article is cut short, for example `OLLAMA_NUM_CTX=8192` on a machine with
   enough RAM for the extra KV cache. A reasoning model may spend the whole generation budget on its
   private thinking; the provider accepts a per-call `think` flag for that case, which the skills use
   only where a measured result justified it (see the Phase 4 transcript).
3. **Start Ollama** (the desktop app starts it automatically, or run `ollama serve`). Verify it:

   ```bash
   curl http://localhost:11434/api/tags
   ```

4. **Configure the application** in the root `.env`. This is the exact shape used for every live
   verification in Phases 4–6:

   ```env
   LLM_MODE=ollama
   OLLAMA_BASE_URL=http://localhost:11434
   OLLAMA_MODEL=qwen3:4b
   LLM_TIMEOUT_SECONDS=1800
   ```

   With any other model, set `OLLAMA_MODEL` to its tag and lower the timeout accordingly
   (`120` suits a hosted-scale model or a fast small local model).

5. **Select local mode** — it is the default, so nothing else is needed. If `LLM_MODE` is set to
   `cloud`, change it back to `ollama` (or `local`, which is the same thing).

6. **Expect CPU inference to be slow.** On a laptop CPU the verified model runs at roughly 2–4
   tokens/s: a greeting took about two minutes, a grounded answer about twelve, a full essay about
   sixteen. This is a property of local inference, not of the application — the app layer answered in
   1–12 s in every measurement — and it is why the UI shows an activity line with an elapsed timer and
   a Stop control. A larger or GPU-backed model, or cloud mode, removes the wait without any code
   change.

### Cloud mode (Anthropic)

1. Create an API key in the [Anthropic Console](https://console.anthropic.com/) and put it in `.env`:

   ```env
   LLM_MODE=cloud
   ANTHROPIC_API_KEY=your-key-here
   ANTHROPIC_MODEL=claude-sonnet-4-5
   ```

   `.env` is git-ignored — never commit a real key.

2. Install the Claude Code runtime that the Claude Agent SDK drives. On Windows the SDK requires the
   native `claude.exe`; the npm `claude.cmd` shim is rejected by the SDK. If the runtime is missing, the
   agent reports that cloud execution is unavailable on this machine and suggests switching to
   `ollama` — it never falls back automatically.

> **Verification status, stated honestly.** Cloud mode was **never verified against a live Anthropic
> API on the machine used for Phases 1–7, because no API key is configured there.** What *is* verified:
> the cloud client and runtime are implemented behind the same provider interface and agent as Ollama;
> the automated tests exercise them through a mocked HTTP transport with synthetic keys (so a passing
> cloud test is a mocked test, not a live call); and switching to Cloud in the browser produced the
> honest `503 configuration` error, preserved the draft, persisted nothing, and left the app usable
> after switching back. Do not read any statement in this repository as a claim of live cloud
> generation.

### Verifying a real provider

The pytest suite mocks every provider, so it never needs a network call or a paid API request. To make
real calls, use the smoke-test script:

```bash
# Uses LLM_MODE from .env
backend/.venv/Scripts/python.exe backend/scripts/smoke_llm.py

# Or target one provider explicitly
backend/.venv/Scripts/python.exe backend/scripts/smoke_llm.py --mode ollama
backend/.venv/Scripts/python.exe backend/scripts/smoke_llm.py --mode cloud
backend/.venv/Scripts/python.exe backend/scripts/smoke_llm.py --skip-generation   # routing only
```

It reports each check as `PASS`, `FAIL` or `SKIPPED` (exit code `0` all passed, `1` something failed,
`2` no real call could be made) and prints no credential values. A provider that is not installed,
not running or not configured is reported as skipped, never as a success.

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Health check. Returns `{"status": "ok"}` |
| `POST` | `/api/sessions` | Create a session. Optional body: `{"title": "...", "user_id": "..."}`. Returns `201` with the session |
| `GET` | `/api/sessions` | List sessions, newest first. Optional `user_id` query parameter |
| `GET` | `/api/sessions/{session_id}/messages` | List the messages of one session, oldest first |
| `POST` | `/api/chat` | Run one chat turn and return it complete: `{"session_id": "...", "message": "...", "llm_mode": "cloud"\|"ollama"}` → reply, persisted user/assistant messages, structured `artifact`, `sources`, `activity`, `intent`, `skills`, `metrics`, provider and model |
| `POST` | `/api/chat/stream` | The same turn as Server-Sent Events (same body). Events: `activity` (allow-listed high-level stages), `artifact_ready` (the structured artifact, emitted before `done`), `done` (the full `ChatResponse`), `error` (`{detail, status, category}`) |

Error responses:

| Status | When |
|---|---|
| `404` | The session id does not exist |
| `422` | Request validation failed (for example a malformed UUID) |
| `502` | The provider returned an unusable response, or classification/capability execution failed |
| `503` | The database is unavailable or not configured, or the selected provider is missing, unreachable or timed out |

Both chat routes run the same service (`app.services.chat_service.run_chat_turn`), so there is exactly
one production chat workflow. Messages are persisted only after the agent succeeds: a failed turn
leaves nothing behind and a retry cannot duplicate the user message. There is no `token` event — the
skills generate through the provider's non-streaming call, so partial tokens do not exist to forward.
A failure inside a stream cannot reach the exception handlers (the response has already started), so it
is delivered as an `error` event carrying the same client-safe detail and status the JSON route would
have returned.

### Development-only agent verification (Phase 3)

These three routes exist to verify the agent architecture end to end. **They are not the production
chat API** (that is [`POST /api/chat`](#api-endpoints)), they persist nothing, and they are not
registered at all when `APP_ENV=production`.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/dev/agent/capabilities` | The configured mode, the available providers, and every known capability with whether it is implemented |
| `POST` | `/api/dev/agent/route` | Classify a request: `{"message": "..."}` → intent, confidence, execution path, capability and availability. Classifies only — it never executes a capability |
| `POST` | `/api/dev/agent/respond` | Run one request through the agent: `{"message": "...", "session_id": "...", "llm_mode": "..."}`. With `session_id` the session's history is loaded read-only; with `llm_mode` a temporary agent is built for that provider |

Status codes for the agent routes: `404` unknown session, `422` invalid request body, `502` the provider
returned an unusable response or classification failed, `503` the configured provider is missing,
unreachable or timed out.

---

## Testing

```bash
cd backend
.venv\Scripts\activate          # or: source .venv/bin/activate
python -m pytest -q             # 390 tests, ~2.5 minutes, no network
```

The suite covers Phases 1–6: configuration normalisation, the health and session endpoints,
transcript discovery, frontmatter parsing and metadata preservation, token-aware chunking (with a
fake tokenizer), the embedding provider factory, and — against the real database — idempotent
upserts, pruning and vector search. Phase 3 adds the LLM provider contract, both providers, the LLM
factory, the intent classifier, the router, the agent context and runtimes, the tool registry, the
activity log and the development-only agent endpoints. Phase 4 adds the four skills, the search tool
and the composition rules. Phase 5 adds the production chat routes: both transports, persistence,
structured artifact delivery, activity forwarding, client-safe error frames, and the guarantee that a
failed turn persists nothing. Phase 6 adds the integration regression test that pins the general
conversational path: a greeting must stay on `direct_response`, must emit no retrieval event, must
make exactly one model call and must persist both messages once.

Provider tests never call a paid API. The Anthropic provider is exercised against the pinned SDK
through its own mocked HTTP transport, and the Ollama provider through a mocked HTTP transport, so
the whole suite runs offline. Unit tests run without a database. The integration tests require
`DATABASE_URL` to be configured and the migrations to be applied; they are skipped automatically
when no database is configured or migrated, and they clean up the rows they create.

The real-provider smoke test is deliberately separate from this suite: it is not collected by
pytest and it is never run in CI, because it needs a live provider. See
[LLM providers: cloud and local](#llm-providers-cloud-and-local) for how to run it and how to read
its exit codes.

Frontend checks:

```bash
cd frontend
npm run lint       # ESLint — clean
npm run typecheck  # tsc --noEmit — clean
npm test           # Vitest + Testing Library (jsdom) — 128 tests in 10 files
npm run build      # production build — succeeds (routes / and /_not-found, static)
```

Verified on the final state of this repository (Phase 6, again in Phase 7, and again after the
post-Phase-7 session-switching fix described in
[`agent-transcripts/008-post-phase7-session-switch-hotfix.md`](agent-transcripts/008-post-phase7-session-switch-hotfix.md)):
**backend 390 passed, frontend 128 passed — 518 automated tests in total — lint clean, typecheck
clean, build green.**

The frontend suite runs entirely offline: `fetch` is stubbed, so no test reaches the backend, a
provider or a paid API. It covers the SSE parser, the typed API client, error-copy mapping, the
sandboxed-artifact document builder, the workspace state hook (bootstrap, session switching and
isolation, the send/cancel/retry lifecycle, artifact open/close/reopen, mode persistence) and the
components (sidebar, toggle, message rendering, chat pane states, and the Artifact Viewer including
its iframe sandbox attributes, Preview | Code, copy, full screen, Escape ordering and error boundary).

Run the backend before the frontend checks only if you point the tests at a live API — the suites
themselves do not need one. `npm run build` writes `.next`; if you then run `npm run dev` and the page
stuck on "Checking backend…", delete `.next` and start `npm run dev` again.

---

## Known limitations

Everything below was observed, not inferred. Each item is labelled the way the Phase 6 transcript
labels it.

| Limitation | Kind | Detail |
|---|---|---|
| **Local CPU latency** | Verified limitation | `qwen3:4b` on CPU generates at roughly 2–4 tokens/s. Measured in Phase 6: a greeting 121 s, a warm general turn in a long session 380 s, a short grounded answer 762 s, the Ship30for30 essay 985 s, a markdown artifact 697 s. The application layer itself answered in 1–12 s and made the minimum number of model calls on every measured path. `LLM_TIMEOUT_SECONDS=1800` and the activity line with its elapsed timer exist for this reason. |
| **Cloud mode is not live-verified** | Unavailable dependency/credential | No Anthropic API key exists on the verification machine. Cloud mode is implemented, unit-tested against a mocked provider transport, and its `503 configuration` error path was exercised in the browser; no cloud generation is claimed anywhere. Add a key and it is a configuration change, not a code change. |
| **No token-level streaming** | Verified limitation (by design) | Skills generate through the provider's non-streaming call, so there are no partial tokens to forward; `/api/chat/stream` emits activity stages, `artifact_ready`, `done` and `error`. The provider interface does expose generation and streaming primitives, but wiring token-level output would reopen the provider and skill architecture and was out of scope. |
| **Sources are not persisted** | Verified limitation (Phase 5 decision) | `sources` arrive with the live turn and render behind the "Sources (n)" disclosure; after a refresh the answer and any artifact come back but the source list does not. Persisting them would change the message schema, which Phase 6 was not allowed to do. |
| **The current local model cannot finish HTML/CSS artifacts** | Verified limitation of `qwen3:4b` | HTML/CSS artifact generation is implemented, structurally validated and test-covered, and the viewer's HTML path is verified with valid and malformed fixtures — but this model spends its budget on private thinking and returns no HTML. The `502 llm_response` error it produces is honest and actionable, and nothing is persisted. Use a cloud mode or a non-reasoning local model for live HTML. |
| **Long compound questions can exhaust the answer budget** | Verified limitation | One 838 s compound PMF question returned `502 llm_response` ("used the whole token budget without returning an answer"); a shorter re-ask grounded correctly. Phase 4 measured that disabling thinking does not fix it on this model. |
| **"I generated a html artifact…"** | Cosmetic issue | The artifact confirmation sentence uses an article that does not agree with "html". Left alone deliberately: rewording it would churn working Phase 4 output for no functional gain. |
| **One-time ingestion cost** | Optional improvement | A full first ingestion downloads the embedding model and embeds 22,327 chunks locally (tens of minutes on a laptop CPU). It is idempotent, so re-running it is cheap. |
| **Retrieval quality is calibrated, not learned** | Optional improvement | The 0.71 evidence floor and top-k are tuned by measurement (Phase 4, re-confirmed in Phase 6) rather than by a labelled evaluation set; a richer eval harness would be new scope. |

---

## Demo and submission

- [Demo script (2–3 minutes)](docs/demo-script.md) — the known-good flows in the order they should be
  shown, with the prompts to type and the honest wording for each limitation.
- [Submission checklist](docs/submission-checklist.md) — what must be present, what was verified and
  how to re-check it.

---

## Development-agent transcripts

One transcript per phase is stored in [`agent-transcripts/`](agent-transcripts), plus one entry for the
post-Phase-7 bug fix that followed them. Each records
what was attempted, what failed, what was corrected and what was verified:

| Transcript | Phase |
|---|---|
| [`001-phase1-foundation.md`](agent-transcripts/001-phase1-foundation.md) | Foundation |
| [`002-phase2-ingestion.md`](agent-transcripts/002-phase2-ingestion.md) | Knowledge base and ingestion |
| [`003-phase3-llm-factory-and-router.md`](agent-transcripts/003-phase3-llm-factory-and-router.md) | Application agent, LLM factory and router |
| [`004-phase4-core-skills.md`](agent-transcripts/004-phase4-core-skills.md) | Core skills and tools |
| [`005-phase5-frontend-and-artifact-viewer.md`](agent-transcripts/005-phase5-frontend-and-artifact-viewer.md) | Frontend workspace and Artifact Viewer |
| [`006-phase6-integration-and-verification.md`](agent-transcripts/006-phase6-integration-and-verification.md) | Integration and verification |
| [`007-phase7-documentation-and-submission.md`](agent-transcripts/007-phase7-documentation-and-submission.md) | Documentation, submission and demo preparation |
| [`008-post-phase7-session-switch-hotfix.md`](agent-transcripts/008-post-phase7-session-switch-hotfix.md) | Post-Phase-7 bug fix (not a phase): in-flight chat state preserved across session switching |

Secrets are redacted from the transcripts; nothing else is filtered, so failures and corrections are
preserved. No transcript, source file or log contains an API key, password, connection string or hidden
model reasoning.

---

## Documentation

- [Product requirements](docs/PRD.md)
- [Architecture](docs/architecture.md)
- [UI/UX design](docs/design.md)
- [Implementation roadmap](docs/roadmap.md)
- [Demo script](docs/demo-script.md)
- [Submission checklist](docs/submission-checklist.md)

---

## Roadmap status

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: repo, FastAPI, Next.js, database, sessions | Complete |
| 2 | Knowledge base: transcript ingestion, embeddings, `pgvector` | Complete |
| 3 | Application agent and LLM provider layer | Complete |
| 4 | Core skills and tools (transcript Q&A, Ship30for30, artifacts) | Complete |
| 5 | Frontend workspace and Artifact Viewer | Complete |
| 6 | Integration and verification | Complete |
| 7 | Documentation and submission | Complete — this documentation pass |

The seven phases above are the complete roadmap; there is no Phase 8. After the Phase 7 submission gate one
focused bug fix was made to the Phase 5 workspace (an in-flight chat request was cancelled by switching
sessions), documented in
[`agent-transcripts/008-post-phase7-session-switch-hotfix.md`](agent-transcripts/008-post-phase7-session-switch-hotfix.md).
It changed no scope, architecture, RAG behaviour, schema or design.
