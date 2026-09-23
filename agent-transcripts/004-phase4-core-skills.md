# 004 — Phase 4: Core Skills & Tools

**Date:** 2026-09-22 (verification continued into 2026-09-23)
**Scope (from `docs/roadmap.md`):** transcript search/RAG tool over the Phase 2 knowledge base,
transcript-grounded Q&A, the Ship30for30 writing skill, artifact generation (markdown and HTML/CSS),
executable tool/skill orchestration through the existing agent/router/registry, tests, verification.

**Explicit exclusions honoured:** no second vector-search system (the Phase 2 `match_transcript_chunks`
path is reused unchanged), no second agent/router/factory/registry/orchestration framework, no new
model-provider architecture, no `claude-agent-sdk` substitution for Ollama, no `<artifact>`-tag parsing
in the frontend, no Artifact Viewer, no production chat workflow, no frontend work, no deployment
scripts.

> **Redaction note.** The repository-root `.env` holds real credentials and was never read, printed or
> committed in this phase; it stays git-ignored (`git check-ignore -v .env` → `.gitignore:4`). No
> credential value appears anywhere in this transcript, in the source files, in the tests or in the
> smoke-test output. The only keys that appear in test code are obvious synthetic placeholders (for
> example `sk-ant-test-not-a-real-key`), used to assert that error paths redact them. No chain-of-
> thought, private prompt or hidden reasoning is recorded here — only what was executed, observed and
> measured. Provider "thinking" text is a separate channel in the runtime's response and is never read
> by the client, never logged, never returned.

---

## 1. Starting point

Phases 1–3 were complete and verified: FastAPI + Next.js + PostgreSQL/`pgvector`, 303 ingested
transcripts (22,327 chunks), a provider abstraction with an LLM factory, an application agent with a
deterministic intent router, an activity reporter and a tool registry in which the four product
capabilities were registered as **planned descriptors only** — the router could name a pathway but
nothing could execute it.

Phase 4's job was therefore precise: make the registered capabilities executable, without changing the
shape of the layer that routes to them.

---

## 2. Inspection before writing code

| Surface | What was found | What it changed |
|---|---|---|
| `app/rag/retrieval.py` | `search_transcript_chunks(db, query, top_k, min_similarity, guest, episode_id, provider)` returns `TranscriptSearchResult` (episode id, title, guest, publish date, youtube url, chunk index, content, similarity) | The search tool wraps exactly this function. No second query path, no new SQL |
| `app/agent/tools.py` | `AgentTool` (name, description, `intents`, `run(arguments, context)`), `ToolRegistry.available()`, `is_available()`, `default_registry()` | The registry already had the mechanism; Phase 4 only had to register real tools in it |
| `app/agent/agent.py` | `ExecutionPlan.generates_reply` gated replies; `PLANNED_*` handling in the router | The planned path was replaced by execution; the plan shape was unchanged |
| `messages.artifact` (Phase 1 schema) | A JSONB column that already existed for artifact payloads | Fixed the canonical artifact shape `{"type","title","content"[, "css"]}` — no new schema, no migration |
| `qwen3:4b` on Ollama 0.34.2 | A reasoning model: its private thinking consumes the same `num_predict` budget as the answer | Token budgets had to cover thinking *plus* the answer; the provider layer itself was not redesigned |

Late in the phase, live probes added two runtime facts that shaped the outcome:

| Measurement | Result |
|---|---|
| `POST /api/show` for the installed model | `qwen3.context_length = 262144` — the model supports far more context than the runtime uses |
| `GET /api/ps` before configuration | `context_length: 4096` — the runtime's own default, shared by thinking and answer |
| `POST /api/chat` with `think: false` (essay, 400-token budget) | 1684 characters of visible planning text ("Okay, the user wants…"), no article: disabling the reasoning channel moves planning into the answer |
| `POST /api/chat` with `think: true` (400-token budget) | 0 characters of content: the entire budget was spent thinking |
| Generation speed on this CPU (8.3 GB RAM) | 2.0–3.6 tokens/s; an 8192-token context costs ≈1.2 GB of KV cache |

---

## 3. Decisions taken before writing code

