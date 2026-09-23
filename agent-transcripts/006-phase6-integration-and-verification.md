# 006 — Phase 6: Integration & Verification

**Date:** 2026-09-23
**Scope (from the Phase 6 directive):** verify that Phases 1–5 work together as one application —
browser → Next.js → FastAPI → application agent → router → Phase 4 skills/RAG → Supabase/Ollama →
structured response → frontend rendering — and fix only genuine integration defects found while doing
it. Integration and regression testing, session isolation and persistence, streaming/activity behaviour,
artifact integration, error recovery, security sweep, lightweight latency measurement, and one concise
real-browser pass.

**Explicit exclusions honoured:** Phase 7 was **not** implemented — no deployment, hosting, submission
packaging, GitHub/remote work, README rewrites for submission, demo video or CI/CD setup. No
architecture was reopened: no new database, RAG, agent, router, registry or provider design, no new
frontend framework or state-management library, no token-level streaming, and no redesign of working
code. Only two files changed, both from a reproduced product bug (§9).

> **Redaction note.** The repository-root `.env` holds real credentials and was never read in full,
> printed or committed in this phase; `git check-ignore -v .env` still resolves to `.gitignore:4` and
> `git ls-files` shows no `.env` entry. The only non-secret settings quoted here are `LLM_MODE`,
> `OLLAMA_BASE_URL` (port only), `OLLAMA_MODEL` and `LLM_TIMEOUT_SECONDS`. No API key, password,
> connection string, service-role value, chain of thought, hidden reasoning, private prompt or tool
> argument appears in this transcript, in the source, in the tests or in captured UI text. Browser
> evidence below is accessibility-tree text plus rendered UI copy. Test-fixture keys such as
> `sk-ant-test-not-a-real-key` are synthetic values that already existed in Phase 3/4 tests and assert
> redaction; none were added here.

---

## 1. Starting point

Phases 1–5 were complete and individually verified: FastAPI + SQLAlchemy 2 + PostgreSQL/`pgvector`
with **303 episodes / 22,327 chunks** live (re-counted at the end of this phase), provider layer and
LLM factory, deterministic router, four capabilities (`transcript_search`, `transcript_qa`,
`ship30for30`, `artifact_generator`), one production workflow (`run_chat_turn`) shared by `POST
/api/chat` and `POST /api/chat/stream`, and the Phase 5 Next.js workspace with sidebar, composer,
activity timeline, LLM mode toggle and Artifact Viewer. Local runtime: Ollama 0.34.2, `qwen3:4b`,
CPU-only; backend on `127.0.0.1:8000`; `next dev` on `:3000`.

Nothing was restarted or rebuilt from Phases 1–5.

## 2. Verification plan

1. Route every §2 scenario through the real browser and, where a scenario was expensive (long local
   generation), also through the real HTTP API once, and only once.
2. Prove the general path never retrieves, by reading the code path, by observing live SSE frames, and
   by a new automated regression test.
3. Prove RAG against real `pgvector` in both directions: above the evidence floor (sources returned) and
   below it (exact insufficient-evidence reply, zero model calls).
4. Prove isolation/persistence/race behaviour server-side (a two-session probe with a slow turn in
   session A and switching to B mid-flight) and in the UI (refresh, switch, New chat).
5. Force each failure class (§9) and read the actual error category, HTTP status, user-facing copy,
   traceback-leak flag and persisted-row count rather than judging by appearance.
6. Verify the HTML/CSS path with valid and malformed fixtures rather than pushing `qwen3:4b` to
   generate HTML live again (a Phase 4 known limitation).
7. Measure a small number of latencies, then check for application-side waste (needless retrieval, extra
   LLM calls, per-turn agent rebuild).
8. Run the security sweep, then full regression (`pytest`, `vitest`, `eslint`, `tsc --noEmit`,
   `next build`).
9. One 19-step real-browser pass (§11).

Expensive local generations were kept to first-time-required scenarios only.

## 3. End-to-end integration scenarios (real Ollama + real Supabase)

