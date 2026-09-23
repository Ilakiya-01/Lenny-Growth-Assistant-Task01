# 003 — Phase 3: Agentic Routing & LLM Factory

**Date:** 2026-09-22
**Scope (from `docs/roadmap.md`):** unified LLM provider abstraction, Anthropic Cloud and Ollama
local providers, an LLM factory for config-driven provider selection, the core application agent and
agentic router, intent classification, execution-path preparation, minimal backend integration to
verify the layer, tests, verification.

**Explicit exclusions honoured:** the transcript-grounded Q&A skill, the transcript-search
skill/tool, any production use of `match_transcript_chunks`, Ship30for30 generation, artifact
generation, the Artifact Viewer, the production chat workflow, the full frontend chat UI, production
SSE streaming, full skill composition, and deployment scripts. The router recognises the future
capabilities as *planned* intents; it never executes them.

> **Redaction note.** No Anthropic key was ever set in this session, so no cloud credential existed
> to leak. The local database credential and the `.env` file are untouched by this phase and remain
> git-ignored. Test and smoke-test credentials are obvious synthetic placeholders (for example
> `sk-ant-test-not-a-real-key`) used only to assert that error paths redact them. Nothing in this
> transcript is a real credential, token or password.

---

## 1. Starting point

Phases 1 and 2 were complete and verified: FastAPI + Next.js + PostgreSQL/`pgvector`, 70 passing
tests, 303 ingested transcripts. There was **no** LLM code at all — no provider abstraction, no
factory, no agent, no router. `docs/architecture.md` described the intended design (provider
layers, a classifier, execution paths); `docs/roadmap.md` listed Phase 3's scope.

---

## 2. Inspection before writing code

The task forbids guessing about SDK interfaces, so all three external surfaces were inspected on the
machine before a line of provider code was written.

| Surface | Version found | What inspection changed |
|---|---|---|
| `anthropic` | 1.7.0 | It depends on **`httpx2`**, not `httpx`. Tests had to mock `httpx2.AsyncClient` / `httpx2.MockTransport` (`httpx2==2.13.0` pinned in `requirements-dev.txt`). `AsyncAnthropic(api_key=…, http_client=…, max_retries=…, timeout=…)` is the documented construction path |
| `anthropic` sampling params | 1.7.0 | `messages.create()` / `messages.stream()` **no longer accept `temperature` or `top_p`** at all. Sampling moved into `output_config` (`effort`, `format`). The provider therefore does not forward a temperature, and a regression test asserts it is absent from the payload |
| `claude-agent-sdk` | 0.2.157 | `ClaudeAgentOptions`, `AssistantMessage`/`ResultMessage`, `TextBlock`/`ThinkingBlock`, `ThinkingConfigDisabled`. On Windows the SDK refuses the npm `claude.cmd` shim and needs the native `claude.exe`; it is not installed here |
| Ollama | 0.34.2 (live) | `POST /api/chat` with `{model, messages, stream, options{num_predict, temperature}}`; `GET /api/tags`; `GET /api/version`. `qwen3:4b` is a **reasoning** model: with a small budget it spends everything on `message.thinking` and returns `content: ""` with `done_reason: "length"` |

That last Ollama finding was not a theoretical concern — it broke the first smoke-test run (see §9).

---

## 3. Decisions taken before writing code

| Decision | Rationale |
|---|---|
| Prove the SDK surface with real code before designing around it | The `temperature` removal is exactly the class of breakage the task warns about ("do not invent SDK methods"). A throwaway inspection script found it in minutes; discovering it after writing the provider would have meant redesigning the request path |
| `httpx2` pinned in `requirements-dev.txt` with an explanatory comment | The provider tests mock the SDK's *real* transport, so the transport package is a test dependency in its own right, and pinning keeps the mocks honest |
| Provider layer ≠ runtime layer | `BaseLLMClient` is a thin, uniform async text-generation contract. `ClaudeAgentRuntime` (Claude Agent SDK) and `ProviderAgentRuntime` (plain provider call) are *runtimes* that execute a prepared plan. The task warns "do not assume Ollama can simply be substituted into the Claude Agent SDK" — separating the two layers is the structural answer |
| The router is provider-agnostic | Classification is deterministic heuristics by default; the configured provider is consulted only for low-confidence reclassification and only when `LLM_ROUTER_LLM_CLASSIFICATION=true`. Routing therefore works offline, with no key, and with no paid calls |
| `LLM_MODE` accepts `local` as an alias of `ollama` | `docs/architecture.md` §13.1 said `cloud\|local`; the task said `cloud\|ollama`. Rather than silently pick one, both are accepted, `ollama` is canonical, and the conflict was written up in architecture.md §13.1 instead of guessed at |
| Activity events carry fixed wording + an allow-listed detail-key set | The task forbids emitting chain-of-thought, prompts or private tool arguments. Making the *data structure* reject those keys is stronger than remembering not to pass them |
| `ExecutionPlan.generates_reply` gates reply generation | Planned (Phase 4) intents structurally cannot produce a reply: only `DIRECT_RESPONSE` sets it, so a future skill cannot be "accidentally" executed by this phase's agent |
| Reasoning models: treat an empty answer at `done_reason=length` as a token-budget error | Surfacing "the model returned nothing" would be confusing; the actionable message tells the operator to raise the budget or choose a non-reasoning model. Private `thinking` is never used as an answer |
| No LangChain/LlamaIndex and no new framework | Same reasoning as Phase 2's chunker: the abstraction needed here is ~200 lines of plain Python |

