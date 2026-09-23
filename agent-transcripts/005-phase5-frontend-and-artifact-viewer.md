# 005 — Phase 5: Frontend Workspace & Artifact Viewer

**Date:** 2026-09-22 (live verification continued into 2026-09-23)
**Scope (from `docs/roadmap.md`):** the production chat workflow the frontend calls, the session
sidebar and workspace, message and Markdown rendering, the composer, loading/error/activity states,
the Cloud | Ollama toggle, the Artifact Viewer (Markdown and sandboxed HTML/CSS, Preview | Code),
responsive and accessible behaviour, and Phase 5 frontend/integration tests.

**Explicit exclusions honoured:** no Phase 6 or Phase 7 work; no new database, vector, RAG, agent,
router, registry or provider architecture; no second agent workflow for the frontend; no deployment
scripts; no API key, connection string or Supabase reference anywhere in the frontend; no `<artifact>`
tag parsing in the client; no large state-management framework; no generated HTML injected into the
application DOM.

> **Redaction note.** The repository-root `.env` holds real credentials and was never read in full,
> printed or committed in this phase; it stays git-ignored (`git check-ignore -v .env` →
> `.gitignore:4`). The only `.env` lines quoted here are non-secret local settings (`LLM_MODE`,
> `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `LLM_TIMEOUT_SECONDS`). No API key, password, connection string,
> hidden reasoning, private prompt or tool argument appears in this transcript, in the source, in the
> tests or in the captured UI text. The browser evidence below is accessibility-tree text, which
> contains rendered UI copy only.

---

## 1. Starting point

Phases 1–4 were complete and verified: FastAPI + Next.js + PostgreSQL/`pgvector` with 303 ingested
episodes (22,327 chunks), the provider layer and LLM factory, the application agent with deterministic
routing, and four executable capabilities (`transcript_search`, `transcript_qa`, `ship30for30`,
`artifact_generator`) plus the two composition rules.

The frontend was still the Phase 1 connectivity skeleton: it could reach `/api/health`, create a
session and list a session's messages, and it rendered a status card. There was **no** chat endpoint
to call — the only agent-facing routes were the development-only `/api/dev/agent/...` set, which
persists nothing and is unregistered in production. So Phase 5 began with the one piece of backend work
the directive permits: a minimal production `/api/chat` that connects the existing `ApplicationAgent`
to the browser.

---

## 2. Inspection before writing code

| Surface | What was found | What it decided |
|---|---|---|
| `app/services/` | Session create/list/messages services, no chat service | One new `chat_service.run_chat_turn` becomes the single production workflow; both routes call it |
| `app/agent/agent.py` → `AgentResult` | `reply`, `artifact` (structured dict), `sources`, `activity`, `metadata`, `intent`, `skills`, `llm_mode`, `provider`, `model` | The response schema mirrors this shape; nothing has to be parsed back out of prose |
| `app/agent/activity.py` | `ActivityReporter` with a fixed, allow-listed set of activity kinds | The stream can forward activity verbatim: it already excludes prompts, reasoning and tool arguments |
| `app/errors.py` | `ERROR_STATUS` table, per-error `user_message`, and exception handlers | Streaming cannot use exception handlers (the response has already started), so the same table was exposed through two reusable helpers, `http_status_for()` and `user_message_for()`, and an `error` frame is built from them |
| `messages.artifact` | JSONB column already storing `{type,title,content[,css]}` | The viewer renders that payload as delivered; no new column, no migration |
| `get_db` dependency | FastAPI closes request dependencies before a streaming body runs | The SSE generator owns its session (`get_session_factory()()`) and closes it in `finally` |
| Frontend skeleton | `app/page.tsx` status card, no typed API layer, no components beyond layout | A typed `lib/api.ts` plus one state hook, so no component owns `fetch` |
| Provider reality on this machine | Ollama only, `qwen3:4b`, no Anthropic key, CPU inference at roughly 2–4 tokens/s | Cloud mode had to be verified as an honest configuration error, never as a fabricated success; `LLM_TIMEOUT_SECONDS` was raised for local generation |

---

## 3. Decisions taken before writing code

1. **One workflow, two transports.** `POST /api/chat` returns the completed turn as JSON;
   `POST /api/chat/stream` returns the same turn as SSE. Both call `run_chat_turn`. There is no second
   agent path for the frontend, and the dev-only routes were left untouched.
2. **No `token` event.** The directive lists `token` among the preferred events, but the skills
   generate through the provider's non-streaming call, so no partial tokens exist. Inventing them
   would fake progress; the finished assistant text travels inside `done`. This is a deliberate,
   documented deviation from the suggested event list, and the activity events carry the progressive
   feedback instead.
3. **Persist only after success.** A turn writes its two messages after the agent returns, so a failed
   turn leaves nothing behind: the client keeps the draft, and Retry cannot duplicate a user message.
4. **Structured artifacts only.** An artifact is emitted as its own `artifact_ready` frame and as
   `ChatResponse.artifact`. The client never parses tags out of assistant text — there is no code path
   that could.
5. **State: one hook, no framework.** `lib/useWorkspace.ts` owns exactly the directive's state model
   (`selectedSessionId, sessions, messages, artifact, llmMode, loading, activity, error`) plus the
   composer draft. React state + one hook was sufficient; Redux/Zustand would have added indirection
   without removing any.
6. **Untrusted HTML goes in a sandbox.** `html_css` artifacts are rendered into an iframe `srcDoc`
   with `sandbox="allow-scripts"` (no `allow-same-origin`, no top navigation, no forms) and an injected
   CSP that disables network access. Markdown is rendered through `react-markdown` + `remark-gfm`,
   which builds an AST — raw HTML in model output is never executed.
7. **Errors are mapped, not surfaced.** The client shows copy from `lib/errors.ts`, keyed by the
   backend's `category`, so a driver message or stack frame can never reach the screen. The
   Ollama-unavailable sentence is exactly the one the directive specifies.

---

## 4. What was built

### 4.1 Backend (the permitted minimal integration)

| File | Change |
|---|---|
| `backend/app/api/chat.py` | **New.** `POST /api/chat` and `POST /api/chat/stream`; `StreamingActivityReporter` publishes allow-listed activity as it happens; `stream_events()` owns its DB session; `error_payload()` builds a client-safe `error` frame from `user_message_for`/`http_status_for`/`error_category`; `STREAM_HEADERS` disables proxy buffering |
| `backend/app/services/chat_service.py` | **New.** `run_chat_turn()` — resolve mode, reuse the process-wide cached agent (`@lru_cache get_chat_agent`), build `AgentContext` from the session, run the agent, persist both messages, derive a short session title, return a `ChatTurn` with a safe `metrics()` subset |
| `backend/app/api/schemas.py` | Added `ChatRequest`, `ChatResponse`, `MessageResponse`, `ArtifactModel`, `SourceModel`, `ActivityModel`; the dev-agent response models now reuse `ArtifactModel`/`SourceModel` instead of duplicating the shapes |
| `backend/app/db/repositories/session_repository.py`, `backend/app/services/session_service.py` | Added `rename_session()`, used to derive a short sidebar title from the first user message |
| `backend/app/errors.py` | Added `http_status_for()` / `user_message_for()` over the existing `ERROR_STATUS` table and message constants |
| `backend/app/api/dev_agent.py` | Import adjusted for the shared schema models; behaviour unchanged |
| `backend/app/main.py` | Registered `chat.router` in every environment; the dev-only router stays behind `APP_ENV` |
| `backend/tests/test_chat_api.py` | **New.** Both routes, persistence, artifact delivery, activity forwarding, error frames, and the guarantee that a failed turn persists nothing |

No change to the agent, router, registry, skills, providers, RAG modules, models or migrations.

### 4.2 Frontend

```text
frontend/
├── app/page.tsx                 Workspace shell: sidebar (drawer below md), chat pane, artifact viewer
├── app/globals.css              Theme + .markdown typography + prefers-reduced-motion block
├── lib/
│   ├── api.ts                   The only fetch code: health, sessions, messages, chat, streamChat
│   ├── sse.ts                   SSE frame parser over a fetch POST body reader
│   ├── errors.ts                Error → user-facing copy (category keyed), exact Ollama sentence
│   ├── artifacts.ts             buildArtifactDocument(): sandboxed HTML document + CSP
│   ├── useWorkspace.ts          The state model, session switching, send/cancel/retry, mode
│   └── preferences.ts           localStorage: selected session id and LLM mode only
├── components/
│   ├── Sidebar/                 Sidebar, SessionList, NewChatButton
│   ├── LLMSelector/             LLMModeToggle (Cloud | Ollama, aria-pressed)
│   ├── Chat/                    ChatPane, MessageList, Message, Composer, EmptyState,
│   │                            AgentActivity, ErrorNotice
│   ├── ArtifactViewer/          ArtifactViewer, ArtifactHeader, MarkdownRenderer, HtmlRenderer,
│   │                            ArtifactErrorBoundary
│   └── Markdown.tsx             react-markdown + remark-gfm
└── tests/                       10 Vitest files (lib + components), fixtures.ts
```

Behavioural points worth recording:

- **Empty-state prompt cards fill the composer and do not execute.** Clicking a card sets the draft and
  focuses the textarea; nothing is sent until the user presses Send/Enter.
- **Activity is subtle.** One line with the current stage plus an elapsed timer, and a Stop control.
  Stages come from the backend's allow-listed kinds; no prompt, reasoning or tool argument is
  rendered, and the UI is not a debug console.
- **Session switching is race-safe.** A selection token (`selectionRef`) is captured at send time; a
  turn that finishes after the user switched sessions is not written into the new conversation (it is
  persisted in its own session and reappears when that session is opened). Switching also aborts the
  in-flight request and clears the artifact view.
- **The viewer is hidden without an artifact** — it is not rendered at all, so there is no empty panel.
  With an artifact it takes ~40% of the desktop workspace (`lg:w-[40%]`, `lg:min-w-[22rem]`), is
  independently scrollable, and below `lg` becomes a full-screen overlay so the narrow layout stays
  usable. Each message with an artifact keeps an "Open …/Viewing …" chip, so closing never loses it.
- **Escape is layered:** it exits full screen first, and only closes the viewer on a second press.
- **A rendering failure is contained.** `ArtifactErrorBoundary` (keyed by artifact identity) catches a
  preview failure, says so, and points at Code; the conversation is untouched.

### 4.3 Documentation

`README.md` was updated where the implementation changed what the document claims: the phase list and
"What works today" section, a new frontend layout block, the workspace walkthrough under "Running the
application", the API endpoint and error tables (both chat routes, SSE event names, `502`), the testing
section (frontend `typecheck`/`test` commands and what the suites cover), the environment-variable
note (Phase 5 added no variables) and the roadmap status table (Phases 4 and 5 complete). `.env.example`
gained one comment explaining that `LLM_TIMEOUT_SECONDS=120` suits hosted providers while slow local
CPU models may need 1800. `docs/PRD.md`, `docs/architecture.md`, `docs/design.md` and `docs/roadmap.md`
are the source-of-truth planning documents and contain no phase-status claims, so they were left
unchanged. One stale comment in `backend/app/main.py` ("the production chat workflow arrives in a
later phase") was corrected.

---

## 5. Failures, corrections and things that did not go as planned

Recorded because the transcript is meant to show the actual path, not a clean one.

1. **`npm install` crashed twice.** The first attempt exited 0 without installing anything; the second
   failed with an ERESOLVE conflict and then an arborist internal error
   (`Cannot read properties of null (reading 'edgesOut')`). Installing with `--legacy-peer-deps`
   worked, and the missing peer `@testing-library/dom@^10` was added the same way.
2. **Vitest rejected `vitest.config.ts`** ("ESM syntax in a file loaded as CommonJS"). Renamed to
   `vitest.config.mts`.
3. **TypeScript failures:** `.map(toChatMessage)` passed extra array arguments to a one-parameter
   function (wrapped in an arrow); a deliberately exploding test component needed an explicit
   `React.JSX.Element` return type; `mock.calls[0][0]` tuple access needed a typed `stubFetch` helper.
4. **ESLint `react-hooks/set-state-in-effect` (React Compiler rule) — 3 errors.** Rather than disable
   the rule, the "reset state when the selected session changes" logic was rewritten as a render-phase
   adjustment in `useWorkspace` and `AgentActivity`. That refactor is the reason the selection-token
   guard exists, and it removed a real class of stale-write bug.
5. **Two genuine product bugs found by the new tests, both fixed:**
   - `storeSessionId(selectedSessionId)` ran on the initial `null` render and erased the stored
     session preference before bootstrap could read it → guarded with `if (selectedSessionId)`.
   - A turn completing after a session switch wrote its messages into the newly selected session →
     the success path is now wrapped in `if (token === selectionRef.current)`.
6. **Two test-side bugs:** a nested `<li>` from the source list inflated a `getAllByRole("listitem")`
   count (now asserts `conversation.children`), and a mocked `listMessages` returned the same messages
   for every session, which made an isolation assertion pass for the wrong reason.
7. **A meaningless test rewritten.** "Submits on Enter" was vacuous with a controlled no-op draft; it
   now types Shift+Enter (must not send) and then Enter (must send).
8. **Port 8000 was occupied by my own stale uvicorn** (`[Errno 10048]`). Identified the PID, confirmed
   from `/openapi.json` that it predated `/api/chat`, killed it, restarted clean.
9. **A second `next dev` bound :3001 and exited** ("Another next dev server is already running"). The
   existing :3000 server was kept; HMR was already serving the new UI (confirmed by fetching the page).
10. **The backend log file stayed empty** because the background command piped through `tail`, which
    buffers until exit. Diagnosis was done with `curl` probes instead; later runs wrote straight to a
    file.
11. **Cold-start activity silence.** The first turn after a server start showed no activity frames for
    several minutes, while an identical probe on the warm server delivered all five frames in about a
    second. Measured afterwards: importing the agent module costs ~9.0 s per process and constructing
    the agent ~0.5 s (and `get_chat_agent` is `@lru_cache`d, so construction happens once per mode).
    Neither explains minutes, so the remaining cost is attributed to Ollama loading `qwen3:4b` into
    memory and CPU inference — the cause was **not** isolated precisely, and no code change was made
    on the strength of a guess.
12. **The automation browser tab was hidden** (`visibilityState=hidden`) for the live checks. Two
    consequences, both environmental rather than product bugs: `evaluate_script` and screenshots were
    unavailable (verification used accessibility-tree snapshots written to files), and the elapsed-time
    label froze because background-tab timers are throttled — the second turn's activity line showed
    no timer at all. The streaming request itself was unaffected and completed normally.
13. **One unexplained empty session.** During the Cloud→Ollama switch sequence an extra session was
    created at `2026-09-23T06:34:01Z`. The essay turn persisted in the previously selected session,
    the extra session is empty, and nothing in the UI broke. The only UI path that creates a session
    is the New Chat button (and bootstrap when the list is empty); the automation was clicking with
    uids from a snapshot taken before an error banner was removed, so a mis-targeted click is the most
    likely cause. **Cause not proven**, and no fix was made without evidence.
14. **No live HTML/CSS artifact.** `qwen3:4b` still does not complete HTML generation (known since
    Phase 4). The viewer's HTML path was therefore verified by unit tests (sandbox attributes, CSP,
    `srcDoc`, parent-DOM cleanliness) and not by a model-generated artifact. Nothing in this phase
    claims otherwise.

---

## 6. Automated verification

| Check | Command | Result |
|---|---|---|
| Frontend lint | `npm run lint` | exit 0, no warnings |
| Frontend types | `npx tsc --noEmit` | exit 0 |
| Frontend tests | `npm test` (Vitest) | **10 files, 120 tests passed** (10.36 s) |
| Frontend build | `npm run build` | compiled successfully; routes `/` and `/_not-found`, both static |
| Backend suite (Phases 1–5) | `python -m pytest -q` | **389 passed, 1 warning** (147.34 s), re-run after the final source state |

> The 120/389 figures above are what this phase closed with and are kept as the point-in-time record. The
> current repository totals, after the post-Phase-7 fix in
> [`008-post-phase7-session-switch-hotfix.md`](008-post-phase7-session-switch-hotfix.md), are 128 frontend /
> 390 backend (518 total); `README.md` is the authoritative statement of the current counts.

No existing test was weakened, skipped or deleted to make the new work pass. Provider tests still make
no paid calls: the Anthropic and Ollama clients are exercised through mocked transports, and the
frontend tests stub `fetch`.

Frontend test coverage against the directive's checklist (15 items) — every item is covered by at
least one test:

| Required check | Where |
|---|---|
| New Chat creates a session | `useWorkspace.test.tsx` |
| Session list renders | `Sidebar.test.tsx` |
| Switching sessions loads the right messages | `useWorkspace.test.tsx` (incl. dropping a late reply) |
| Messages render correctly | `Message.test.tsx` |
| Composer submits | `ChatPane.test.tsx` (Enter sends, Shift+Enter does not, empty is disabled) |
| Loading state works | `ChatPane.test.tsx`, `useWorkspace.test.tsx` |
| Errors render | `ChatPane.test.tsx`, `errors.test.ts` (exact Ollama sentence asserted) |
| LLM toggle changes the request mode | `LLMModeToggle.test.tsx`, `useWorkspace.test.tsx` (payload `{session_id,message,llm_mode}`) |
| Markdown artifact renders | `ArtifactViewer.test.tsx` |
| HTML artifact renders in a sandboxed iframe | `ArtifactViewer.test.tsx` (sandbox attr, CSP, no parent-DOM injection) |
| Preview \| Code toggle | `ArtifactViewer.test.tsx` |
| Artifact close / reopen | `ArtifactViewer.test.tsx`, `ChatPane.test.tsx` |
| No artifact → no viewer | `ChatPane.test.tsx`, `useWorkspace.test.tsx` |
| Malformed artifact fails gracefully | `ArtifactViewer.test.tsx` (error boundary throws and recovers) |
| Session state not mixed between chats | `useWorkspace.test.tsx` (selection-token regression test) |

---

## 7. Real local verification

Environment: real Supabase `pgvector` (303 episodes, 22,327 chunks), Ollama `qwen3:4b` on CPU,
`LLM_MODE=ollama`, `LLM_TIMEOUT_SECONDS` raised from 300 to 1800 for long local generations (the
`.env.example` comment now explains that hosted providers are fine at 120). No Anthropic key exists on
this machine. Frontend on :3000, backend on 127.0.0.1:8000.

| # | Step | Observed |
|---|---|---|
| 1 | Open the app | Workspace renders: sidebar, chat pane, empty state with three prompt cards, composer, Cloud \| Ollama toggle (Ollama pressed) |
| 2 | Mobile-width drawer | "Show conversations" opens the drawer, "Close navigation" closes it (the automation viewport is fixed at 638×310 CSS px, so the drawer path is what could be exercised; desktop breakpoints are class-based and unit-tested) |
| 3 | New chat | A session is created, selected and shown as "New Chat 11:58 AM"; the empty state appears |
| 4 | Prompt card | Clicking "Write with Ship30for30" set the composer to "Write an essay about building products users love." — **0 messages, nothing sent** (verified by reading the textarea value and message count) |
| 5 | Grounded question (earlier turn, 06:08Z) | "What does Lenny say about finding product-market fit?" → grounded answer naming the four levels (nascent, developing, strong, extreme) and the four Ps, with `Sources (5)` and episode links; the sidebar renamed the session to "What does Lenny say about finding…" |
| 6 | Session isolation | Switching to "Context test" replaced the conversation with that session's own messages ("first question", "hi", the insufficient-evidence reply); nothing from the product-market-fit session remained |
| 7 | Sending state | Optimistic user row, "Working on your request", activity line "Running the selected capability" with elapsed timer (8 s → 47 s → 2 m 04 s), Stop button, Send disabled and relabelled "Sending", both mode buttons disabled |
| 8 | Cloud mode | Selecting Cloud and sending produced the honest configuration error: "The LLM configuration is incomplete. Check the LLM settings in the repository root `.env` file." with Retry/Dismiss, the draft restored, and **nothing persisted**. No cloud success was fabricated — there is no Anthropic key on this machine |
| 9 | Ship30for30 essay (Ollama) | Completed after ≈11 minutes of CPU generation: a 1,347-word article rendered as real Markdown (h1/h2 headings, emphasis, paragraphs) with the capability line "1,347 words • 6 min read"; the session auto-renamed to "Write an essay about building products users…". **No artifact was produced, correctly**: the composition rule only wraps an essay when the request also asks for an artifact (`_should_wrap_in_artifact` requires `artifact_generation` as a secondary intent) |
| 10 | Markdown artifact (Ollama) | "Create a markdown artifact titled 'Beta launch checklist' …" → persisted `{type: "markdown", title: "Beta launch checklist", css: null}`; the assistant reply was the deterministic confirmation ("I generated a markdown artifact titled 'Beta launch checklist'. It is available as structured artifact data.") and the artifact travelled as structured data — no tag parsing anywhere |
| 11 | Artifact Viewer opens | Opened automatically on `artifact_ready`: `complementary "Artifact viewer"`, heading "Beta launch checklist", `MARKDOWN` badge, Preview selected, content rendered as an h1 plus five list items |
| 12 | Preview \| Code | Code tab became `selected`, Preview deselected, and the panel showed the raw source `# Beta Launch Checklist\n\n- Finalize user testing protocols\n…` |
| 13 | Copy | Failed gracefully in this browser context with the honest notice "Copying is blocked in this browser. Select the source under Code instead." (the success path is unit-tested; the clipboard is unavailable to the automated tab) |
| 14 | Full screen | Button flipped to "Exit full screen" with `pressed="true"` |
| 15 | Escape ordering | First Escape exited full screen (viewer still open, `pressed="false"`); second Escape closed the viewer, and the message chip changed from "Viewing Beta launch checklist" (`pressed=true`) to "Open Beta launch checklist" (`pressed=false`) |
| 16 | Reopen | Clicking the chip restored the viewer with Preview selected and the chip back to "Viewing …" |
| 17 | No artifact → no viewer | Every turn without an artifact rendered no `complementary "Artifact viewer"` node at all (0 occurrences), so there is no empty panel |
| 18 | Ollama unavailable | With `OLLAMA_BASE_URL` temporarily pointed at a dead port and the backend restarted, sending "hello" rendered the directive's sentence verbatim: "Cannot connect to Ollama. Make sure Ollama is running and the configured model is available, or switch to Cloud." plus the secondary line, Retry/Dismiss, the draft restored, the open Artifact Viewer and the conversation untouched, and **0 messages persisted**. `.env` was restored to `http://localhost:11434`, the backend restarted, `/api/health` → `{"status":"ok"}` and Ollama listed `qwen3:4b` again |
| 19 | Streaming protocol | A `curl` probe of `POST /api/chat/stream` on a warm server returned all five activity frames within ≈1 s in order: `preparing_request → classifying_intent (heuristic) → selecting_provider (ollama / qwen3:4b) → preparing_pathway (general, confidence 0.6, direct_response) → generating_response`, then `done` |
| 20 | HTML/CSS live generation | **Not achieved** on `qwen3:4b` (unchanged Phase 4 limitation). The sandboxed-iframe path is verified by unit tests only; no live model-generated HTML artifact was produced or claimed |

Expensive Phase 4 smoke tests were not repeated; the two long generations above (one essay, one
artifact) are the only live model calls this phase added beyond short error-path probes.

---

## 8. Security checks before finishing

- The frontend contains no provider credentials, no Supabase client and no connection string: it
  calls only `NEXT_PUBLIC_API_BASE_URL` (FastAPI). A case-insensitive `grep` over `frontend/` for
  `supabase|anthropic|sk-|11434|DATABASE_URL|api[_-]?key` matches only the `Cloud — Anthropic` toggle
  hint, a comment in `HtmlRenderer.tsx` explaining what the CSP blocks, and package names inside
  `package-lock.json` (`…task-list-item`, which contains the literal `sk-`). No secret value appears.
- `.env` is git-ignored and was never committed; `.env.example` carries placeholders only.
- Generated HTML is rendered only inside `sandbox="allow-scripts"` + CSP `default-src 'none'` iframes;
  a unit test asserts the parent DOM receives no generated markup.
- No hidden reasoning, system prompt, tool argument or stack trace is rendered: activity frames come
  from the backend's allow-listed kinds, and error copy comes from `lib/errors.ts` keyed by category.
- `ArtifactErrorBoundary.componentDidCatch` logs a message and component stack to the console only —
  it never renders them.

---

## 9. Known limitations

1. **No token-level streaming.** The provider call is non-streaming, so the UI shows activity stages
   rather than incremental text. Adding it means streaming inside the skills, which is Phase 6+ scope.
2. **First request after a cold server start is slow and quiet** (model load into memory); observed
   minutes of silence before the first frame in one instance, cause not isolated beyond the
   measurements in §5.11.
3. **`qwen3:4b` cannot complete live HTML/CSS artifact generation.** The viewer supports `html_css`
   fully and is tested for it; the local model is the limiting factor.
4. **Cloud mode is unverified end to end** on this machine (no Anthropic key). Only its configuration
   error path was exercised live; the provider itself is covered by mocked-transport tests.
5. **Desktop three-column layout was not screenshotted**: the automation viewport is fixed at
   638×310 CSS px and `window.resizeTo` is blocked, so the `lg` layout is evidenced by classes and
   unit tests rather than a capture. The mobile drawer path was exercised live.
6. **The elapsed timer freezes in a hidden tab** (browser timer throttling). Harmless, but it means a
   backgrounded tab shows a stale or missing timer.
7. **Copy depends on clipboard availability**; when blocked, the viewer says so and points at Code.

---

## 10. Phase boundary

Phase 5 stopped at its verification gate. **Phase 6 (integration and verification) and Phase 7
(documentation and submission) were not implemented**, and no work was done towards them: no
end-to-end test harness, no deployment or hosting configuration, no CI pipeline, no submission
packaging, and no further backend architecture. The only backend changes are the minimal production
chat workflow described in §4.1, plus one stale comment corrected in `app/main.py`.
