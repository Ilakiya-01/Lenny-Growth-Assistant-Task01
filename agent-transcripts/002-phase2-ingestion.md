# 002 — Phase 2: Knowledge Base & Ingestion

**Date:** 2026-09-22
**Scope (from `docs/roadmap.md`):** configurable transcript source path, transcript discovery, YAML
frontmatter parsing, transcript extraction and normalization, metadata preservation, configurable
chunking, configurable embeddings, `pgvector` storage, vector similarity search foundation,
repeatable/idempotent ingestion, verification.

**Explicit exclusions honoured:** Claude Agent SDK, Pi Coding Agent, application agent runtime,
agentic routing, transcript-grounded conversational Q&A, chat endpoint over the knowledge base,
Ship30for30, artifact generation, Artifact Viewer, full conversational chat UI, cloud/local LLM
switching, Ollama LLM generation, SSE chat streaming. The vector search function is part of the
knowledge base and was verified directly with a CLI and SQL probes; no application agent was built
to demonstrate it.

> **Redaction note.** The database credential used during this session (a full PostgreSQL connection
> URI including password and project reference) is replaced with `<REDACTED>`/`<project-ref>`/
> `<region>` placeholders. No API key was ever set for this phase (the selected embedding provider is
> local), so nothing else required redaction. `.env` is git-ignored; only `.env.example` with empty
> placeholders is committed.

---

## 1. Starting point

Phase 1 had left a working FastAPI + Next.js + Supabase stack with `users`, `sessions`, `messages`
(13 passing tests). No transcript, embedding or `pgvector` code existed, and the transcript dataset
was not present on the machine.

Phase 2 needed a real corpus. The dataset specified by the task
(`https://github.com/ChatPRD/lennys-podcast-transcripts`) was cloned **outside** the application
repository, as `docs/architecture.md` §25 requires:

```bash
git clone --depth 1 https://github.com/ChatPRD/lennys-podcast-transcripts /d/lennys-podcast-transcripts
```

Result: 303 episodes in `episodes/<guest-slug>/transcript.md`, 4.64M words total, each file
frontmatter + `# Title` + `## Transcript` + speaker turns.

---

## 2. Decisions taken before writing code

| Decision | Rationale |
|---|---|
| `episode_id` = the episode **folder slug**, not `video_id` | The dataset's `video_id` is not unique: 301 files contain only 269 unique ids (e.g. `andy-raskin` and `andy-raskin_` are the same talk twice). The folder name is unique and stable |
| Local embedding model `BAAI/bge-small-en-v1.5` | Asked the developer to choose between a paid cloud API (OpenAI) and open local models. Answer: **local open model**. 384 dimensions, 512-token window, ~1 GB download, no API key, no per-token cost |
| Dimension verified *before* writing the migration | The task forbids guessing: the model was loaded and `get_embedding_dimension()` printed 384, and `max_seq_length` printed 512, before `vector(384)` was written into the migration |
| Token-aware chunking implemented directly, no LangChain | The task explicitly says not to add a framework merely because it was mentioned as an example. The chunker is ~170 lines, testable with a fake tokenizer and free of a large dependency |
| Chunking counts **tokens from the model's own tokenizer** | Documented in the module docstring, `.env.example`, `docs/architecture.md` §8.5 and the README so character- and token-based counting are never mixed |
| `CHUNK_SIZE=400`, `CHUNK_OVERLAP=60` | Leaves headroom inside the 512-token model window and keeps neighbouring chunks connected |
| Chunk identity `(episode_id, chunk_index)` with a unique constraint | Makes re-ingestion idempotent: `ON CONFLICT ... DO UPDATE ... WHERE content/metadata changed` writes nothing when the corpus is unchanged |
| `metadata.chunk_tokens` and `metadata.embedding_model` recorded per chunk | Chunk size is auditable, and changing the embedding model invalidates the stored chunks (they are rewritten on the next run) |
| Ingestion commits per episode | An interrupted run is resumed by rerunning the same command; one bad file cannot roll back the whole corpus |
| `ingestion/` at the repository root, RAG code in `backend/app/rag/` | Matches `docs/architecture.md` §25; the CLI adds `backend/` to `sys.path` so the operational scripts and the API share one implementation |
| `match_transcript_chunks` defined with `SET search_path = public, extensions` | pgvector is installed in the `extensions` schema on this Supabase project, so the function must resolve `vector` types itself |