---

## 4. What was built

### Provider layer — `backend/app/llm/`

| File | Responsibility |
|---|---|
| `base.py` | `BaseLLMClient` (async `generate()`, optional `stream()`, `describe()`), `LLMMessage`, `LLMResponse`, `LLMChunk`, `LLMUsage`, the typed error hierarchy, `split_system_message()`, `sanitize_error_text()` and credential redaction |
| `anthropic_client.py` | Anthropic cloud provider over the pinned SDK; system-message hoisting, token-limit handling, streaming, status→error mapping, key redaction |
| `ollama_client.py` | Ollama provider over HTTP (`/api/chat`, `/api/tags`); `num_predict`/`options` mapping, NDJSON streaming, model listing/checking, actionable errors for an unreachable server or a missing model |
| `factory.py` | `create_llm_client()` and `normalize_llm_mode()` — the single place `LLM_MODE` becomes a client |

### Agent layer — `backend/app/agent/`

| File | Responsibility |
|---|---|
| `intents.py` | `Intent` enum (`rag_qa`, `ship30for30`, `artifact_generation`, `general`), `ExecutionPath`, `ExecutionPlan` |
| `classifier.py` | `HeuristicIntentClassifier` (deterministic, signal-based) and `LLMIntentClassifier` (label + confidence only) |
| `router.py` | `AgentRouter` — classify → resolve execution pathway → report capability availability |
| `context.py` | `AgentContext` — session id, user request, conversation history, provider settings; loads history from the Phase 1 session tables |
| `tools.py` | `AgentTool` interface + `ToolRegistry`; Phase 4 capabilities registered as descriptors with `available=False, phase=4` |
| `runtimes.py` | `AgentRuntime` interface, `ClaudeAgentRuntime` (Claude Agent SDK, tools/skills/settings/plugins disabled, thinking disabled), `ProviderAgentRuntime` |
| `activity.py` | `ActivityLog` + `ActivityEvent` with the allow-listed detail keys and fixed stage wording |
| `prompts.py` | The (small, non-leaking) instruction strings used by the classifier and reply step |
| `agent.py` | `ApplicationAgent` — wires router + runtime + registry + activity into one `handle(context)` entry point |

### Verification surface

| File | Responsibility |
|---|---|
| `backend/app/api/dev_agent.py` | Development-only `/api/dev/agent/{capabilities,route,respond}`; never registered when `APP_ENV=production` |
| `backend/scripts/smoke_llm.py` | Real-provider smoke test (router probes, provider construction, reachability, generation, streaming, agent construction, conversational request, pathway preparation) |

### Configuration

`backend/app/config.py` and `.env.example` gained `LLM_MODE`, `LLM_TIMEOUT_SECONDS`,
`ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_MAX_TOKENS`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`
and `LLM_ROUTER_LLM_CLASSIFICATION`. Placeholders only in `.env.example`; `.env` stays git-ignored.

---

## 5. The router and its classification approach

```
request ──▶ ApplicationAgent ──▶ AgentRouter ──▶ ExecutionPlan ──▶ (Phase 4 skill)
                                      │
                                      └──▶ LLM Factory ──▶ Anthropic cloud | Ollama local