| § | Request | Route actually taken | Result |
|---|---|---|---|
| A | `hi` | `general` → `direct_response`, skills `[]` | Conversational answer, **0 retrieval events, 0 sources, 1 LLM call**, both messages persisted exactly once |
| B | `What does the podcast say about product-market fit?` | `rag_qa` → `transcript_qa` | 5 transcript sources (top similarities 0.826 / 0.815 / 0.812 / 0.808), attributed answer naming Paul Adams and Todd Jackson |
| B′ | `What should a seed-stage founder measure first?` | `rag_qa` | Grounded single-paragraph answer, persisted |
| B″ | `What did Todd Jackson say about product-market fit?` | `rag_qa` | Grounded multi-paragraph answer with quotes, `Sources (5)` disclosure rendered |
| C | `Write a Ship30for30 article about product retention.` | `ship30for30` | 1,259 words against the 1,250 target, 7 headings, 3 bullets, 8 bold phrases, title + takeaway present, 6-minute reading time metadata |
| D | `Create a Markdown artifact titled 'Beta launch checklist'.` | `artifact_generation` → `artifact_generator` | `artifact_ready` then `done`; markdown artifact persisted on the message and rendered in the viewer |
| E | HTML/CSS artifact (valid fixture incl. `<script>`, remote `<img>`, unclosed tags; and a malformed alias fixture) | `artifact_generation` | Stored and returned as structured artifact data; rendered only inside the sandboxed viewer (§7) |

Cloud-mode scenario (§2/§7 of the directive) is in §8. `qwen3:4b` was never asked to produce live HTML.

## 4. Real RAG and the evidence floor

Retrieval ran against live Supabase `pgvector` over the ingested corpus; nothing was mocked in these
checks. The Phase 4 calibrated design was left alone and validated at both ends of the floor:

- **Above the floor:** the PMF question returned 5 chunks with similarities from 0.826 down to 0.808,
  all above the 0.71 evidence threshold; `metrics.evidence_count` matched the source list, and the
  answer quoted only provided evidence.
- **Below the floor:** a deliberately unanswerable question (a fabricated 2031 "zebra-farming OKR"
  episode with an invented guest) returned `intent=rag_qa`, `skills=["transcript_qa"]`,
  `metrics={"insufficient_evidence": true, "evidence_count": 0}` and the exact calibrated reply
  (“The available Lenny transcripts do not provide enough evidence to answer this reliably…”) in 11.2 s
  with **no model call** — the correct behaviour for an invented-entity query, and no fabricated quote.
- No hidden reasoning, retrieval trace, tool arguments or prompt text reached the UI in any frame.

## 5. Session isolation, persistence and race safety

Server-side probe (two sessions, one slow turn) plus UI checks:

- **Isolation:** session A and B histories never contained each other's rows; switching A → B → A in
  the UI showed each conversation intact and the empty-state only for a genuinely new chat.
- **Race safety:** while a 600 s-class turn was in flight in A, the UI was switched to B. The late reply
  was dropped by the Phase 5 selection-token guard (61 polls, **0 rows** ever appeared in B), and A
  received its own turn when it completed. The pre-existing Phase 5 logic was reused unchanged.
- **Exactly-once persistence:** every successful turn produced one user row and one assistant row
  (`final-rows` sample: A = user/assistant/user/assistant; B = `[]`); no duplicate assistant rows after
  refresh, and the markdown artifact from a completed turn was restored a single time.
- **Failed turns are not persisted:** all four failure classes (§9) left 0 rows; a subsequent successful
  retry in the same session stored both rows normally (`rows_after_retry: 2`, artifact present).
- **Timestamps:** the user row inherits the request-start time and the assistant row its own insert time
  because repositories `db.commit()` per call and Postgres `now()` is transaction-start time. Ordering
  and exactly-once semantics are correct; **no change made**.
- **New chat** creates a real new session (sidebar entry, empty conversation, first turn auto-titles it);
  **refresh** restores sessions, selection and persisted artifacts.

## 6. Streaming and activity protocol

Observed on real turns in every scenario: `preparing_request` → `classifying_intent` →
`selecting_provider` → `preparing_pathway` → (`retrieving_evidence` only on capability paths) →
`generating_response`/`executing_capability` → `completed`, then `artifact_ready` when an artifact
exists, then exactly one `done`. On failure the stream ends with `activity stage=failed` and one `error`
event instead of `done`. Provider/model metadata (`ollama`, `qwen3:4b`) appears only as safe
activity detail. No prompt text, no chain of thought, no tool arguments, no raw JSON leaked to the
client. Token-level streaming was not added — responses arrive per turn, which matches the Phase 3/4
provider design and showed no concrete defect, so reopening it was explicitly out of scope.