A question was put to the developer at this point: local open model or paid cloud API. Answer:
**local open model (`bge-small-en-v1.5`, 384 dims)** — which fixed the database dimension at 384.

---

## 3. What was built

New modules under `backend/app/rag/`:

| File | Responsibility |
|---|---|
| `discovery.py` | Finds every `episodes/*/transcript.md` below `TRANSCRIPTS_PATH`; raises readable errors for a missing path, missing `episodes/` directory or an empty corpus |
| `parsing.py` | Splits YAML frontmatter from the body, preserves all metadata, normalizes the body, parses dates |
| `chunking.py` | Token-aware paragraph → sentence → hard-window chunking with sentence-level overlap |
| `embeddings.py` | `EmbeddingProvider` abstraction, local sentence-transformers provider, OpenAI provider, factory driven by `EMBEDDING_PROVIDER` |
| `retrieval.py` | `search_transcript_chunks()` — embeds the query and calls the `match_transcript_chunks` SQL function |
| `pipeline.py` | Orchestrates discovery → parse → chunk → embed → upsert and reports metrics |

Database and CLI:

| File | Responsibility |
|---|---|
| `backend/alembic/versions/0002_transcript_chunks.py` | `vector` extension, `transcript_chunks`, HNSW index, `match_transcript_chunks` function |
| `backend/app/db/repositories/transcript_repository.py` | Idempotent upsert, stale-tail pruning, embedding-dimension checks, counts |
| `ingestion/ingest.py` | Ingestion CLI (`--limit`, `--episode`, `--dry-run`, `--verbose`) |
| `ingestion/search.py` | Vector-search CLI (`--top-k`, `--min-similarity`, `--guest`, `--episode`) |

Configuration (`backend/app/config.py`, `.env.example`): `TRANSCRIPTS_PATH`, `EMBEDDING_PROVIDER`,
`EMBEDDING_MODEL`, `EMBEDDING_BATCH_SIZE`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `OPENAI_API_KEY` (empty
placeholder). Relative `TRANSCRIPTS_PATH` values resolve from the repository root, and no personal
absolute path is hard-coded anywhere.

### Edge cases found in the real dataset

Discovery and parsing were validated against files that do not follow the happy path:

| File | Quirk | Handling |
|---|---|---|
| `andy-raskin` / `andy-raskin_` | Duplicate `video_id` for two folders | `episode_id` is the folder slug, so both are ingested distinctly; `video_id` stays in metadata |
| `daniel-lereya` | Empty `video_id` and `youtube_url`, no `publish_date` | Empty strings are treated as absent, the episode still ingests |
| `nickey-skarstad` | `spotify_id` instead of `video_id` | Unknown keys are preserved in `metadata`, nothing is dropped |
| `teaser_2021` | Only `guest` + `keywords`, no title | Title falls back to the body's `#` heading |

---

## 4. Failures, corrections and debugging

### 4.1 Truncated first write of `parsing.py`

The first `Write` of `parsing.py` was cut short by the tool's output limit, leaving a syntactically
incomplete file. It was rewritten in full. Two follow-up cleanups: a convoluted `_build_metadata`
was simplified, and an unused `metadata_to_json` helper plus its `json` import were removed.

### 4.2 Double-appended unit in the chunk packer

The first `_pack_units` implementation appended a unit twice after flushing a full chunk, producing
duplicated text. Corrected by restructuring the loop around a `fits()` closure with
`while len(current) > 1 and not fits(current): current.pop(0)`, which drops carried overlap context
only when it cannot coexist with the next unit.

### 4.3 A false alarm in the overlap check