```

Classification is **signal-based first**. The heuristic classifier scores the request against
curated signal groups (`rag:source_terms`, `rag:topic_terms`, `rag:attribution_terms`,
`rag:question_form`, `rag:interrogative`, and equivalents for the essay and artifact intents) and
returns an intent plus a confidence and the fired signal names. Signals are *names*, never the
prompt text, so the routing decision can be logged safely.

When confidence is below the threshold and LLM-assisted classification is enabled, the configured
provider is asked for a label and a confidence — nothing else. A model answer that cannot be parsed
into a known label raises `AgentClassificationError` rather than being echoed back. With
LLM-assisted classification off (the default) the provider is **never called** for routing, which
the tests assert directly with `client.calls == []`.

The four documented examples classify as required:

| Request | Intent | Execution path |
|---|---|---|
| "What did Lenny's guests say about product-market fit?" | `rag_qa` | `transcript_search` |
| "Write a 1250-word essay about finding product-market fit." | `ship30for30` | `ship30for30` |
| "Create a markdown product strategy document from this discussion." | `artifact_generation` | `artifact_generation` |
| "Hello, how are you?" | `general` | `direct_response` |

A planned intent produces a plan with `generates_reply=False`, `reply=None` and status
`pathway_prepared`. Every Phase 4 capability is a registry descriptor with `available=False`; the
router reports it and stops.

---

## 6. Failures, debugging and corrections

| Problem | Cause | Fix |
|---|---|---|
| `ImportError: attempted relative import with no known parent package` | `from .conftest import TEST_API_KEY` in a test module — `tests/` has no `__init__.py` | Defined the placeholder locally in the module instead |
| `TypeError: AsyncMessages.create() got an unexpected keyword argument 'temperature'` | The pinned `anthropic==1.7.0` removed sampling parameters | Stopped forwarding `temperature` in `create()` and `stream()`, documented it in the module docstring, and replaced the old assertion with a test that *asserts absence* from the payload |
| `AgentConfigurationError: No agent runtime is registered for LLM mode 'ollama'` (8 tests) | Real source bug: `ApplicationAgent.__init__` keyed the default runtime by *provider name* while `_runtime_for()` looks it up by *LLM mode* | Keyed the default runtime by the normalized LLM mode; removed an unused import |
| Router test asserted a 4-signal tuple, got 5 | `rag:interrogative` fires alongside `rag:question_form` for a question | Corrected the expectation — the extra signal is intentional |
| Router tests referenced a non-existent `tests/helpers.py` | Draft-test authoring error | Added a `ScriptedLLMClient` + `scripted_client` fixture to `conftest.py` and refactored both classifier and router tests onto it |
| API tests used `app.router.routes` introspection | This FastAPI version defers `include_router`, so `AttributeError: '_IncludedRouter' object has no attribute 'path'` | Replaced with behavioural `TestClient` tests |
| Smoke run 1: `provider construction` FAIL | The local `.env` had no Phase 3 block at all | Added the (non-secret) Phase 3 values, including `OLLAMA_MODEL=qwen3:4b` |
| Smoke run 2: `single generation`, `streaming generation` FAIL, `agent conversational request` timeout | The script passed `max_tokens=64`; `qwen3:4b` spent the entire budget on private reasoning and returned an empty answer. The agent check then hit the 120 s read timeout on CPU inference | Removed the token override so the configured budget is used, added the actionable token-exhaustion error to the Ollama provider, and raised the local `LLM_TIMEOUT_SECONDS` to 300 |
| README lost its `## API endpoints` heading during an edit | An edit replaced the heading along with the surrounding text | Restored it in the following edit |

---

## 7. Tests

**291 tests pass** (70 Phase 1+2 unchanged + **221 new**), `79.44s`.

| File | Tests | Covers |
|---|---|---|
| `test_agent.py` | 28 | Agent init with the configured provider, runtime selection, end-to-end general request, pathway preparation for planned intents, activity sequence, serialization safety, error categories |
| `test_agent_classifier.py` | 25 | The four documented examples, thresholds, exact signal tuples, secondary intents, no reasoning/temperature leakage, unusable model labels rejected |
| `test_llm_ollama.py` | 24 | `/api/chat` request shape, streaming, connect/timeout/HTTP/model-missing/malformed handling, model listing, token-budget diagnosis |
| `test_agent_api.py` | 23 | Capabilities/route/respond endpoints, 422/404/502/503 paths, no secret or traceback leakage, production gating of the dev routes |
| `test_llm_anthropic.py` | 20 | Real SDK against a mocked `httpx2` transport: request path/headers/payload, no sampling params, status→error mapping, timeouts, streaming, key redaction |
| `test_agent_router.py` | 19 | Structured routing output, no hidden reasoning, provider never called for deterministic routing, planned intents not executed |
| `test_agent_runtimes.py` | 18 | Both runtimes, block filtering (thinking dropped), options hardening, SDK error mapping without leaking machine paths |
| `test_llm_factory.py` | 16 | `cloud`→Anthropic, `ollama`/`local`→Ollama, invalid mode, missing cloud config, no silent fallback |
| `test_agent_activity.py` | 16 | Fixed wording, ordering, serialization, allow-listed keys, over-long values rejected |
| `test_llm_base.py` | 15 | Message validation, usage totals, system-message handling, redaction, default streaming, context-manager close |
| `test_agent_tools.py` | 10 | Registry register/discover, Phase 4 descriptors unavailable, duplicate/unnamed rejection |
| `test_agent_context.py` | 7 | Session history loading and trimming against the real database |