## 7. Artifact integration

- **Markdown, live end-to-end:** scenario D through the browser — chip in the transcript, viewer opens
  with title `Beta launch checklist`, `MARKDOWN` badge, Preview renders GFM (H1 + task-list checkboxes,
  correctly disabled in read-only preview), Code shows the raw source in a `<pre>` with real newlines
  (verified in DOM: 6 lines, no literal `\n`), Copy source / Full screen / Close present; closing
  removes the panel and flips the chip back to “Open …”, reopening resets to Preview. The same turn
  survived a refresh as one message with one artifact.
- **HTML/CSS, sandboxed:** the valid hostile fixture (script calling `document.write`, remote
  `https://evil.example/…` image and link, unclosed anchor) round-tripped through the real persistence
  path and was then opened in the viewer. Live iframe facts: `sandbox="allow-scripts"` only, content set
  via `srcDoc`, injected CSP
  `default-src 'none'; img-src data:; font-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'`,
  `referrerPolicy="no-referrer"`, and `iframe.contentDocument === null` from the parent (opaque origin).
  Parent-document checks after rendering: no `ran-in-sandbox` text in `document.body.textContent`, zero
  `img[src*="evil.example"]` in the parent, chat composer still editable, Send still enabled, and the
  browser console stayed free of errors. A malformed/alias artifact stayed contained and did not break
  chat. **The viewer cannot reach the parent DOM, the API or the network.**
- **Cosmetic, left as is:** the fixed summary line reads “I generated a html artifact…”. It is an
  internal confirmation sentence inside an already-designed template; rewording it would have churned
  working Phase 4 output for no functional gain, so it is recorded as a known nit instead.

## 8. Cloud / Ollama modes through the frontend

- **Ollama mode:** the default used for every live check above.
- **Cloud mode:** **no Anthropic API key exists on this machine, so no cloud success is claimed.** What
  was verified is the honest failure path, in the browser: toggle to Cloud, send a message, receive
  `503 configuration` — “The LLM configuration is incomplete. Check the LLM settings in the repository
  root `.env` file.” — with the draft preserved in the composer, **0 rows persisted**, and the app fully
  usable again after switching back to Ollama (the preserved draft then completed normally).
- Kept distinct for the reader: (i) the cloud client is implemented and wired through the same agent and
  workflow as Ollama; (ii) its behaviour is covered by automated tests with a stubbed provider — those
  are mocked tests, not live calls; (iii) the configuration-error path was verified live; (iv) live
  cloud generation is **not verified in this phase for lack of credentials**.

## 9. Integration failures, root causes and fixes

Only real, reproduced product bugs were changed.

### 9.1 Defect 1 — a greeting could be routed to transcript Q&A and answer “insufficient evidence”

- **Reproduced:** a manual check sent `hi` and got a retrieval-flavoured non-answer instead of a normal
  conversational reply. Confirmed the direct-response path is reachable but under-specified.
- **Classification:** real product bug (prompt-level), not a router architecture bug.
- **Root cause:** the general/direct-response system prompt (`BASE_SYSTEM_PROMPT`, consumed only by
  `ApplicationAgent` at the direct-response branch) told the model what to do *with* transcript evidence
  but never stated that this path retrieves nothing. A small local model therefore volunteered
  “not enough transcript evidence” on ordinary small talk. Retrieval itself was already structurally
  impossible on this path — evidence gathering exists only inside capability execution — so the defect
  was purely in the instruction text.
- **Fix (small, in place):** `backend/app/agent/prompts.py` now states that no transcript evidence is
  retrieved for this kind of request, to answer general product/growth questions and greetings from the
  model's own knowledge, never to mention retrieval or missing transcripts, and that an ordinary question
  is not a “cannot do” case. The existing anti-fabrication, no-instruction-leak and no-CoT rules were
  kept.
- **Regression test added:** `test_a_greeting_stays_on_the_general_path_with_no_retrieval` in
  `backend/tests/test_chat_api.py` asserts `intent=general`, empty `skills`/`sources`, the
  `preparing_pathway` detail's `execution_path == "direct_response"`, that `retrieving_evidence` never
  appears, that the retrieval stub was never called, that exactly **one** model call happened, and that
  both messages persisted once.