A first overlap check compared the last six words of chunk 0 with the **first** six words of chunk 1
and printed `overlap present: False`. The chunker was correct — the carried text is not necessarily
the first thing in the next chunk when a new paragraph follows. Re-checking "does chunk 1's opening
appear at the tail of chunk 0" showed **78/78** chunks carrying trailing context. Lesson recorded:
verify the invariant, not a guess about its shape.

### 4.4 `get_sentence_embedding_dimension` deprecation

sentence-transformers 6.1 emits a `FutureWarning` for the old accessor. A `_model_dimension()` helper
now prefers `get_embedding_dimension()` and falls back to the old name.

### 4.5 Noisy third-party output in the CLI

The ingestion CLI printed httpx HEAD/GET lines from the Hugging Face hub, model loading progress bars
and a transformers notice about sequences longer than the model maximum. Both CLIs now set
`transformers` to ERROR, `httpx`/`huggingface_hub` to WARNING and `HF_HUB_DISABLE_PROGRESS_BARS=1`.
The "sequence longer than the model maximum" notice is expected: long transcripts are tokenized for
chunking but never embedded whole.

### 4.6 `AttributeError: 'MetaData' object has no attribute '_bulk_update_tuples'`

**The most instructive failure of the phase.** The first live ingestion of a single episode stored
nothing and reported:

```text
failure: episodes/ada-chen-rekhi/transcript.md -> AttributeError: 'MetaData' object has no attribute '_bulk_update_tuples'
```

The per-episode error handling did its job — the run continued, reported the failure and exited
non-zero instead of dying silently. The traceback pointed at
`postgres_insert(TranscriptChunk).values(rows)` inside `upsert_episode_chunks`. Passing the **ORM
class** to a Core `insert()` makes SQLAlchemy route the multi-row `values()` through its ORM
bulk-persistence path, which resolves dict keys against mapped attributes. One of the keys is
`metadata` — on the ORM class that resolves to the declarative `MetaData` object (the mapped
attribute for the JSONB column is named `metadata_json`), so SQLAlchemy called
`_bulk_update_tuples` on a `MetaData` instance.

Corrected by running the statement against the Core table `TranscriptChunk.__table__`, where `metadata`
is a plain column key. The behaviour was then verified directly against the database:

```text
run1: UpsertOutcome(inserted=1, updated=0, unchanged=0, pruned=0)
run2 (unchanged): UpsertOutcome(inserted=0, updated=0, unchanged=1, pruned=0)
run3 (changed):   UpsertOutcome(inserted=0, updated=1, unchanged=0, pruned=0)
```

### 4.7 A scrapped prototype function left in the database

After applying migration `0002`, inspection showed **two** `match_transcript_chunks` overloads: the
new five-argument function, and an older three-argument prototype (`vector, double precision,
integer`) that selected a `transcript_chunks.episode_title` column which never existed in any
committed revision. Leaving it would make three-argument calls ambiguous. The cleanup
(`DROP FUNCTION IF EXISTS match_transcript_chunks(vector, double precision, integer)`) was added to
migration `0002` itself — not run by hand — and the migration was re-applied (downgrade + upgrade,
table empty at the time). Afterwards exactly one overload remains, with
`proconfig = {"search_path=public, extensions"}`.

### 4.8 Test-expectation bugs found while writing the Phase 2 suite

Writing the tests surfaced five incorrect expectations of mine, all in the tests rather than the
code:

| Wrong expectation | Reality |
|---|---|
| Two three-token paragraphs each become their own chunk at `chunk_size=10` | 8 tokens fit in one chunk; the test needed `chunk_size=4` |
| Two paragraphs of 8+4 tokens do not fit at `chunk_size=12` | They fit exactly; the test needed `chunk_size=11` |
| A character-counting fake tokenizer produces word-sized windows | It produces character windows (28, not 4); the test now uses the word tokenizer |
| Repeated fake words prove overlap | The fixture itself contained the duplicates; the fixture now uses unique words |
| `_words(...)` joined with spaces produces many paragraphs | It produces one paragraph, which forced the hard-window path; paragraphs are now joined with `\n\n` |
| `duration: 1:23:45` stays a string | Unquoted `H:MM:SS` is YAML 1.1 sexagesimal (an integer). The real dataset quotes it (`duration: '3:50'`), which the fixture now mirrors |