| Decision | Rationale |
|---|---|
| A capability is an `AgentTool`; the router stays a classifier | The task forbids a second router or orchestration framework |
| `SkillContext` is dataclass-passed, never global | A skill is unit testable with a fake client, an in-memory registry and no database |
| `SkillContext.client` is optional, accessed through `require_client()` | Transcript search needs a database but no model; `require_client()` raises an actionable `.env` error |
| `require_db()` instead of a hidden session lookup | A missing session is a wiring bug, so the tool fails loudly rather than returning "no evidence" |
| Evidence is a typed `EvidenceBundle`, not raw text | Grounded answer, essay and artifact all need the same passages, and the API must return episode metadata separately from the answer |
| Grounding is enforced structurally, not by prompt alone | With no usable evidence the Q&A skill returns the insufficient-evidence reply **without calling the model at all** — a test asserts the provider was never invoked |
| Retrieval stays generous; evidence has a quality floor | Two numbers: a 0.3 noise floor for what is worth returning at all, and a calibrated 0.71 evidence floor for what may be answered from |
| Ship30for30 length is a prompt contract plus deterministic measurement | The requirements are expressed as a section-level contract in one template, and `analyze_essay()` measures the result — so "did it follow the format" is data, not an assumption |
| The artifact is JSON produced by the model, validated by `Artifact` | Structured JSON is canonical, the Phase 1 column stores it as-is, and the frontend never parses tags out of prose |
| Composition is two explicit rules, not a planner | Both extra capabilities come from the registry; no graph, no planner |
| No new dependency | Everything is `dataclasses`, `re`, `json` and the existing stack |

---

## 4. What was built

### Capability layer — `backend/app/agent/skills/`

| File | Responsibility |
|---|---|
| `base.py` | `SkillContext` (`request`, `registry`, optional `client`/`db`/`agent_context`/`reporter`), `require_client()`, `require_db()`; `EvidenceBundle`; `evidence_to_dict()`; `format_evidence_block()` |
| `transcript_search.py` | `TranscriptSearchTool` (`transcript_search`), `run_transcript_search()` over the Phase 2 retrieval function, `gather_evidence()` with the evidence floor, `MAX_TOP_K` clamp, `TranscriptSearchError` translation |
| `grounded_qa.py` | `TranscriptQASkill` (`transcript_qa`): retrieves through the registry, then answers only from the passages; returns `MISSING_EVIDENCE_REPLY` without a model call when there is nothing to ground on |
| `ship30for30.py` | `Ship30For30Skill` (`ship30for30`), `SHIP30FOR30_SYSTEM_PROMPT`, the length contract (`SECTION_TARGET`, `MIN_SECTION_WORDS`, `MIN_TARGET_WORDS`), `build_essay_prompt()`, `analyze_essay()` → `EssayStructure` |
| `artifacts.py` | `ArtifactSkill` (`artifact_generator`), `ARTIFACT_SYSTEM_PROMPT`, `normalize_artifact_type()`, `detect_artifact_type()`, `parse_artifact()` → validated `Artifact`, `build_wrapped_artifact()` |
| `__init__.py` | The registry surface: the four skills plus `EvidenceBundle`, `SkillContext` |

### Provider and configuration changes