- **Re-verified:** same-phase live browser `hi` → “Hello! How can I help you today?” with 0 retrieval
  events; automated path green.

### 9.2 Investigated and judged **not** a defect (no code change)

- **Timestamps** within one turn (§5) — correct given per-call commits and `now()` semantics.
- **`502 llm_response` on a long compound PMF question** (838.53 s, “used the whole token budget without
  returning an answer”): a `qwen3:4b` CPU limitation already measured in Phase 4 (`think=false` does not
  fix it; planning leaks into content). Error copy is honest and actionable, nothing persisted, and a
  short re-ask grounded correctly. Known model limitation; the app already surfaces it well.
- **Per-turn efficiency:** the general path made exactly 1 LLM call with 0 retrievals, and
  `@lru_cache get_chat_agent(llm_mode)` keeps one agent per mode, so no per-request rebuild. Nothing
  justified the “small performance fix” clause.
- **No existing test was weakened, deleted, skipped or rewritten.** No frontend source changed.

## 10. Error recovery matrix (actual categories, not appearance)

| Class | How forced | Status | Category / copy shown | Rows persisted |
|---|---|---|---|---|
| A — Ollama unavailable | Second backend instance with `OLLAMA_BASE_URL` pointed at a dead port (`.env` untouched) | `503` | `llm_unavailable`; “Local model execution is unavailable. Make sure Ollama is running and the configured model is installed, then try again.” — stream ends `activity stage=failed (detail.status=llm_unavailable)` + `error`, **no `done`** | `[]` |
| B — cloud config missing | Toggle to Cloud with no API key, through the browser | `503` | `configuration`; “The LLM configuration is incomplete. Check the LLM settings in the repository root `.env` file.” | 0, draft kept |
| C — malformed artifact output | Non-JSON and title-less model output at the artifact skill | `4xx/5xx` by class | `ArtifactGenerationError`; “The model did not return a valid artifact structure…” / “The generated artifact had no title. Try rephrasing the request.” | 0 both times; retry stored 2 rows incl. artifact |
| D — database unavailable | Broken session factory on the real app | `503` | “The database is currently unavailable. Please check the configured `DATABASE_URL` and try again.”, `leaks_traceback: false` | 0 |

Health endpoint re-confirmed after each experiment (`/api/health` → `{"status":"ok"}` on the normal
instance, which stayed running throughout).

## 11. Real-browser pass (single 19-step run)

On `http://localhost:3000/` in the in-app browser, in order: open app → restore last session → New chat
(empty state) → type `hi` → Enter-to-send → conversational reply with no sources and no retrieval event
→ session auto-titled → switch to another session (history, no mixing) → switch back → grounded PMF
question → `Sources (5)` disclosure rendered → `What should a seed-stage founder measure first?` →
markdown artifact request → chip → viewer → Preview → Code → close → reopen (resets to Preview) →
Cloud toggle → honest config error with draft preserved and 0 rows → back to Ollama → draft answered →
activity timeline observed in order with Stop/Sending states and disabled controls mid-turn → refresh →
history, both artifact chips and the fixture artifact restored exactly once → HTML/CSS fixture opened in
the sandboxed viewer → composer and Send still usable → console clean.

**Browser-automation limitations found (not product bugs):** at the 638×310 in-app viewport, pixel
clicks on off-canvas drawer rows and on viewer header controls behind the sticky composer failed with
“Element could not be scrolled into the viewport” / “Element is covered by another element at its
clickable point”. Those interactions were exercised by dispatching real clicks to the same React
handlers through the accessibility tree/DOM and by reading rendered DOM state; keyboard Enter-to-send,
the mode toggle, New chat and session switching were all clicked normally and worked. Sources
expansion and drawer rows are additionally covered by Phase 5 component tests.

## 12. Performance observations (lightweight, CPU inference)

| Check | Elapsed | Notes |
|---|---|---|
| `hi`, first greeting of the phase | 121.02 s | 5 activity frames at ~1.3 s, then model time; 0 retrievals, 1 LLM call |
| Warm general inside a session with history | 379.83 s | Longer than the cold greeting — context tokens, not extra calls: still 1 LLM call, 0 retrieval events |
| Warm grounded RAG (short question) | 761.53 s | Retrieval frames at ~12 s; the rest is `qwen3:4b` generation |
| Evidence-floor refusal | 11.20 s | No model call at all |
| Ship30for30 article | 985.16 s | 1,259 words, one turn |
| Markdown artifact | 696.63 s | `artifact_ready` + `done` |