A further test bug was environmental: `test_vector_search_ranks_the_closest_chunk_first` initially
searched the whole table and failed **because the live ingestion was filling the table with real
chunks that outranked the fixtures**. The assertion was scoped with the `episode_id` filter; the
"failure" was evidence that search works over real data.

### 4.9 A stray line and a typing nit

A comment line was accidentally added next to `TRANSCRIPTS_PATH` in `.env.example` and removed after
review. `chunks: Sequence` in `pipeline._store_episode` was tightened to `Sequence[Chunk]`.

---

## 5. Verification

### 5.1 Migration

```text
alembic current   -> 0001_initial_schema
alembic upgrade   -> Running upgrade 0001_initial_schema -> 0002_transcript_chunks
alembic_version   -> 0002_transcript_chunks
```

Verified in the live database:

| Check | Result |
|---|---|
| `transcript_chunks.embedding` type | `vector(384)` |
| Row count after migration | 0 |
| Indexes | `ix_transcript_chunks_embedding_hnsw`, `ix_transcript_chunks_episode_id`, `pk_transcript_chunks`, `uq_transcript_chunks_episode_chunk` |
| `match_transcript_chunks` overloads | 1 — `(vector, integer, double precision, text, text)`, `search_path=public, extensions` |
| Probe call on the empty table | `[]` (no error) |

The dimension was not guessed: it was read from the loaded model (`384`) and `max_seq_length` (`512`)
before the migration was written, and the migration comment records that a model change requires a
new migration.

### 5.2 Dry run over the whole corpus

```bash
backend/.venv/Scripts/python.exe ingestion/ingest.py --dry-run
```

| Metric | Value |
|---|---|
| Files discovered | 303 |
| Episodes processed | 303 |
| Chunks generated | 22,327 |
| Failures | 0 |
| Elapsed | 3m20s |

All 303 transcripts parse, normalize and chunk; every failure path that would have been hit by a
malformed file was exercised by the unit tests instead.

### 5.3 Live ingestion and idempotency

Smoke run (`--episode ada-chen-rekhi`): 79 chunks generated, 79 inserted, 0 failures, 1m10s.
Immediate re-run of the same episode:

```text
chunks inserted     : 0
chunks updated      : 0
chunks unchanged    : 79
chunks pruned       : 0
failures            : 0
```

No row was written on the second run — the idempotency requirement is satisfied by observation, not
by assumption.

Full-corpus run and vector-search verification: see §6.

---

## 6. Full-corpus ingestion and vector-search verification

### 6.1 The crash in the first full run, and the recovery

The first full-corpus run reached 50/303 episodes and then **died with exit code 139** (SIGSEGV /
`0xC0000005` — an access violation, not a Python exception, so nothing could be caught and logged).
The log simply stopped after `[50/303] camille-ricketts`.

Diagnosis: the machine has 7.7 GB of RAM with only ~1.1 GB free, and a concurrent benchmark run I
started (loading a second copy of the embedding model, ~600 MB) pushed it over. Nothing in the
application was at fault — but the failure was instructive about the design:

- Ingestion commits **per episode**, so the 57 completed episodes were intact in the database.
- Rerunning the whole corpus would have re-embedded ~4,000 already-stored chunks (the embedding step
  is the entire cost), so the remaining work was selected with the repeatable `--episode` flag:

```python
# remaining = discovered episodes whose slug is not in transcript_chunks.episode_id
backend/.venv/Scripts/python.exe ingestion/ingest.py --episode <246 slugs>
```

The resumed run then completed cleanly. This is exactly the "resume by rerunning" behaviour the
idempotent design promises, exercised for real.