| Change | Responsibility |
|---|---|
| `app/llm/base.py` | `generate(..., think: bool \| None = None)` and the same kwarg on `stream()`: an optional reasoning switch for providers that expose one, ignored by providers that do not |
| `app/llm/ollama_client.py` | `think` is forwarded as the **top-level** `think` key of the chat payload (not inside `options`); `num_ctx` is opt-in via configuration and only sent when set; a non-positive value is rejected; the empty-answer error message now names the budget as the likely cause |
| `app/llm/anthropic_client.py` | Accepts and deliberately ignores `think` (no equivalent knob); nothing else changed |
| `app/config.py`, `app/llm/factory.py` | `OLLAMA_NUM_CTX` (default `0` = the runtime's own default) wired into the client |
| `.env.example` | `OLLAMA_NUM_CTX=0` with comments explaining the trade-off |
| `.env` (never read) | `OLLAMA_NUM_CTX=8192` for this machine; presence verified with a count-only check, never by printing the file |

### Agent integration — `backend/app/agent/`

| Change | Responsibility |
|---|---|
| `agent.py` | `_execute_capability()` runs the routed tool from the registry; `_gather_evidence_if_needed()` and `_should_wrap_in_artifact()` are the two composition rules; `_compose_artifact()` wraps deterministically. `AgentResult` gained `artifact`, `sources`, `skills`, `metadata` |
| `tools.py` | `default_registry()` registers the four skills; the *planned* descriptor mechanism is kept for later phases |
| `router.py` | Docstrings updated to the Phase 4 boundary; the classification and pathway logic itself is unchanged |
| `api/dev_agent.py` | Dev-only search endpoint alongside the existing `capabilities`, `route`, `respond`; the agent call now passes a database session |

### Verification surface

| File | Responsibility |
|---|---|
| `backend/scripts/smoke_skills.py` | Real verification against the live knowledge base and the local provider: knowledge base, transcript search, grounded Q&A, insufficient-evidence behaviour (stub and live), Ship30for30, markdown artifact, HTML/CSS artifact, composition. Prints PASS/FAIL/SKIPPED, `done_reason`, `output_tokens`, generation seconds and raw retrieval scores; `--only` runs a subset. No prompt, reasoning or answer text is printed beyond a short preview |
| `backend/scripts/smoke_llm.py` | Updated: the knowledge-base pathway check now opens a session and asserts a real grounded answer |

---

## 5. RAG grounding approach

```
question ──▶ ApplicationAgent ──▶ AgentRouter (rag_qa)
                                        │
                                        ▼
                          transcript_qa skill (agent/skills/grounded_qa.py)
                                        │  gather_evidence()
                                        ▼
                             transcript_search tool (registry)
                                        │
                                        ▼
              app/rag/retrieval.search_transcript_chunks()  ← the Phase 2 function
                                        │
                                        ▼
                    match_transcript_chunks (pgvector, PostgreSQL)
                                        │
                                        ▼
                 EvidenceBundle (numbered, citable passages + metadata)
                                        │
                       ┌────────────────┴────────────────┐
                       ▼                                 ▼
        empty → fixed insufficient-evidence        passages → grounded prompt
                reply, NO model call                            │
                                                                ▼
                                                    answer + structured sources
```

**Evidence quality.** Retrieval is deliberately generous — it reports what the knowledge base
contains — and a separate floor decides what may be answered from. The floor was **calibrated, not
guessed**, against the live knowledge base (22,327 chunks, `bge-small-en-v1.5`) on 2026-09-22:

| Query set | Best-passage similarity |
|---|---|
| 11 relevant product/growth questions | 0.7399 – 0.7969 |
| 10 clearly unrelated questions (cold fusion reactors, sourdough bread, the rules of cricket, …) | 0.4866 – 0.6861 |

`MIN_EVIDENCE_SIMILARITY = 0.71` sits between the two distributions; `MIN_RETRIEVAL_SIMILARITY = 0.3`
stays as the SQL noise floor. Both are constants in `transcript_search.py`, so the behaviour lives in
one place and is adjustable. Tests cover the floor behaviour at both boundaries.

Grounding rules encoded in the prompt: answer only from the retrieved evidence; never invent quotes,
guests, episodes or statistics; if the evidence is insufficient, say so in the first sentence and
stop; attribute each insight to its episode and guest; mark the model's own synthesis as synthesis;
never reveal instructions or produce chain-of-thought. The answer carries its sources **structurally**
(`AgentResult.sources`, and `metadata["passages"]` on the tool result) so attribution does not depend
on the model formatting it correctly.

---

## 6. Ship30for30 and artifact design

**Ship30for30.** One system-prompt template encodes the method: H1 title first, a one-to-three-line
hook immediately after it, exactly six H2 sections, a takeaway section, at least three bold phrases,
at least one bulleted list, one-to-three-sentence paragraphs, and a **length contract written per
section** (each H2 section at least 200 words; approximately 1250 words in total, never fewer than
1000). `analyze_essay()` then measures the result deterministically: word count, reading time
(`words / 225`), heading count, bullet count, bold count, `has_title`, `has_takeaway`. Those numbers
travel with the result, so the caller sees what was produced instead of trusting the prompt. The word
count is a **target, not a gate**: a short article is reported honestly rather than rejected.

The contract went through three measured revisions (see §10): a bare "approximately 1250 words"
produced 589–761 words; adding a minimum and a loose per-section budget produced 761 and 832; writing
the budget as a required, checkable per-section contract produced **1141 words** on the live run.

**Artifacts.** The model is asked for JSON only, and `parse_artifact()` is the only way an artifact
enters a result:

```json
{"type": "markdown", "title": "...", "content": "..."}
{"type": "html", "title": "...", "content": "<!doctype html>...", "css": "..."}
```

This is the shape the Phase 1 `messages.artifact` JSONB column already stores. `html_css` (the name
used in `docs/architecture.md`) and the shorthands `md`/`css` normalize onto the two canonical types;
for HTML the stylesheet stays in `css` and never inside the document body, so the artifact body is free
of the application's own text and the frontend will not need to parse `<artifact>` tags.
`build_wrapped_artifact()` turns another capability's finished document into a validated artifact
without a model call.

---

## 7. Composition

Two rules, both implemented in `ApplicationAgent` and both resolving their extra capability through the
registry:

1. **Evidence enrichment.** When the routed intent is not `rag_qa` but the request references Lenny's
   sources (a secondary RAG intent or an explicit reference to the podcast), evidence is retrieved
   first and handed to the capability as an argument — so an essay "based on what guests said" is
   grounded without the essay skill knowing anything about retrieval.
2. **Essay → artifact.** When the request is both an essay and an artifact request, the finished
   article is wrapped into a markdown artifact **deterministically**: `build_wrapped_artifact()` takes
   the document as it is and reads the title from its own H1. A unit test asserts one provider call for
   the whole composed request, and the live check reports `provider_calls=1` for the same reason — a
   second call would mean the artifact was regenerated rather than reused. The reply stays the article;
   the artifact rides alongside it.

Neither rule introduces a planner, a graph or a new abstraction: they are two branches in the existing
execution step, and every capability they touch is a normal registry entry.

---

## 8. Failures, debugging and corrections

| Problem | Cause | Correction |
|---|---|---|
| `NameError: EVIDENCE_BLOCK_EMPTY` in `gather_evidence` | The constant was used but not imported when the evidence floor was added | Import added; the focused run then passed |
| Agent API tests failed once execution was wired | The Phase 3 tests asserted "planned" descriptors and a `rag_qa` pathway that never executed | Tests were **updated to the new boundary** (execution, grounding, artifacts, capability failure), never weakened or deleted |
| Artifact API test asserted the wrong detail string | The real user-facing message differs from the assumed one | Assertion corrected to the real message |
| Error-translation tests failed with "requires a database session" | `run_transcript_search` checks the session before delegating | Tests pass a session (or assert the missing-session message) |
| `normalize_artifact_type("html css")` raised | Spaces are stripped before the alias lookup, so it is genuinely not an alias | Assertion changed to `" HTML "` (whitespace, which *is* tolerated) instead of inventing an alias |
| Sample article in a test had only two bold phrases | The test fixture, not the skill | Third bold phrase added |
| RAG activity-stage order test failed | The skill retrieves internally, so `EXECUTING_CAPABILITY` is emitted before `RETRIEVING_EVIDENCE` | Order test corrected with a comment explaining why |
| Composed-request test expected an artifact confirmation as the reply | The reply is the article; the artifact rides alongside it | Assertions corrected |
| A test for "capability available but no tool" was impossible | Availability is derived from the same registry | Replaced with an `InconsistentRouter` stub feeding an inconsistent plan |
| First real Ollama probe failed with `LLMResponseError: … exhausted the token budget` | `qwen3:4b` is a reasoning model: 300 tokens were consumed by thinking, leaving no answer | Budgets calibrated against a real probe (1500 tokens → 197 s, 715 output tokens) |
| `smoke_llm.py` still asserted `status == "pathway_prepared"` | Written for the Phase 3 boundary | Rewritten to open a session and assert a real grounded answer with sources |
| Live run #1: insufficient evidence reported `TranscriptSearchError: … no database session` | The smoke path had not been given a session when the live check was added | The check now opens a session; the stub check uses a registry-based `EmptySearchTool` |
| Live run #1: composed request failed with "did not return a valid artifact structure" | The essay was being re-emitted through a second generation, which the model could not do reliably | Replaced with the deterministic `build_wrapped_artifact()`; the live run then passed |
| Live run #1 crashed at cleanup with `psycopg2.OperationalError` | The pooled connection is closed by the server during a 20-minute generation and the session close was unguarded | Cleanup is guarded; a failed close is reported as a one-line note instead of a traceback |
| Live run: HTML/CSS artifact FAILED with "used the whole token budget without returning an answer" | 4096 output tokens, all spent in the reasoning channel, no content | Runtime context raised (`OLLAMA_NUM_CTX=8192`, measured KV-cache cost) and the HTML prompt tightened |
| HTML/CSS artifact FAILED **again** after that change | Same 4096-token ceiling; `done_reason=length`, zero content | One further configuration was tested (below) rather than repeated retries |
| HTML/CSS artifact with `think=false` FAILED differently | 4096 tokens of content, but no JSON object in it: the model wrote the document in the wrong envelope | The reasoning switch is kept as a **provider capability** (implemented, tested, opt-in) but the skills send no flag, because it was measured not to resolve this and a non-reasoning model should stay on its normal path. See §12 |
| Live retrieval returned 3 passages for a clearly off-topic question (top 0.684) and the no-evidence branch was SKIPPED | The evidence floor was 0.3, which almost any question clears | Floor calibrated to 0.71 from live relevant/unrelated distributions; the same probe now returns no evidence and makes no provider call |
| Test fixtures with similarity 0.61/0.62 became "not evidence" | They sat below the new floor | Fixtures raised to 0.75/0.73, preserving each test's intent, and explicit floor tests were added instead |

---

## 9. Tests

The complete Phase 1 + 2 + 3 suite still runs; nothing was disabled or reduced.

**Phase 4 test modules (new):**

| File | Tests | Focus |
|---|---|---|
| `test_skill_transcript_search.py` | 15 | valid query, retrieval delegation, parsing, metadata preservation, empty result, error translation, top-k clamping, real-DB retrieval, weak matches reported but not used as evidence, floor filtering |
| `test_skill_grounded_qa.py` | 10 | evidence in the prompt, grounded answer, source metadata, insufficient evidence with **zero** provider calls, weak-match rejection, mixed-strength passages, grounding rules in the prompt, provider failure, missing provider |
| `test_skill_ship30for30.py` | 11 | structure detection, word-count/reading-time metadata, the length contract in system and user turns, short article reported honestly, evidence in the prompt, `analyze_essay()` and `build_essay_prompt()` units |
| `test_skill_artifacts.py` | 23 | markdown, HTML/CSS separation, alias normalization, type detection, JSON-only prompt, evidence/source-output prompts, malformed and non-JSON rejection, oversize, title truncation, capability/provider failures, the reasoning switch staying unset |
| `test_agent_skills.py` | 12 | each intent executes its capability, evidence enrichment, essay→artifact composition, general requests still direct, unregistered capability, retrieval failure + activity, payload hygiene, error categories |

**Provider/config tests added to existing files:** the `think` flag reaching the payload (and staying
out of `options`), forwarding while streaming, `num_ctx` sent only when configured, a non-positive
`num_ctx` rejected, and the `OLLAMA_NUM_CTX` default.

**Suite total: 373 passed** (292 at the end of Phase 3; 71 of the total are the Phase 4 modules).

---

## 10. Real verification (Ollama `qwen3:4b` + live pgvector)

All statuses below are exactly as printed by `backend/scripts/smoke_skills.py` against the real
database and the real local provider. Runs are listed in the order they happened, including the ones
that failed — the failures are why the corrections above exist.

| # | Run / check | Status | Detail as printed |
|---|---|---|---|
| 1 | full run, 20:08 — transcript search tool | PASS | 3 passages in 111.4 s; top: Luc Levesque, similarity 0.811 |
| 1 | grounded Q&A | PASS | 857.2 s, `intent=rag_qa`, evidence=5, grounded=True, sources=5 |
| 1 | artifact generation (markdown) | PASS | 996.8 s, title `Product Retention Strategy`, content_chars=2813 |
| 1 | artifact generation (HTML/CSS) | **FAIL** | `LLMResponseError: … used the whole token budget without returning an answer` |
| 1 | insufficient evidence (live retrieval) | **FAIL** | session wiring bug (`… no database session was provided`) |
| 1 | Ship30for30 article | PASS | 448.2 s, words=589, headings=6, bullets=3, bold=5, takeaway=True |
| 1 | composed request (essay → artifact) | **FAIL** | `ArtifactGenerationError: … did not return a valid artifact structure` |
| 1 | run cleanup | crash | `psycopg2.OperationalError` while closing a stale pooled connection (fixed) |
| 2 | 21:23 — markdown artifact | PASS | 1376.2 s, content_chars=1336 |
| 2 | HTML/CSS artifact | **FAIL** | same token-budget error |
| 2 | insufficient evidence (stub) | PASS | grounded=False, evidence=0, provider_calls=0 |
| 2 | composed request | PASS | 578.5 s, skills=ship30for30,artifact_generator, article_words=722, artifact_chars=4396 |
| 3 | 21:36 — insufficient evidence (live retrieval) | **SKIPPED** | live retrieval returned 3 passages (top 0.684), so the no-evidence branch was not reached (floor was 0.3) |
| 3 | Ship30for30 article | PASS | 578.1 s, words=705 |
| 4 | 21:51 — Ship30for30 article | PASS | 841.1 s, words=761 |
| 5 | 22:23 — markdown artifact (**`OLLAMA_NUM_CTX=8192`**) | PASS | 1496.1 s, content_chars=887, `done_reason=stop`, output_tokens=2961 |
| 5 | HTML/CSS artifact | **FAIL** | 4096/4096 tokens generated, `done_reason=length`, **no content at all**; effective config `num_ctx=8192`, `max_tokens=4096` |
| 6 | 02:17–02:47 — HTML/CSS artifact with `think=false` | **FAIL** | 4096 tokens, `done_reason=length`, content present but *no JSON object* (`The artifact response did not contain a JSON object`); effective config `num_ctx=8192`, `think=false`, `max_tokens=4096` |
| 7 | 08:09 — grounded Q&A (relevant query) | PASS | 666.2 s, evidence=5, grounded=True, sources=5, top source `The disease of process people / Marty Cagan` |
| 7 | source metadata preserved | PASS | guest / publish date / YouTube link present for the retained sources |
| 7 | off-topic retrieval scores | PASS | raw retrieval returned 3 passages for the off-topic question, **best similarity 0.6844**, evidence floor 0.71 |
| 7 | insufficient evidence (live retrieval) | PASS | **1.3 s**, raw_retrieval=3, evidence=0, **provider_calls=0**, fixed insufficient-evidence reply |
| 8 | 08:32 — Ship30for30 (contract v2) | PASS | 723.7 s, words=832, headings=5, bullets=3, bold=7, takeaway=True, `done_reason=stop`, output_tokens=2066 |
| 9 | 09:21 — Ship30for30 (contract v3) | PASS | 875.0 s, **words=1141** (target 1250), reading_time=5 min, headings=6, bullets=3, bold=7, takeaway=True, `done_reason=stop`, output_tokens=2232 |
| 9 | composed request (essay → artifact) | PASS | 1347.3 s, skills=ship30for30,artifact_generator, article_words=1184, artifact_type=markdown, artifact_chars=7619, **provider_calls=1** |
| 9 | run cleanup | note | `closing the database session reported OperationalError` — cleanup only, reported as a note, exit code 0 |

**Essay length history, same brief and same model:** 589 → 722 → 705 → 761 words (original prompt) →
832 (loose per-section budget) → **1141** (explicit per-section contract: six sections, ≥200 words
each, ≥1000 total). 1141 words is 91% of the 1250-word target and above the contract's floor.

**What the live runs prove, and what they do not:**

- Transcript search, grounded Q&A with 5 attributed sources, the calibrated evidence floor, and the
  no-evidence branch with zero provider calls: **verified live**.
- Markdown artifact generation, and essay→artifact composition with exactly one model call:
  **verified live**.
- HTML/CSS artifact generation: **NOT verified live.** It is implemented, unit-tested and exposed
  through the same registry path, and both realistic configuration levers were tried once each with
  the measurements recorded above. The capability is preserved — not removed, not marked unsupported.
- Anthropic cloud: **SKIPPED.** No usable API key or paid access exists in this environment, so no
  cloud generation was attempted and none is reported. The cloud provider is covered by mocked unit
  tests and is unchanged by this phase except for accepting the ignored `think` kwarg.
  `claude-agent-sdk` still requires the native `claude.exe` on Windows; Ollama was never treated as a
  substitute for it.

---

## 11. Security review

- No new secret of any kind. The only configuration variable added is `OLLAMA_NUM_CTX`, a context size.
- `.env` remains git-ignored (`git check-ignore -v .env` shows `.gitignore:4`); `.env.example` holds
  placeholders only. A sweep of the tree for credential patterns matched only placeholders and
  synthetic test values (`postgresql://user:pw@host:5432/db`, `sk-ant-…` used to assert redaction).
- Errors are translated into actionable user-facing text (`TranscriptSearchError`,
  `ArtifactGenerationError`, `LLMConfigurationError` from `require_client()`); internal details stay
  in logs, never in API responses, and no user-facing message contains a machine path, credential,
  stack trace or prompt. The empty-answer message names the budget, not the prompt.
- Prompts contain an explicit instruction not to reveal system prompts, configuration or credentials
  and not to produce chain-of-thought; artifact parsing accepts JSON only, so a model that wraps an
  explanation around the payload has it rejected rather than surfaced.
- The runtime's thinking channel is a separate response field that the client never reads, so private
  reasoning cannot appear in a reply, a log line or an API response; the smoke check records only
  provider-level facts (`done_reason`, `output_tokens`, durations), never prompt or answer text.
- Retrieved transcript text is treated as the only source of truth and clearly delimited as evidence,
  which also keeps prompt-injection material inside the evidence block rather than in the instruction
  position.
- Activity events carry fixed wording and allow-listed detail keys only; a test asserts the user's
  question does not appear in them.
- The dev-only verification endpoints remain gated behind `APP_ENV != production`.

---

## 12. Known limitations

- **HTML/CSS artifact generation does not complete with `qwen3:4b` on this machine.** With thinking
  on, the whole 4096-token output budget is spent in the reasoning channel and no content is
  returned; with `think=false`, content is produced but it is not the requested JSON envelope. The
  path is implemented, validated in tests, and reachable through the same registry entry as the
  working markdown path; the limitation is the local 4B reasoning model plus the 4096-token output
  budget at ~2–3 tokens/s, not the skill's design. A non-reasoning model, a larger output budget, or a
  hosted provider is the expected fix, and the provider `think` switch is already available for a
  model that needs it.
- The evidence floor (0.71) is calibrated from 21 live queries on this corpus; it is one measured
  constant in one place, not a universally correct threshold. A different embedding model would need
  it recalibrated.
- Grounding is enforced by prompt plus the no-evidence short circuit; a model can still drift from the
  passages on a subtle question where evidence exists but is weak.
- Ship30for30 length is a target, not a gate: 1141 words is reported as 1141 words. Closing the last
  ~9% reliably would need a longer contract still or a second drafting pass — out of scope here.
- The pooled database connection can be closed by the server during a 20-minute generation; cleanup
  reports it as a note. A fresh session per request is the real fix and belongs to the phase that
  introduces the production request path.
- Only two composition rules exist by design; any richer planning belongs to a later phase.
- Artifact rendering itself is Phase 5 work; Phase 4 guarantees the structured payload only.

---

## 13. Boundary

This is still Phase 4. **Phase 5 was not started**: no chat UI, no Artifact Viewer, no streaming or
SSE, no LLM toggle, no production workflow, no deployment work, and no frontend changes beyond what
Phases 1–3 already shipped.