Everything slow here is local CPU token generation; the application layer responded in ~1–12 s and made
the minimum number of calls in every measured path. No redesign was warranted or attempted.

## 13. Security sweep findings

- `.env` git-ignored, untracked, never printed; `.env.example` carries placeholders only (0
  key/JWT/`user:pass@host` shaped strings).
- Frontend touches exactly one origin: `lib/api.ts` is the only `fetch` site and points at
  `NEXT_PUBLIC_API_BASE_URL ?? http://localhost:8000`. No Supabase, Anthropic or Ollama calls, no keys
  in frontend code or bundle; the only matches for those words are a security comment in
  `HtmlRenderer.tsx:15` and the “Cloud — Anthropic” toggle label.
- Generated HTML stays in the CSP'd opaque-origin iframe (§7); user text and model text are rendered as
  Markdown/React nodes, never as raw HTML.
- UI copy for every error class is user-safe; `leaks_traceback: false` on the database failure; the
  provider layer's redaction patterns run before logging. Across 355 backend log lines produced during
  this phase plus the failure-injection instance log: **0** matches for provider-key prefixes,
  credential-bearing database URLs or bearer tokens.
- No chain of thought, tool argument or prompt text appeared in any SSE frame, message row, screenshot
  text or log.
- Nothing in this transcript, the tests or the source contains a real credential.

## 14. Regression results

| Check | Result |
|---|---|
| Backend `pytest` (Phases 1–6, `APP_ENV=development`) | **390 passed**, 1 pre-existing anyio deprecation warning, 148 s — no skips, no failures, run twice for the count |
| Frontend `vitest run` | **120 passed** across 10 files (incl. 27 `useWorkspace` race/isolation tests, 13 `artifacts` CSP/sandbox tests, 7 `sse` tests), 11.4 s |
| `eslint` | clean, 0 problems |
| `tsc --noEmit` | clean |
| `next build` | success — Next.js 16.3.5 (Turbopack), compiled in 1.53 s, TypeScript 4.5 s, routes `/` and `/_not-found` prerendered static |

> Superseded on 2026-09-23 by the post-Phase-7 session-switching fix
> ([`008-post-phase7-session-switch-hotfix.md`](008-post-phase7-session-switch-hotfix.md)), which added 8
> frontend tests: the current totals are 128 frontend / 390 backend (518 in total). The rows above stay as
> the point-in-time Phase 6 record, and none of those tests were altered.

Build was run after stopping the dev server (to avoid writing `.next` under it); the dev server was
restarted and re-confirmed serving `200` afterwards. Backend instance on `:8000` was never taken down;
the temporary `:8010` failure-injection instance was stopped and confirmed gone.

## 15. Known limitations carried into Phase 7

1. **`qwen3:4b` on CPU is slow** (~2–4 tok/s): grounded answers, essays and artifacts take minutes, and
   long compound questions can exhaust the answer-token budget (`502 llm_response`, honest copy, nothing
   persisted). Phase 4 measured that `think=false` does not cure it.
2. **Cloud mode is live-unverified** — no Anthropic credential on this machine. Only its config-error
   path and mocked-provider tests are proven here.
3. **No token-level streaming** by design; responses land per turn.
4. **Sources are not persisted** with history: they render live for the current turn and disappear after
   refresh (Phase 5 decision, unchanged; answers themselves persist).
5. **Cosmetic:** “I generated a html artifact…” grammar in the artifact confirmation line.
6. **In-app browser automation** at 638×310 cannot pixel-click some off-canvas/overlaid elements; use
   DOM-dispatched clicks or a larger viewport for future UI passes.
7. Dev-only verification endpoint and the seeded corpus remain as in earlier phases; deployment,
   analytics and submission packaging are Phase 7 work and were not started.

## 16. Phase boundary

Phase 6 closed at its verification gate. **Phase 7 was not implemented**: nothing was deployed or
published, no hosting/submission tooling, no repository/GitHub operations, no demo assets, no CI/CD, and
no README-for-submission work. No Phase 1–5 architecture was redesigned, no test was weakened, and no
new capability was added — the only code changes are the §9.1 prompt fix and its regression test.