Provider tests never make a paid call: the Anthropic provider is exercised against the pinned SDK
through its own mocked transport, and Ollama through a mocked `httpx` transport.

---

## 8. Real smoke test — Ollama

`backend/scripts/smoke_llm.py` against the live local instance:

```
9 passed, 0 failed, 0 skipped
```

Including: the router recognised all four documented intents; the provider was constructed from
configuration; the server was reachable with one model installed; a real generation returned 142
characters; a real stream returned 16 chunks / 90 characters; the agent answered a conversational
request (`status=completed`, `intent=general`); and the agent prepared the RAG pathway
(`intent=rag_qa path=transcript_search capability=transcript_search reply_generated=False`).
Real generation is slow on CPU (~82 s), which is why the local timeout was raised.

## 8b. Live verification of the development endpoints

The three dev routes were also exercised against the **real, unstubbed** application (in-process
`TestClient`, real settings, real router):

```
GET  /api/dev/agent/capabilities   200  mode=ollama providers=['anthropic','ollama'] available_tools=[]
POST /api/dev/agent/route          200  rag_qa             -> transcript_search   (transcript_search, available=False)
POST /api/dev/agent/route          200  ship30for30        -> ship30for30        (ship30for30, available=False)
POST /api/dev/agent/route          200  artifact_generation-> artifact_generation (artifact_generator, available=False)
POST /api/dev/agent/route          200  general            -> direct_response    (capability=None, available=True)
GET  /api/health                   200  (unchanged Phase 1 endpoint)
```

Every classification was made by the `heuristic` classifier — no provider call was made for routing,
and every Phase 4 capability reported itself unavailable. `available_tools` is empty, which is the
structural proof that no Phase 4 skill is wired up.

## 9. Real smoke test — Anthropic cloud (NOT performed)

The cloud smoke check is **skipped, not passed**: no `ANTHROPIC_API_KEY` is configured on this
machine, and the Claude Agent SDK additionally requires the native `claude.exe` (the npm `claude.cmd`
shim is rejected on Windows), which is not installed. Nothing was fabricated to make this look green.
What *was* verified for real, unmocked: constructing `ClaudeAgentRuntime` and calling it raises a
genuine `CLINotFoundError` that maps to `LLMUnavailableError` with an actionable user message that
names neither the machine path nor any credential. The Anthropic provider's request/response path
remains covered by the mocked-transport suite.

---

## 10. Security review

- `.env` is matched by `.gitignore` and is untracked; `.env.example` contains placeholders only.
- No real credential exists anywhere in source, tests, docs, the smoke script or this transcript.
  The only `sk-ant-…`-shaped strings are marked synthetic placeholders used to prove redaction, and
  a test asserts the configured key never appears in an error string, `.detail` or user message.
- Provider errors expose a category and an actionable message; stack traces are logged, never
  returned.
- Activity events and routing results are asserted not to contain the prompt, the reply, the
  system prompt or any reasoning, and the allow-listed key set is enforced by construction.
- The development endpoints are not registered at all when `APP_ENV=production`, and a test proves
  both that they 404 there and that health/sessions still work.
- `match_transcript_chunks` is untouched and unreferenced by the agent layer.

---

## 11. Remaining limitations

1. **The cloud path has not been exercised against the real API** (no key, no Claude CLI).
2. `ApplicationAgent` answers only general requests end to end; the three planned intents stop at a
   prepared pathway by design — their execution is Phase 4.
3. Per-request provider override exists on the dev endpoint as the backend half of a future UI
   toggle; there is no frontend control yet.
4. Streaming exists in the provider layer but is not exposed over HTTP; production SSE is a later
   phase.
5. The heuristic classifier is tuned to the documented examples; LLM-assisted classification is
   available as an opt-in escape hatch rather than the default.
