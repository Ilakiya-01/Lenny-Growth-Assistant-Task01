# Demo script — The Lenny Growth Assistant

**Length:** 2–3 minutes of talking, with the slow generations pre-run (see "Before you record").
**Rule:** show only flows that were actually verified. Do not claim live cloud generation and do not
claim a live `qwen3:4b` HTML artifact — neither happened on the demo machine.

---

## Before you record

1. Start the stack and leave it running: backend on `:8000`, `npm run dev` on `:3000`,
   `ollama serve` with `OLLAMA_MODEL` pulled (`/api/health` should return `{"status":"ok"}`).
2. Local CPU generation takes minutes, not seconds, so **pre-run these four turns** into separate
   sessions and keep them in the sidebar. Each one is a verified Phase 6 scenario:
   - session **`Grounded PMF`** → `What did Todd Jackson say about product-market fit?`
   - session **`Ship30 retention`** → `Write a Ship30for30 article about product retention.`
   - session **`Beta checklist`** → `Create a Markdown artifact titled 'Beta launch checklist'.`
   - session **`Not enough evidence`** → a question about an episode that does not exist, e.g.
     `In the 2031 zebra-farming OKR episode with Pelham Wetherby-Smythe, what exact words did they use?`
3. Do two turns live in front of the camera: the greeting and one short grounded question. Everything
   else is opened from history.

---

## The sequence

| # | Action | What the audience sees | What to say |
|---|---|---|---|
| 1 | Open `http://localhost:3000` | Sidebar with sessions, chat pane, empty-state prompt cards | "Next.js front end, FastAPI behind it, Postgres with `pgvector` for the knowledge base. The browser only ever talks to my own API — no keys, no database URL in the client." |
| 2 | Click **New chat** | A genuinely empty conversation | "Sessions are server-side rows; the last selection is remembered locally." |
| 3 | Type `hi`, press Enter | Activity line: preparing → classifying → selecting provider → generating; a normal conversational reply, **no sources** | "Routing is deterministic and offline: this is the `general` pathway, so retrieval is structurally skipped and exactly one model call happens. That was a real Phase 6 bug I found and fixed — a greeting used to answer as if it had gone looking for transcripts." |
| 4 | Open **`Grounded PMF`** | Answer quoting Todd Jackson, then **`Sources (5)`** — expand it | "Every claim came from retrieved transcript chunks, ranked by cosine similarity over 303 episodes / 22,327 chunks. Sources carry the episode, guest and timestamps. If the evidence falls below the calibrated floor, the app refuses instead of guessing." |
| 5 | Open **`Not enough evidence`** | "The available Lenny transcripts do not provide enough evidence…" with no sources | "This is the same request shape as before, but nothing crossed the evidence threshold, so the model was never called. No invented quotes." |
| 6 | Open **`Ship30 retention`** | A full article: title, hook, headings, bold, bullets, takeaway | "The writing skill targets ~1,250 words and the metrics are measured, not self-reported — last run: 1,259 words, 7 headings, 3 bullets, 8 bold phrases." |
| 7 | Open **`Beta checklist`**, click the artifact chip | Artifact Viewer opens on the right with title + `MARKDOWN` badge | "Artifacts are returned as structured data on the message, not as text the client has to parse, and they survive a refresh." |
| 8 | Toggle **Preview → Code** | Rendered GFM checklist, then the raw `# Beta Launch Checklist …` source; then Copy / Full screen / Close / reopen | "Same viewer for markdown and for HTML/CSS. HTML is the security-sensitive one: it goes into an `srcDoc` iframe with `sandbox="allow-scripts"` only — opaque origin, `default-src 'none'` CSP — so generated markup cannot touch the page, the API or the network. I verified that with a hostile artifact containing a script and a remote tracking image." |
| 9 | Point at the **Cloud \| Ollama** toggle, leave Ollama selected | Mode chips; the choice is sent with the request | "Two providers behind one interface, chosen per request, never with silent fallback. This is `ollama` running locally." |
| 10 | Switch to **Cloud** with no key configured, send a message | Red error notice: "The LLM configuration is incomplete…", the draft still in the composer, nothing added to history | "This is honest failure handling: `503 configuration`, the text you type is preserved, the failed turn is not persisted, and switching back to Ollama leaves the app usable." **Switch back to Ollama before you stop recording.** |

Close with one sentence: "Phases 1–7 each have a transcript, including the failures — 390 backend and
128 frontend tests (518 automated tests in total), lint, typecheck and a production build are green."

---

## Limitation wording to use (and not to use)

- Say: "Local `qwen3:4b` on CPU runs at two to four tokens a second, so an essay takes about
  sixteen minutes — these sessions were pre-generated."
  Do **not** say: "the app is slow" or "the backend is the bottleneck"; measured app-layer overhead is
  1–12 seconds.
- Say: "Cloud mode is implemented and unit-tested through a mocked transport; I had no Anthropic key on
  this machine, so only its configuration-error path is live-verified."
  Do **not** say: "cloud works" or show a fabricated cloud reply.
- Say: "HTML/CSS artifacts render and are sandbox-tested with fixtures. The current local model cannot
  finish generating them, and that is reported as an honest `502 llm_response` rather than hidden."
  Do **not** say: "the model generated this page".
- Say: "Streaming is per turn with activity events; token-level streaming was left out deliberately
  because it would have reopened the provider and skill design."
- Say: "The source list belongs to the live turn and is not stored with the message."

## If something misbehaves during the take

- "Checking backend…" and nothing happens → delete `frontend/.next` and restart `npm run dev`
  (a mixed dev/production build cache).
- Ollama unavailable → start `ollama serve`, or show the `503 llm_unavailable` notice: it is itself a
  verified error path with correct copy and no persistence.
- A live short question takes too long → keep talking over the activity timer, or cut to the
  pre-generated session; the timer is the intended progress signal.