### 6.2 Full-corpus results

| Run | Episodes | Chunks inserted | Failures | Elapsed |
|---|---|---|---|---|
| First run (crashed at episode 51) | 57 | 4,079 | 0 | ~35 min |
| Resumed run (`--episode` × 246) | 246 | 18,248 | 0 | 92m02s |
| **Corpus total** | **303** | **22,327** | **0** | – |

22,327 chunks matches the dry-run count exactly, so every discovered file was ingested and no file
was silently skipped or double-counted.

### 6.3 Database integrity checks (live)

| Check | Result |
|---|---|
| Episodes / chunks | 303 / 22,327 |
| Distinct embedding dimensions | `{384}` |
| Null or non-normalized embeddings | 0 (all norms ≥ 0.99) |
| Episodes whose first chunk is not index 0 | 0 |
| Chunks with `guest` / `publish_date` / `youtube_url` | 22,327 / 22,132 / 22,068 |
| Average / maximum `chunk_tokens` | 324 / **400** (the `CHUNK_SIZE` bound is never exceeded) |
| `metadata.embedding_model` | `BAAI/bge-small-en-v1.5` on every row |
| Publish-date range | 2022-01-01 → 2026-01-11 |
| Credential-shaped values in `metadata` | 0 |

### 6.4 Idempotency on a re-run (live)

`ingestion/ingest.py --limit 8` on already-ingested episodes:

```text
chunks generated    : 582
chunks inserted     : 0
chunks updated      : 0
chunks unchanged    : 582
chunks pruned       : 0
failures            : 0
elapsed             : 2m59s
```

Row counts before and after: 303 episodes / 22,327 chunks — unchanged. Combined with the earlier
single-episode check (79/79 unchanged), re-running ingestion writes nothing.

### 6.5 `match_transcript_chunks` and the HNSW index (live)

Querying with a chunk's **own** stored embedding:

```text
('todd-jackson', 7,  1.0000)   <- the chunk itself
('todd-jackson', 6,  0.9192)   <- neighbouring chunk of the same episode
('rahul-vohra',  47, 0.8982)   <- related product-market-fit segment
```

The query plan for the same ordering confirms the index is used:

```text
Limit
  ->  Index Scan using ix_transcript_chunks_embedding_hnsw on transcript_chunks c
        Order By: (embedding <=> '[...]'::vector)
```

`CREATE INDEX ix_transcript_chunks_embedding_hnsw ... USING hnsw (embedding vector_cosine_ops)
WITH (m='16', ef_construction='64')`.

### 6.6 Semantic queries on the real corpus

A real product/growth question, run through the CLI (retrieval only — no agent, no answer
generation):

```bash
backend/.venv/Scripts/python.exe ingestion/search.py "how do I find product-market fit for a new product?" --top-k 5
```

| Rank | Similarity | Result |
|---|---|---|
| 1 | 0.805 | *How marketplaces win* — Benjamin Lauzier, chunk 22 (PMF discussion) |
| 2 | 0.796 | *A framework for finding product-market fit* — Todd Jackson, chunk 7 |
| 3 | 0.794 | *Superhuman's secret to success* — Rahul Vohra, chunk 47 |
| 4 | 0.786 | *A founder's guide to crisis management* — Uri Levine, chunk 20 |
| 5 | 0.784 | *A framework for finding product-market fit* — Todd Jackson, chunk 17 |

The top two are literally the PMF-framework episodes, and the Rahul Vohra chunk is the segment about
"find something people want". Filters were exercised too:

```bash
# Guest filter: all results from the Madhavan Ramanujam pricing episodes
ingestion/search.py "how should I price my SaaS product?" --guest "Madhavan Ramanujam" --top-k 3
# -> 0.739 / 0.738, both from "Pricing your AI product: Lessons from 400+ companies and 50 unicorns"

# Episode + similarity filters also verified through the automated tests
```

### 6.7 Small output fix found during verification

