# 008 — Post-Phase-7 focused bug fix: in-flight chat request preserved across session switching

**Date:** 2026-09-23
**Classification:** **Hotfix after the Phase 7 submission gate. This is NOT a development phase.** It is
one defect, fixed narrowly, on the already-submitted Phase 5 workspace. No Phase 8 exists, `docs/roadmap.md`
is unchanged, and nothing here reopens Phase 6 or Phase 7.

**Scope (from the bug-fix directive):** stop a running request in Session A, switch to Session B while it
is still in flight, return to A before it completes — and keep A's live state. Explicitly *not* a completed
request persistence issue; completed turns already persisted correctly.

**Explicit exclusions honoured:** no redesign, no architecture change, no API contract change, no database
schema change, no RAG or threshold change, no prompt change, no artifact-behaviour change, no visual
redesign, no new capability. `git` state is untouched: `master` still has zero commits, no remote, nothing
pushed. No test was deleted, weakened or skipped to make the fix pass.

> **Redaction note.** The repository-root `.env` was not opened, printed or copied. This transcript
> contains no credential, connection string, hidden model reasoning or private prompt — only the
> user-visible activity stage strings the app already renders.

---

## 1. Defect as reproduced

1. Create Session A, send `"talk about pricing"` — the optimistic user row, the activity line and the
   Stop button appear, the composer locks into the working state.
2. Click Session B while that request is still running.
3. Click back into A before it finishes.

Before this fix, step 2 destroyed the turn: A's submitted message, its activity stage, its elapsed/processing
time, the Stop control and the working composer state were all gone, and the request itself was cancelled.

## 2. Root cause

In `frontend/lib/useWorkspace.ts` the in-flight state was **global**, and the selection drove more than
display:

- One `abortRef`, one `activity` array and one `status` value served the whole workspace, so they described
  "whatever the currently selected session is doing" rather than any particular session.
- The effect that reacts to `selectedSessionId` called `superseded?.abort()`. **Selecting another session
  actively cancelled the running request** and cleared the optimistic message.
- The `streamChat` event callback and the completion handler were gated on a selection token
  (`selectionRef`). Because that token was only ever valid for the session on screen, events and the final
  response belonging to a session the user had navigated away from were **discarded instead of written to
  their own session**.
- `AgentActivity` started its elapsed timer on mount, so even a restored turn would have restarted at `0s`
  instead of showing real elapsed time.

The underlying design error: the selected session decided *whether the background request may continue*,
when it should only ever decide *what is displayed*.

## 3. Implementation

Request state became a per-session record keyed by session id, with a `useRef` mirror so the SSE callbacks
can read and write it without a stale closure:

```ts
type SessionTurn = {
  phase: "running" | "settled" | "failed";
  optimistic: ChatMessage;   // submitted message, shown until the persisted row replaces it
  rows: ChatMessage[];       // the persisted pair once the turn is over; empty while running
  activity: ActivityEvent[];
  startedAt: number;
  controller: AbortController;
  error: WorkspaceError | null;
};
```

The invariants this restores:

| Invariant | How |
|---|---|
| Switching sessions never aborts a request | The abort-on-selection was deleted; only `cancel()` aborts, and only the on-screen session's controller |
| A's events keep updating A while B is displayed | `send()` captures `const sessionId = selectedSessionId` once and routes every `activity` event to `mutateTurn(sessionId, …)` with no selection guard |
| Results land in the originating session | The captured id — never a re-read of the selection — keys the settled rows, the failure and the cleanup |
| Exactly one live request per session | `if (turnsRef.current[sessionId]?.phase === "running") return` |
| Display is derived, not duplicated | `turns[selectedSessionId]` feeds `status`, `activity`, `activityStartedAt`, `error` and `visibleMessages` through `useMemo` |
| No duplicate or lost message after a background finish | A settled turn keeps its rows until the loaded history provably contains them (`withoutDuplicates` returns empty), then the entry is dropped |
| Stop stays per-session | `cancel()` looks up the running turn of the session on screen only |

Removed: `abortRef`, `lastRequestRef`, the global `setActivity`, the `setStatus("sending")` call, the abort
inside the selection effect, and the abort in `createSession`.

One supporting prop was needed for honest elapsed time: `AgentActivity` accepts an optional `startedAt` and
seeds its timer from it, threaded through `ChatPane` (`activityStartedAt`) from `app/page.tsx`. No styling,
markup or copy changed. The artifact view remains gated on the session actually on screen, so a background
turn cannot hijack the viewer.

**No backend change was required.** `run_chat_turn` already persists both rows of a turn under the
originating `session_id` and commits before the `done` event; the defect was entirely client-side.

## 4. Tests added

`frontend/tests/lib/useWorkspace.test.tsx` — new block
`describe("in-flight request across session switches")`, plus a `holdStreams()` helper that parks each
session's stream on a resolver and records its `AbortSignal`:

| Test | Asserts |
|---|---|
| keeps running when the reader switches to another session | `signals.s1.aborted === false` after selecting B |
| restores the in-flight turn when the reader returns | pending user row, the real activity stage, an identical `activityStartedAt`, `streamChat` still called once |
| keeps collecting progress for the session that is not on screen | B's activity list grows while A is displayed |
| finishes a background turn in its own session only | the reply appears in A, never in B |
| reports a failed background turn to its own session only | the error surfaces in A only |
| stops only the session on screen | with two concurrent turns, `signals.s2.aborted === true` and `signals.s1.aborted === false` |
| runs one request per session and replaces the finished turn | no parallel request for the same session; the settled turn is superseded cleanly |

`frontend/tests/components/ChatPane.test.tsx` — "times a resumed turn from its real start, not from the
redisplay" (`startedAt` 65 s ago renders `1m 05s`).

Existing coverage was left intact, including Phase 6's "drops a late reply that belongs to a session the
user left", which still passes: that test is about a session the user *left and which no longer has a live
turn*, and the new code only discards a load that a newer load superseded.

## 5. Verification — automated

| Check | Result |
|---|---|
| `npx vitest run` (frontend) | **128 passed** in 10 files, 15.3 s (was 120; +8 for this fix) |
| `python -m pytest -q` (backend) | **390 passed**, 1 pre-existing anyio deprecation warning, 157 s |
| Total automated tests | **518** (390 + 128) |
| `npm run lint` | clean, no warnings |
| `npx tsc --noEmit` | clean |
| `npm run build` | compiled in 21 s, TypeScript passed, 4 static pages, routes `/` and `/_not-found` |
| Health after restart | `GET /api/health` → `{"status":"ok"}`; `http://localhost:3000/` → HTTP 200 |

## 6. Verification — real browser (Ollama `qwen3:4b`, live backend, no mocks)

Measured from the DOM with scripted queries; the numbers below are what the page actually rendered.

**CASE 1 — switch during processing, return before completion.** Sent
`"What does Lenny say about pricing experiments?"` in a fresh Session A. While it ran, selected Session B
and measured B as fully isolated: `{bubbles: [], status: null, stop: false, sendText: "Send", taDisabled: false,
error: null}`. Clicked back into A before completion and measured
`{bubbles: ["user: …What does Lenny say about pricing experiments?"], status: "Searching Lenny's transcripts1m 37s",
stop: true, sendText: "Sending", sub: "Working on your request", error: null}` — the actual stage, and the
timer still counting from the real request start, not a generic "Processing…".

A's turn then ended in `502 llm_response`: `qwen3:4b` exhausted its token budget on private reasoning before
emitting answer text — the documented model limitation from Phases 4–7, not a regression. The UI handled it
correctly and locally to A: the actionable alert appeared, the draft was restored, the pending row was
removed, and no in-flight state leaked.

**CASE 2 — switch after completion.** Created a new session, sent the cheap prompt `"hi"`, and immediately
selected `"New Chat 06:49 PM"`. While that session was displayed, the background turn finished: the sidebar
quietly renamed the originating session to `"hi 07:12 PM"` and the displayed session stayed empty — no
cross-session leakage, and the earlier failed turn's alert did not follow the user into it. Opening
`"hi 07:12 PM"` showed exactly one pair with no duplicate and no residue:
`["user: hi", "assistant: Hi there! How can I help you today?"]`, `{status: null, pending: false, alerts: [],
draft: ""}`.

**Normal single-session use unchanged** — that `"hi"` turn is the evidence: one send, one reply, composer
locks and unlocks as before. After the production build and a dev-server restart, a clean page reload
restored the selected session and its messages from the database with no phantom activity line.

## 7. Remaining limitations (deliberately not fixed here)

- The sidebar shows no "this session is working" badge, so a background request is invisible until you open
  its session. Adding one is new UI scope.
- The composer draft is still one global string, so a mid-edit draft travels with the selection. Per-session
  drafts would be a separate change.
- A failed turn's alert now persists in its own session until dismissed or superseded by a new send —
  intentional, since it is part of that session's real state.
- There is still no automated browser E2E suite (recorded in `docs/submission-checklist.md`); CASE 1 and
  CASE 2 above were verified manually against the live app.

## 8. Submission cleanup recorded with this entry

The only documentation deltas made alongside this fix: the frontend test count is stated as 128 (total 518)
in `README.md`, `docs/demo-script.md` and `docs/submission-checklist.md`; this transcript is indexed in the
README transcript table and in `docs/submission-checklist.md`. Transcripts 001–007 keep the counts that were
true when each phase closed, as point-in-time records; this file is the authoritative statement of the
current totals. No architecture, roadmap scope, RAG, prompt, schema or UI design document was touched, and
no application behaviour changed.