The first CLI run printed `A founder�s guide` — a mangled typographic apostrophe. The stored value is
correct UTF-8 (`'A founder’s guide to crisis ma'`, `U+2019` present); the legacy console code page
was responsible. Both CLIs now call `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` after
logging setup, and the title renders correctly.

### 6.8 Automated tests

```text
70 passed in 41.13s
```

| File | Tests | Covers |
|---|---|---|
| `tests/test_config.py` | 5 | Phase 1 URL normalisation |
| `tests/test_health.py` | 1 | Health endpoint |
| `tests/test_sessions_api.py` | 7 | Session API against the real database |
| `tests/test_rag_discovery.py` | 6 | Discovery, missing path/`episodes/`/empty corpus |
| `tests/test_rag_parsing.py` | 13 | Frontmatter, metadata preservation, normalization, malformed input |
| `tests/test_rag_chunking.py` | 11 | Token bounds, overlap, sentence/hard-window splitting, invalid config |
| `tests/test_rag_embeddings.py` | 14 | Provider factory, aliases, dimension table, BGE query prefix (no model download) |
| `tests/test_rag_pipeline.py` | 3 | One bad file does not abort the run, episode/limit selection, dry run writes nothing |
| `tests/test_rag_repository.py` | 10 | Idempotent upsert, in-place update, pruning, vector ranking, filters, dimension mismatch |

The database-backed tests skip automatically when the database is unreachable or unmigrated, and
remove every row they create (verified: 0 rows with a `__pytest%` episode id after the suite).

### 6.9 Secret scan

| Check | Result |
|---|---|
| `postgresql://`, `postgres://`, `supabase`, `password`, `pooler`, `sk-` in the ingestion logs | 0 matches |
| Credential-shaped strings in `backend/`, `ingestion/`, `docs/`, `README.md`, `.env.example`, `agent-transcripts/` | only documented example URIs with `user:pw@host` placeholders |
| Hard-coded personal absolute paths (`D:\`, `C:\Users`, the dataset path) in code/docs | 0 matches |
| `.env` tracked by git | no — `.gitignore` has `.env`, `.env.*` with `!.env.example` |
| Dataset clone inside the application repository | no — sibling directory `../lennys-podcast-transcripts` |

---

## 7. Phase boundary

Nothing from Phase 3 or later was implemented: no Claude Agent SDK, no agent runtime, no agentic
routing, no chat endpoint over the knowledge base, no transcript-grounded Q&A, no Ship30for30, no
artifact generation, no Artifact Viewer, no streaming, no Ollama or cloud LLM selection. The vector
search function was verified directly (CLI + SQL), not by building an application agent to
demonstrate it.

---

## 8. Known limitations and assumptions

| Item | Note |
|---|---|
| Embedding throughput | ~2.2 chunks/s on this 8-core CPU-only machine (~3 hours for the full corpus). The model is CPU-bound; a GPU or a smaller batch does not change the corpus, only the wall-clock time |
| Memory | The machine had ~1 GB free RAM; a second model process caused the SIGSEGV described in §6.1. Ingesting on a machine with more headroom, or with nothing else loading the model, avoids this. The design already recovers: rerun, or pass the remaining `--episode` values |
| `duration` semantics | The dataset quotes `duration` (`'3:50'`), so it is stored as a string; `duration_seconds` is stored as a number. An unquoted `1:23:45` in some future file would be read by PyYAML as YAML 1.1 sexagesimal (an integer) — noted, not worked around |
| Model change | Switching `EMBEDDING_MODEL` to a different dimension requires a new migration (the column is `vector(384)`); the pipeline fails fast with a clear message instead of silently truncating |
| Duplicate episodes | Two dataset folders can contain the same talk (`andy-raskin`, `andy-raskin_`). Both are ingested, because `episode_id` is the folder slug; deduplicating by `video_id` was deliberately not done |
| `publish_date` coverage | 22,132 of 22,327 chunks (99.1%) carry a date; the rest come from episodes without a parseable date |
| Test isolation | The repository tests scope their assertions with `episode_id` filters because the live corpus shares the table |

