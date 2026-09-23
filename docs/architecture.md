# Architecture Document

# The Lenny Growth Assistant

**Version:** 1.0  
**Status:** Draft for implementation  
**Document:** `docs/architecture.md`

---

## 1. Architecture Overview

The Lenny Growth Assistant is a full-stack agentic AI application with:

- Next.js frontend.
- FastAPI backend.
- PostgreSQL database through Supabase.
- `pgvector` for transcript semantic retrieval.
- Lenny's Podcast transcript ingestion pipeline.
- Application-level agent using the assignment-approved Claude SDK / Agent SDK or Pi Coding Agent.
- Cloud and local Ollama LLM providers behind a common interface.
- Ship30for30 writing skill.
- Artifact generation and in-app rendering.
- Persistent chat sessions and messages.

High-level architecture:

```text
                         ┌─────────────────────┐
                         │        User         │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │   Next.js Frontend  │
                         │                     │
                         │ Sidebar             │
                         │ Chat                │
                         │ Artifact Viewer     │
                         │ LLM Toggle          │
                         └──────────┬──────────┘
                                    │ HTTP/JSON
                                    ▼
                         ┌─────────────────────┐
                         │    FastAPI Backend  │
                         │                     │
                         │ API Routes          │
                         │ Session Service     │
                         │ Agent Service       │
                         │ Artifact Service    │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │   Application Agent │
                         │                     │
                         │ Decide / Route      │
                         │ Tool / Skill Calls  │
                         └──────┬─────┬─────┬──┘
                                │     │     │
                ┌───────────────┘     │     └────────────────┐
                ▼                     ▼                      ▼
       ┌────────────────┐    ┌────────────────┐    ┌─────────────────┐
       │ Transcript RAG │    │ Ship30 Skill   │    │ Artifact Skill  │
       └───────┬────────┘    └────────────────┘    └─────────────────┘
               │
               ▼
       ┌────────────────┐
       │ Supabase       │
       │ PostgreSQL     │
       │ + pgvector     │
       └────────────────┘

                         ┌─────────────────────┐
                         │    LLM Provider     │
                         │      Factory        │
                         └──────────┬──────────┘
                                    │
                         ┌──────────┴──────────┐
                         ▼                     ▼
                  ┌────────────┐       ┌────────────┐
                  │ Cloud LLM  │       │   Ollama   │
                  └────────────┘       └────────────┘
```

The exact implementation should remain simple enough for a take-home while keeping clear boundaries between components.

---

# 2. Component Responsibilities

## 2.1 Frontend

The frontend is responsible for:

- Rendering the application UI.
- Managing the selected chat session.
- Displaying conversation messages.
- Sending user messages to the backend.
- Displaying loading and error states.
- Displaying the current LLM mode.
- Rendering generated artifacts.
- Providing the session sidebar.

The frontend must not contain LLM provider credentials.

---

## 2.2 FastAPI Backend

The backend is responsible for:

- API routing.
- Session management.
- Message persistence.
- Calling the application agent.
- Loading conversation context.
- Connecting to the database.
- Managing LLM provider configuration.
- Returning agent responses.
- Returning artifact data.
- Handling application errors.

---

## 2.3 Application Agent

The application agent is the runtime agent inside the submitted product.

It is not the same as the development coding agent used to build the repository.

Three layers are involved when a request is answered, and they stay separate:

```text
┌──────────────────────────────────────────────────────────────────────┐
│ 1. Development coding agent (build-time only)                        │
│    The IDE/Qoder-style coding agent that wrote this repository.      │
│    It is a build tool. It is not shipped and is never called by the   │
│    running product.                                                  │
└──────────────────────────────────────────────────────────────────────┘
                                 │  produces the code of
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 2. Application Agent (product runtime) - app/agent/                  │
│    Receives the user request with its context, classifies it through │
│    the agentic router, selects the configured provider through the   │
│    LLM factory, prepares the execution pathway and produces the      │
│    structured result plus high-level activity events.                │
│    Runtime: Claude Agent SDK (cloud) or the provider client (Ollama).│
└──────────────────────────────────────────────────────────────────────┘
                                 │  executes model calls through
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 3. LLM Provider (model execution layer) - app/llm/                   │
│    Anthropic cloud models or local Ollama models behind one common   │
│    interface (BaseLLMClient). Swappable by configuration; it holds   │
│    no product logic and no routing decisions.                        │
└──────────────────────────────────────────────────────────────────────┘
```

The application agent is responsible for:

1. Understanding the user's request.
2. Determining whether a specialized capability is required.
3. Calling appropriate skills/tools.
4. Combining retrieved information with the user's conversation context.
5. Generating the final response.
6. Returning artifact information when an artifact is produced.

The agent should make capability decisions rather than forcing every request through every skill.

**Implemented in Phase 3:** responsibilities 1 and 2 (classification and pathways).

**Implemented in Phase 4:** responsibilities 3 to 6. The specialized capabilities are registered as
available tools - `transcript_search` and `transcript_qa` (grounded Q&A), `ship30for30` and
`artifact_generator` - and the agent executes the plan its router produced. Transcript search delegates
to the Phase 2 retrieval service (`app/rag/retrieval.py`); there is no second vector-search system.
Capability composition is limited to two explicit rules: evidence enrichment for non-RAG capabilities,
and feeding an essay into artifact generation.

---

## 2.4 Transcript RAG

The RAG subsystem is responsible for:

- Reading transcript data.
- Chunking transcripts.
- Generating embeddings.
- Storing embeddings.
- Performing vector similarity search.
- Returning relevant transcript chunks and metadata.

---

## 2.5 Ship30for30 Skill

The Ship30for30 skill is responsible for generating the requested approximately 1250-word structured essay.

It receives relevant user/conversation context and applies the writing requirements defined in the PRD.

---

## 2.6 Artifact Skill

The artifact skill is responsible for generating:

- Markdown artifacts.
- HTML/CSS artifacts.

The artifact output should be returned in a structured format that allows the frontend to render it.

**Implemented (Phase 4):** `backend/app/agent/skills/artifacts.py` asks the model for JSON only and
validates it before it can enter a result, so the artifact body never carries application text and the
frontend never parses `<artifact>` tags. Both canonical types are produced; `html_css` is accepted as
an alias and normalized to `html` with the stylesheet kept in its own `css` field. Composing an
artifact from another capability's finished output (essay → artifact) is deterministic and makes no
model call at all, because repackaging an existing document cannot improve it and can only truncate
it. The provider also accepts a per-call `think` flag so a reasoning model's private thinking cannot
consume a whole generation budget; live verification on the local `qwen3:4b` showed that flag changes
the failure mode but does not make this model return a valid HTML artifact, so the skills send no flag
by default and the limitation is documented rather than worked around per request.

---

## 2.7 Database

Supabase PostgreSQL is responsible for:

- User metadata.
- Sessions.
- Messages.
- Transcript chunks.
- Embeddings.

The database is the persistence layer for the application.

---

# 3. Frontend Architecture

A practical frontend structure:

```text
frontend/
├── app/
│   ├── page.tsx
│   ├── layout.tsx
│   └── globals.css
│
├── components/
│   ├── Sidebar.tsx
│   ├── ChatPane.tsx
│   ├── MessageList.tsx
│   ├── MessageInput.tsx
│   ├── ArtifactViewer.tsx
│   ├── LLMToggle.tsx
│   └── LoadingState.tsx
│
├── lib/
│   └── api.ts
│
└── types/
    └── index.ts
```

The exact file names can change during implementation.

### Session state

The frontend maintains:

```text
selectedSessionId
messages
artifact
llmMode
loading
error
```

The authoritative conversation history remains in PostgreSQL.

---

# 4. Backend Architecture

A practical FastAPI structure:

```text
backend/
├── app/
│   ├── main.py
│   │
│   ├── api/
│   │   ├── chat.py
│   │   ├── sessions.py
│   │   └── health.py
│   │
│   ├── agent/
│   │   ├── agent.py
│   │   ├── prompts.py
│   │   └── tools/
│   │       ├── transcript_search.py
│   │       ├── ship30.py
│   │       └── artifact.py
│   │
│   ├── llm/
│   │   ├── base.py
│   │   ├── factory.py
│   │   ├── cloud.py
│   │   └── ollama.py
│   │
│   ├── rag/
│   │   ├── embeddings.py
│   │   ├── retrieval.py
│   │   └── prompts.py
│   │
│   ├── db/
│   │   ├── database.py
│   │   ├── models.py
│   │   └── repositories/
│   │
│   ├── services/
│   │   ├── session_service.py
│   │   ├── chat_service.py
│   │   └── artifact_service.py
│   │
│   └── config.py
│
└── tests/
```

The structure is intentionally modular without requiring a large enterprise architecture.

---

# 5. Database Architecture

Supabase PostgreSQL is the initial database target.

The application should use PostgreSQL's `pgvector` extension for transcript embeddings.

## 5.1 Entity Relationship

```text
Users
  │
  │ 1:N
  ▼
Sessions
  │
  │ 1:N
  ▼
Messages


Transcript Chunks
      │
      └── Embedding vector
```

Sessions and transcript chunks are independent domains.

---

# 6. Database Schema

## 6.1 users

Stores user metadata required by the application.

Suggested fields:

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `metadata` | JSONB | Optional user metadata |
| `created_at` | TIMESTAMP | Creation time |

Authentication is not a required scope unless needed by the implementation.

For a single-user take-home, an anonymous/default user record may be sufficient.

---

## 6.2 sessions

Stores individual conversations.

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `user_id` | UUID | User reference |
| `title` | TEXT | Session title |
| `created_at` | TIMESTAMP | Creation time |
| `updated_at` | TIMESTAMP | Last update |

Relationship:

```text
users.id → sessions.user_id
```

---

## 6.3 messages

Stores individual conversation messages.

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `session_id` | UUID | Session reference |
| `role` | TEXT | `user`, `assistant`, or `system` |
| `content` | TEXT | Message content |
| `artifact` | JSONB | Optional artifact metadata/content |
| `created_at` | TIMESTAMP | Creation time |

Relationship:

```text
sessions.id → messages.session_id
```

---

## 6.4 transcript_chunks

Stores processed transcript content.

Suggested fields:

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `episode_id` | TEXT | Stable episode identifier |
| `guest` | TEXT | Guest name |
| `title` | TEXT | Episode title |
| `youtube_url` | TEXT | Source URL |
| `publish_date` | DATE | Publication date |
| `chunk_index` | INTEGER | Chunk order |
| `content` | TEXT | Chunk text |
| `metadata` | JSONB | Additional source metadata |
| `embedding` | VECTOR | Embedding vector |
| `created_at` | TIMESTAMP | Ingestion timestamp |

The exact vector dimension depends on the selected embedding model and must be configured consistently.

**Implemented (Phase 2)** as migration `0002_transcript_chunks`, dimension `vector(384)`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key, `gen_random_uuid()` |
| `episode_id` | TEXT | Episode folder slug from the transcript repository (unique per episode) |
| `guest` | TEXT | From frontmatter |
| `title` | TEXT | From frontmatter, falling back to the body heading |
| `youtube_url` | TEXT | From frontmatter |
| `publish_date` | DATE | Parsed from frontmatter when it is an ISO date |
| `chunk_index` | INTEGER | Zero-based position within the episode |
| `content` | TEXT | Chunk text |
| `metadata` | JSONB | Remaining frontmatter (video_id, duration, channel, view_count, source_path, ...) plus `chunk_tokens` and `embedding_model` |
| `embedding` | vector(384) | NOT NULL, unit-normalized |
| `created_at` | TIMESTAMPTZ | `now()` |

Constraints and indexes:

- `UNIQUE (episode_id, chunk_index)` — the chunk identity used for idempotent upserts.
- B-tree index on `episode_id`.
- HNSW index on `embedding` with `vector_cosine_ops`.

---

# 7. Vector Search Architecture

The transcript chunks are stored with embeddings in PostgreSQL using `pgvector`.

The retrieval system should use vector similarity search.

## 7.1 Similarity Metric

Cosine similarity is the intended similarity metric.

**Implemented (Phase 2):** cosine similarity (`<=>` in pgvector) over unit-normalized embeddings, exposed as `similarity = 1 - (embedding <=> query_embedding)`.

## 7.2 Vector Index

An HNSW index should be used where supported by the selected Supabase/PostgreSQL configuration.

Conceptually:

```text
User question
      ↓
Question embedding
      ↓
pgvector similarity search
      ↓
Top-k transcript chunks
      ↓
Agent context
```

The exact index definition must match the embedding dimension and database capabilities.

**Implemented (Phase 2):**

- Index: `ix_transcript_chunks_embedding_hnsw` — HNSW, `vector_cosine_ops`, `m = 16`, `ef_construction = 64`.
- pgvector 0.8.2 is installed in the `extensions` schema of the Supabase project; the migration issues `CREATE EXTENSION IF NOT EXISTS vector`.
- Search function: `match_transcript_chunks(query_embedding vector(384), match_count integer DEFAULT 5, match_threshold double precision DEFAULT NULL, filter_guest text DEFAULT NULL, filter_episode_id text DEFAULT NULL)` returns the chunk columns plus `similarity`, ordered by ascending cosine distance. It is defined with `SET search_path = public, extensions` and is called from `backend/app/rag/retrieval.py`, independently of the future application agent.

---

# 8. Transcript Ingestion Pipeline

The local Lenny repository is the source dataset.

Example configuration:

```env
TRANSCRIPTS_PATH=../lennys-podcast-transcripts
```

The path must be configurable.

## 8.1 Pipeline

```text
Local transcript repository
          ↓
Discover episodes
          ↓
Read transcript.md
          ↓
Parse YAML frontmatter
          ↓
Extract transcript body
          ↓
Normalize text
          ↓
Chunk transcript
          ↓
Generate embeddings
          ↓
Insert/upsert into PostgreSQL
          ↓
Create/update vector index
```

## 8.2 Source Discovery

The ingestion process should inspect the `episodes/` directory and identify transcript files.

The implementation should not depend on one hard-coded episode.

## 8.3 Metadata Parsing

Each transcript's YAML frontmatter should be parsed where available.

Useful metadata includes:

- Guest.
- Title.
- YouTube URL.
- Video ID.
- Publish date.
- Description.
- Duration.
- View count.
- Channel.

## 8.4 Text Extraction

Only the transcript content after the frontmatter should be treated as the primary searchable text.

## 8.5 Chunking

Chunking must be configurable.

Initial implementation should use a token-aware chunking strategy rather than arbitrarily splitting at a fixed character count.

The exact values should be chosen during implementation/testing and documented here once finalized.

The design should support:

```text
CHUNK_SIZE
CHUNK_OVERLAP
```

through configuration where practical.

**Implemented (Phase 2) — finalized:**

- **Unit: tokens**, counted with the selected embedding model's own tokenizer (`AutoTokenizer` for sentence-transformers, `cl100k_base` for OpenAI). `CHUNK_SIZE` and `CHUNK_OVERLAP` are never mixed with character-based counting. `CHUNK_SIZE` is a hard upper bound; `CHUNK_OVERLAP` is the token budget for repeated trailing context.
- **Defaults:** `CHUNK_SIZE=400`, `CHUNK_OVERLAP=60` (the model accepts 512 tokens, so a chunk always fits).
- **Strategy** (`backend/app/rag/chunking.py`): split on blank lines into paragraphs, which in this dataset are speaker turns. A paragraph larger than `CHUNK_SIZE` is split into sentences; a single sentence that still exceeds `CHUNK_SIZE` is split into hard token windows (stride `CHUNK_SIZE - CHUNK_OVERLAP`). Units are then greedily packed up to `CHUNK_SIZE`, and when a chunk closes its trailing sentence(s) within the overlap budget are repeated at the start of the next chunk so facts spanning a boundary stay retrievable.
- The realized overlap is emitted at sentence boundaries, so it can be slightly smaller than `CHUNK_OVERLAP` (or larger for a single oversized trailing sentence).
- Chunk token counts are stored per chunk in `metadata.chunk_tokens`.

## 8.6 Embeddings

The embedding provider/model must be configurable.

The selected embedding model must be compatible with:

- The ingestion environment.
- The retrieval environment.
- The PostgreSQL vector dimension.

The final selected model and dimension must be documented after implementation.

**Implemented (Phase 2) — finalized:**

- **Provider:** `sentence-transformers` (local, open weights, no API key, no per-token cost), selected with `EMBEDDING_PROVIDER`; `openai` is also implemented (`text-embedding-3-small` = 1536, `text-embedding-3-large` = 3072) and switched on purely by configuration.
- **Model:** `BAAI/bge-small-en-v1.5`, set with `EMBEDDING_MODEL`.
- **Dimension:** **384**, verified against the loaded model before the migration was written (`get_embedding_dimension()`), and enforced at runtime: ingestion and retrieval compare the provider dimension with `transcript_chunks.embedding` (`atttypmod`) and fail fast on mismatch. The dimension is fixed in migration `0002` and in `TRANSCRIPT_EMBEDDING_DIMENSION`; changing models requires a new migration.
- **Token limit:** 512 tokens (`max_seq_length`), the basis for the `CHUNK_SIZE` guard.
- **Normalization:** embeddings are unit-normalized, so cosine similarity is a dot product.
- **Query prefix:** bge models are queried with the documented instruction prefix (`Represent this sentence for searching relevant passages: `); documents are embedded without it.
- `EMBEDDING_BATCH_SIZE` (default 64) controls the batch size for local and API embedding calls.

## 8.7 Repeatable Ingestion

Ingestion should be safe to rerun.

A stable episode/chunk identity should be used to avoid unnecessary duplicate records.

**Implemented (Phase 2) — finalized:**

- Identity: `episode_id` = the episode folder slug (the dataset's `video_id` is not unique — 301 files contain 269 unique ids) and `chunk_index` = the chunk's position in the episode.
- Upsert: `INSERT ... ON CONFLICT (episode_id, chunk_index) DO UPDATE ... WHERE content IS DISTINCT FROM excluded.content OR metadata IS DISTINCT FROM excluded.metadata`. Unchanged chunks are not written at all; `RETURNING (xmax = 0)` separates inserts from updates.
- Tail chunks beyond the new chunk count are pruned, so a shorter re-chunk does not leave stale rows.
- Each episode is committed separately, so an interrupted run can be resumed by rerunning the command.
- The ingestion run reports discovered files, processed episodes, generated/inserted/updated/unchanged/pruned chunks, failures and elapsed time.

---

# 9. Retrieval Flow

For a transcript-grounded question:

```text
User message
     ↓
Application Agent
     ↓
Transcript Search Tool
     ↓
Create query embedding
     ↓
PostgreSQL pgvector search
     ↓
Top-k relevant chunks
     ↓
Metadata + chunk content
     ↓
Agent
     ↓
Grounded response
```

The retrieval tool should return enough metadata for the agent to understand the source.

Example tool result:

```json
{
  "results": [
    {
      "title": "Episode title",
      "guest": "Guest name",
      "content": "Relevant transcript chunk...",
      "youtube_url": "..."
    }
  ]
}
```

The actual response schema may differ.

---

# 10. Grounding Strategy

The transcript Q&A prompt should establish that retrieved transcript content is the authoritative knowledge source for transcript-grounded questions.

The agent should:

- Use retrieved transcript evidence.
- Avoid inventing transcript claims.
- Distinguish general conversational language from transcript-supported claims.
- State when relevant evidence is insufficient.

The agent should not claim to have retrieved information when retrieval did not occur.

**Implemented (Phase 4):** the rules above are enforced in `backend/app/agent/skills/grounded_qa.py`
and `backend/app/agent/skills/transcript_search.py`. Retrieval stays generous (a 0.3 noise floor), and
a separate evidence-quality floor (`MIN_EVIDENCE_SIMILARITY = 0.71`, calibrated against the live
knowledge base) decides what counts as evidence: only passages at or above it enter the evidence
bundle, and an empty bundle produces the fixed insufficient-evidence reply **without a model call**, so
there is no general-knowledge fallback. Source metadata (episode, guest, publish date, link, chunk
index, similarity) travels beside the answer as structured data rather than inside it.

---

# 11. Agentic Routing Architecture

The runtime agent should determine which capabilities are required.

Conceptual flow:

```text
                         User Request
                              │
                              ▼
                      ┌───────────────┐
                      │ Application   │
                      │     Agent     │
                      └───────┬───────┘
                              │
                 ┌────────────┼─────────────┐
                 │            │             │
                 ▼            ▼             ▼
           Transcript     Ship30for30    Artifact
            Search          Skill        Generator
                 │            │             │
                 └────────────┼─────────────┘
                              ▼
                       Final Response
```

## 11.1 Example: Transcript Question

```text
"What did Lenny's guests say about product-led growth?"
```

Expected capability:

```text
Agent
 ↓
Transcript Search
 ↓
Retrieve relevant chunks
 ↓
Generate grounded answer
```

## 11.2 Example: Ship30 Request

```text
"Write a 1250-word article about product discovery."
```

Expected capability:

```text
Agent
 ↓
Ship30for30 Skill
 ↓
Generate article
```

## 11.3 Example: Artifact Request

```text
"Turn this into a landing page."
```

Expected capability:

```text
Agent
 ↓
Artifact Generator
 ↓
HTML/CSS
 ↓
Artifact Viewer
```

## 11.4 Combined Request

```text
"Use Lenny's advice on onboarding and create a landing page based on it."
```

Expected flow:

```text
Agent
 ├── Transcript Search
 │       ↓
 │   Relevant evidence
 │
 └── Artifact Generator
         ↓
     HTML/CSS artifact
```

The architecture must support multiple tool calls when the task requires them.

---

# 12. Application Agent Tool Interface

The agent should have clearly defined tools.

## 12.1 Transcript Search Tool

Purpose:

Retrieve relevant Lenny transcript chunks.

Input:

```text
query: string
```

Optional parameters:

```text
top_k
```

Output:

```text
retrieved transcript chunks + metadata
```

---

## 12.2 Ship30for30 Tool/Skill

Purpose:

Generate an approximately 1250-word structured essay.

Input:

```text
topic/context
```

Output:

```text
formatted article
```

---

## 12.3 Artifact Generator

Purpose:

Generate a renderable artifact.

Input:

```text
artifact_type
context
requirements
```

Supported types:

```text
markdown
html_css
```

Output should contain:

- Artifact type.
- Artifact content.
- Optional title/metadata.

---

# 13. LLM Provider Architecture

The application should use a common LLM interface.

**Implemented (Phase 3)** in `backend/app/llm/`:

```text
        Application Agent  (app/agent/)
                │
                │  asks the factory for the configured provider
                ▼
        ┌───────────────────┐
        │   LLM Factory     │   create_llm_client() / normalize_llm_mode()
        │   app/llm/factory │   LLM_MODE decides the provider - no silent fallback
        └─────────┬─────────┘
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
  AnthropicLLMClient   OllamaLLMClient
  (Anthropic cloud)    (local Ollama HTTP API)
        │                   │
        └─────────┬─────────┘
                  ▼
        ┌───────────────────┐
        │  BaseLLMClient    │   async generate() + stream(); provider-neutral
        │   app/llm/base    │   messages, usage, response and error types
        └───────────────────┘
```

Conceptually:

```text
                    LLM Factory
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
        Cloud Provider          Ollama
              │                   │
              └─────────┬─────────┘
                        ▼
                  Common LLM API
                        │
                        ▼
                 Application Agent
```

The provider layer and the agent runtime layer are deliberately distinct. A provider client makes
single, stateless model calls; an *agent runtime* turns a prepared plan into a reply and is where the
agentic loop lives. Cloud mode uses the Claude Agent SDK runtime; local mode uses the provider client
directly, because the Claude Agent SDK targets the Anthropic runtime and is not an Ollama runtime.

## 13.1 Provider Selection

**Finalized (Phase 3).** The application reads the selected mode:

```text
cloud    Anthropic cloud models
ollama   local Ollama models
```

`local` is accepted as an alias of `ollama`; the assignment wording (`LLM_MODE=ollama`) and the
architecture wording (`local`) therefore both work, and the canonical value is `ollama`.

Example:

```env
LLM_MODE=local
```

or:

```env
LLM_MODE=cloud
```

`normalize_llm_mode()` performs the mapping and rejects anything else with an actionable
`LLMConfigurationError` that lists the valid values. A mode whose provider configuration is missing
(for example `cloud` without `ANTHROPIC_API_KEY`) fails with an explicit error instead of using another
provider.

The exact runtime switching mechanism may be implemented through a frontend toggle that sends the selected mode to the backend. The backend half exists in Phase 3 (a per-request `llm_mode` override on the development verification endpoint); the frontend toggle is Phase 5.

---

# 14. Cloud LLM

Cloud configuration should be loaded from environment variables.

**Finalized (Phase 3):**

```env
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-5
ANTHROPIC_MAX_TOKENS=2048
```

`CLOUD_LLM_API_KEY` / `CLOUD_LLM_MODEL` were the architecture's conceptual placeholder names; the
implemented names follow the approved provider (`ANTHROPIC_*`).

Two documented interfaces are used, both pinned in `backend/requirements.txt`:

- `anthropic` (the official SDK) for single model calls in `AnthropicLLMClient`.
- `claude-agent-sdk` for the cloud agent runtime in `ClaudeAgentRuntime`.

The pinned SDK version no longer accepts sampling parameters such as `temperature` on its Messages API,
so the provider-neutral `temperature` argument is not forwarded to Anthropic. The cloud runtime also
disables inherited machine configuration: no tools, no allowed tools, no filesystem settings, no
skills, no plugins and no extended thinking, so a cloud turn cannot silently pick up local state or
return private reasoning.

Cloud mode additionally needs the Claude Code runtime installed, and on Windows the SDK requires the
native `claude.exe` (the npm `claude.cmd` shim is rejected). When the runtime is missing, the failure is
reported as an actionable availability error - never as a fallback to another provider.

No credentials may be hard-coded.

---

# 15. Ollama Architecture

Ollama provides local model execution.

Example:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=<selected-model>
```

The backend communicates with Ollama through its local API or supported SDK integration.

**Implemented (Phase 3):** `OllamaLLMClient` calls the documented Ollama HTTP API directly through
`httpx` - `POST /api/chat` for generation (non-streaming and newline-delimited streaming) and
`GET /api/tags` to discover installed models. Ollama is *not* routed through the Claude Agent SDK: the
SDK targets the Anthropic runtime, so the local mode has its own explicit implementation behind the
shared `BaseLLMClient` interface.

Failure handling is explicit and never switches provider:

- An unreachable server (`ConnectError` / connect timeout) is an availability error naming the
  configured `OLLAMA_BASE_URL`.
- A model that is not installed is reported with the exact `ollama pull <model>` command to run.
- A malformed or unusable response (not JSON, no `message`, non-string or empty content, a broken
  streamed frame, an `error` frame) is a response error.
- A reasoning model that spends the whole token budget without returning answer text is reported as a
  budget problem. Its private `thinking` output is never used as the answer.

The README must explain:

1. Installing Ollama.
2. Pulling the selected model.
3. Starting Ollama.
4. Configuring the application.
5. Selecting Local mode.

All five steps are documented in the README's "LLM providers" section.

---

# 16. LLM Toggle Flow

The frontend exposes:

```text
┌──────────────────────────────┐
│ LLM Mode                     │
│                              │
│  Cloud  ◉───────○  Local     │
└──────────────────────────────┘
```

The selected mode is sent with or associated with the chat request.

Backend:

```text
request.llm_mode
       ↓
LLM Factory
       ↓
Cloud / Ollama
       ↓
Application Agent
```

The provider selection should not change the agent's skill/tool architecture.

**Implemented (Phase 3):** `request.llm_mode` is honored by the development verification endpoint,
which builds a temporary agent for that mode and closes it afterwards. Runtimes are keyed by LLM mode,
so the same agent code, router and tool registry are used for both providers - only the provider client
and the runtime differ. The UI toggle itself is Phase 5.

---

# 17. API Architecture

The exact endpoint implementation can evolve, but the initial API should be approximately:

## 17.1 Create Session

```http
POST /api/sessions
```

Request:

```json
{
  "user_id": "optional"
}
```

Response:

```json
{
  "id": "session-uuid",
  "title": "New Chat"
}
```

---

## 17.2 List Sessions

```http
GET /api/sessions
```

Response:

```json
{
  "sessions": [
    {
      "id": "session-uuid",
      "title": "Product Growth",
      "updated_at": "..."
    }
  ]
}
```

---

## 17.3 Get Session Messages

```http
GET /api/sessions/{session_id}/messages
```

Response:

```json
{
  "messages": [
    {
      "id": "message-uuid",
      "role": "user",
      "content": "..."
    }
  ]
}
```

---

## 17.4 Send Chat Message

```http
POST /api/chat
```

Request:

```json
{
  "session_id": "session-uuid",
  "message": "What did Lenny's guests say about onboarding?",
  "llm_mode": "local"
}
```

Response:

```json
{
  "message": {
    "role": "assistant",
    "content": "..."
  },
  "artifact": null
}
```

If response streaming is implemented, the endpoint may use SSE instead of returning one complete response.

Streaming is an implementation option rather than a mandatory PRD requirement.

---

## 17.5 Health Check

```http
GET /api/health
```

Response:

```json
{
  "status": "ok"
}
```

The health endpoint should not expose secrets or sensitive infrastructure information.

---

# 18. Response Streaming

Progressive response rendering is desirable for a conversational AI experience.

If supported by the selected LLM SDK and implementation, `/api/chat` may use Server-Sent Events (SSE) or another streaming mechanism.

When SSE is used, artifact delivery should remain structured rather than embedded in ordinary assistant text. A practical event protocol is:

```text
activity       -> high-level agent status
token          -> normal assistant text
artifact_ready -> {type, title, content}
done           -> completion signal
```

The frontend should consume `artifact_ready` directly and should not parse `<artifact>` tags from streamed assistant text. This keeps the Artifact Viewer compatible with progressive chat responses without requiring the entire response to be buffered.

Conceptually:

```text
User
 ↓
POST /api/chat
 ↓
Agent
 ↓
Streaming tokens/events
 ↓
Frontend progressively renders response
```

Streaming should not complicate the architecture unnecessarily.

A non-streaming implementation remains acceptable if the chosen agent/SDK architecture makes reliable streaming impractical for the take-home.

---

# 19. Artifact Architecture

Artifact generation returns structured data rather than raw untyped text when possible.

Example:

```json
{
  "type": "html_css",
  "title": "Product Landing Page",
  "content": "<!doctype html>..."
}
```

or:

```json
{
  "type": "markdown",
  "title": "Product Strategy Notes",
  "content": "# Strategy..."
}
```

The backend stores artifact information with the relevant assistant message where useful.

The frontend uses the artifact type to select the renderer.

---

# 20. Artifact Rendering Security

Generated HTML is untrusted content.

The frontend must not blindly inject generated HTML into the main application's DOM without an appropriate isolation strategy.

Preferred approach:

```text
Generated HTML
      ↓
Sandboxed iframe
      ↓
Artifact Viewer
```

For example, an iframe can use an appropriate sandbox configuration.

The exact security configuration must be validated during implementation.

Markdown should be rendered through a controlled Markdown renderer with appropriate HTML handling.

---

# 21. Session Context Architecture

Each request is associated with a session ID.

Flow:

```text
Frontend
   ↓
session_id
   ↓
FastAPI
   ↓
Load session messages
   ↓
Application Agent
   ↓
Generate response
   ↓
Save user + assistant messages
   ↓
Return response
```

The backend must ensure that messages from other sessions are not included in the agent context.

---

# 22. Error Handling Architecture

Errors should be classified into user-facing categories.

## 22.1 Cloud Provider Error

Example:

```text
Unable to reach the configured cloud LLM.
Please check the API configuration and try again.
```

## 22.2 Ollama Error

Examples:

- Ollama not running.
- Model unavailable.
- Connection refused.
- Timeout.

User-facing message should explain that local model execution is unavailable.

## 22.3 Database Error

Examples:

- Connection failure.
- Timeout.
- Query failure.

The frontend should display a clear error rather than a generic blank screen.

## 22.4 Retrieval Error

If retrieval fails, the system should not silently invent transcript evidence.

## 22.5 No Relevant Results

This is not necessarily a system error.

The agent should explain that sufficient transcript evidence was not found.

## 22.6 Agent/Tool Error

Tool failures should be caught and surfaced appropriately.

## 22.7 Artifact Error

If generated artifact content is invalid or cannot be rendered, the UI should show a recoverable error.

---

# 23. Configuration

The project should use environment variables.

Example `.env.example`:

```env
# Database
DATABASE_URL=

# Backend
APP_ENV=development
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:3000

# Frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

# Transcript dataset
TRANSCRIPTS_PATH=../lennys-podcast-transcripts

# Embeddings
EMBEDDING_PROVIDER=sentence-transformers
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_BATCH_SIZE=64
OPENAI_API_KEY=

# Chunking
CHUNK_SIZE=400
CHUNK_OVERLAP=60

# LLM providers
LLM_MODE=ollama
LLM_TIMEOUT_SECONDS=120
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-5
ANTHROPIC_MAX_TOKENS=2048
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=
LLM_ROUTER_LLM_CLASSIFICATION=false
```

Only variables actually required by the final implementation should remain in the final file; that is what `.env.example` now does — it lists exactly the variables read by the Phases 1–6 implementation (database, backend, CORS, frontend API base URL, transcript path, embedding and chunking settings, `LLM_MODE`, timeouts, and the Anthropic/Ollama provider settings) with empty placeholders for every key and no unused entries.

---

# 24. Ingestion Configuration

The ingestion process should support configurable settings such as:

```env
TRANSCRIPTS_PATH=../lennys-podcast-transcripts
CHUNK_SIZE=400
CHUNK_OVERLAP=60
EMBEDDING_PROVIDER=sentence-transformers
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_BATCH_SIZE=64
```

Exact final values must be documented after testing.

**Finalized (Phase 2):** `CHUNK_SIZE=400` and `CHUNK_OVERLAP=60` are tokens from the selected model's tokenizer, chosen to fill the model's 512-token window while leaving room for the query prefix; `TRANSCRIPTS_PATH` defaults to `../lennys-podcast-transcripts` relative to the repository root and is resolved absolutely at runtime (never hard-coded); `EMBEDDING_PROVIDER` accepts `sentence-transformers` (default, local) and `openai`.

---

# 25. Project Structure

A practical final repository structure:

```text
lenny-growth-assistant/
│
├── frontend/                 # Next.js UI (Phase 1)
│
├── backend/
│   ├── alembic/versions/     # 0001_initial_schema, 0002_transcript_chunks
│   ├── app/
│   │   ├── api/              # FastAPI routers
│   │   ├── agent/            # application agent, router, context, tools, runtimes
│   │   ├── db/               # engine, models, repositories
│   │   ├── llm/              # LLM factory and providers (Anthropic, Ollama)
│   │   └── rag/              # discovery, parsing, chunking, embeddings, retrieval, pipeline
│   ├── scripts/              # developer tools (provider smoke test)
│   └── tests/                # backend test suite
│
├── ingestion/
│   ├── ingest.py             # ingestion CLI
│   └── search.py             # vector-search CLI
│
├── docs/
│   ├── PRD.md
│   ├── architecture.md
│   ├── design.md
│   └── roadmap.md
│
├── agent-transcripts/
│
├── .env.example
├── .gitignore
├── README.md
└── ...
```

The locally cloned Lenny transcript repository should remain outside the application repository unless there is a specific reason to include it.

Example:

```text
workspace/
├── lenny-growth-assistant/
└── lennys-podcast-transcripts/
```

---

# 26. Development-Agent Transcript Architecture

The development-agent transcript archive is a submission artifact.

Example:

```text
agent-transcripts/
├── 001-project-setup.md
├── 002-database.md
├── 003-transcript-ingestion.md
├── 004-rag.md
├── 005-fastapi.md
├── 006-application-agent.md
├── 007-skills.md
├── 008-frontend.md
├── 009-artifacts.md
├── 010-testing.md
└── 011-final-fixes.md
```

The archive must preserve the complete development interactions.

No interaction should be filtered simply because it was:

- Basic.
- Repetitive.
- A failed attempt.
- An incorrect approach.
- A debugging question.

Actual secrets must be removed before committing.

The architecture document only defines where these transcripts live; the transcripts themselves should remain complete.

---

# 27. Testing Architecture

Testing should exist at multiple levels.

## Unit Tests

Examples:

- Chunking.
- Metadata parsing.
- Retrieval formatting.
- Session services.
- Provider selection.
- Artifact validation.

## Integration Tests

Examples:

- Database.
- Transcript retrieval.
- Agent tools.
- FastAPI endpoints.

## End-to-End Tests

Examples:

```text
Create session
 ↓
Send question
 ↓
Retrieve transcript
 ↓
Agent response
 ↓
Persist messages
```

And:

```text
Request artifact
 ↓
Generate artifact
 ↓
Render artifact
```

---

# 28. Observability and Logging

Application logs should be useful for debugging but must not expose secrets.

Useful information includes:

- Request/session identifier.
- Agent action/tool selected.
- Retrieval success/failure.
- LLM provider mode.
- Error category.
- Processing duration where useful.

Do not log:

- API keys.
- Passwords.
- Access tokens.
- Database credentials.

Development-agent transcripts are separate from runtime application logs.

---

# 29. Deployment Considerations

The take-home should prioritize local reproducibility.

Potential deployment components:

```text
Frontend → deployment platform
Backend  → deployment platform
Database → Supabase
LLM      → cloud provider or local Ollama
```

Local Ollama cannot generally be assumed to be available in a hosted deployment, so the local mode is primarily required for local demonstration.

The README should clearly distinguish:

- Local development.
- Cloud deployment.
- Ollama local execution.

---

# 30. Implementation Order

The recommended implementation order is:

```text
1. Repository setup
        ↓
2. Environment/configuration
        ↓
3. Database schema
        ↓
4. Transcript ingestion
        ↓
5. Vector retrieval
        ↓
6. FastAPI foundation
        ↓
7. LLM abstraction
        ↓
8. Application agent
        ↓
9. Transcript-search tool
        ↓
10. Ship30for30 skill
        ↓
11. Artifact generation
        ↓
12. Session/chat APIs
        ↓
13. Frontend
        ↓
14. Artifact Viewer
        ↓
15. LLM toggle
        ↓
16. Error handling
        ↓
17. Testing
        ↓
18. Documentation
        ↓
19. Demo
```

This order allows the core data and agent functionality to be validated before polishing the frontend.

---

# 31. Key Architectural Decisions

The following decisions are intentional:

### Decision 1 — Supabase PostgreSQL + pgvector

Use PostgreSQL as both the application's persistent database and transcript vector store rather than introducing a separate vector database.

### Decision 2 — Local transcript repository as source

The cloned Lenny repository is the source dataset.

It is not itself the application's database.

### Decision 3 — Agentic runtime

The application should use a real runtime agent with tools/skills instead of a collection of unrelated hard-coded endpoints.

### Decision 4 — Provider abstraction

Cloud and Ollama should use a common LLM abstraction.

### Decision 5 — Session isolation

Conversation state is persisted by session and loaded only for the active session.

### Decision 6 — In-app artifacts

Artifacts are rendered inside the application rather than requiring an external page.

### Decision 7 — Safe artifact rendering

Generated HTML is treated as untrusted content and isolated appropriately.

### Decision 8 — Complete development history

Development-agent transcripts are retained in full, including failures and corrections, with only actual secrets redacted.

### Decision 9 — Avoid unnecessary complexity

The implementation should satisfy the assignment without introducing unnecessary microservices, custom model training, or production infrastructure that does not improve the take-home.

---

# 32. Architecture Validation Checklist

Before implementation is considered complete, verify:

## Data

- [ ] Lenny repository path is configurable.
- [ ] Transcript discovery works.
- [ ] Frontmatter parsing works.
- [ ] Chunking works.
- [ ] Embeddings work.
- [ ] pgvector storage works.
- [ ] Similarity search works.

## Backend

- [ ] FastAPI starts.
- [ ] Database connection works.
- [ ] Sessions work.
- [ ] Messages persist.
- [ ] Chat endpoint works.
- [ ] Error responses are handled.

## Agent

- [ ] Approved application-agent integration is implemented.
- [ ] Transcript tool works.
- [ ] Ship30for30 skill works.
- [ ] Artifact tool works.
- [ ] Multiple skills can be combined.

## LLM

- [ ] Cloud mode works.
- [ ] Ollama mode works.
- [ ] Toggle works.
- [ ] Provider errors are handled.

## Frontend

- [ ] New chat works.
- [ ] Session list works.
- [ ] Chat works.
- [ ] Loading state works.
- [ ] Error state works.
- [ ] Artifact Viewer works.
- [ ] LLM toggle works.

## Security

- [ ] No secrets committed.
- [ ] `.env.example` exists.
- [ ] Generated HTML is sandboxed.
- [ ] Logs do not expose secrets.

## Documentation

- [ ] `PRD.md`
- [ ] `architecture.md`
- [ ] `design.md`
- [ ] `README.md`
- [ ] Development-agent transcripts

---

# 33. Final Architecture

The final intended architecture is:

```text
┌───────────────────────────────────────────────────────────────┐
│                        USER                                   │
└──────────────────────────────┬────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│                     NEXT.JS FRONTEND                          │
│                                                               │
│  Session Sidebar   │   Chat Interface   │   Artifact Viewer  │
│                    │                    │                     │
│                    │   LLM Toggle       │                     │
└──────────────────────────────┬────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│                     FASTAPI BACKEND                           │
│                                                               │
│ Sessions │ Messages │ Chat │ Health │ Configuration           │
└──────────────────────────────┬────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────┐
│                    APPLICATION AGENT                          │
│                                                               │
│              Agentic Decision / Tool Selection                │
└───────────────┬───────────────────┬───────────────────┬───────┘
                │                   │                   │
                ▼                   ▼                   ▼
       ┌────────────────┐   ┌────────────────┐   ┌────────────────┐
       │ Transcript RAG │   │ Ship30for30    │   │ Artifact       │
       │                │   │ Skill          │   │ Generator      │
       └───────┬────────┘   └────────────────┘   └───────┬────────┘
               │                                         │
               ▼                                         ▼
       ┌────────────────┐                        ┌────────────────┐
       │ PostgreSQL     │                        │ Artifact       │
       │ + pgvector     │                        │ Viewer         │
       └────────────────┘                        └────────────────┘

                         ┌───────────────────┐
                         │   LLM Factory     │
                         └─────────┬─────────┘
                                   │
                         ┌─────────┴─────────┐
                         ▼                   ▼
                  ┌────────────┐      ┌────────────┐
                  │ Cloud LLM  │      │   Ollama   │
                  └────────────┘      └────────────┘
```

This architecture provides the required path from:

**User → Agent → Skills/RAG → LLM → Response/Artifact**

while keeping the implementation understandable, testable, and appropriate for the take-home assignment.


---

# 34. Helpful Resources & Tools

- **FastAPI:** [https://fastapi.tiangolo.com/](https://fastapi.tiangolo.com/)
- **Ollama (Local LLMs):** [https://ollama.com/](https://ollama.com/)
- **Anthropic Claude SDK:** [https://docs.anthropic.com/](https://docs.anthropic.com/)
- **Pi Coding Agent:** [https://pi.dev/](https://pi.dev/)
- **Supabase:** [https://supabase.com/](https://supabase.com/)
- **Railway:** [https://railway.com/](https://railway.com/)
- **Ship30for30 Concept:** [https://www.ship30for30.com/post/how-to-start-writing-online-the-ship-30-for-30-ultimate-guide](https://www.ship30for30.com/post/how-to-start-writing-online-the-ship-30-for-30-ultimate-guide)
- **Impeccable.style:** [https://impeccable.style/](https://impeccable.style/)
- **Lenny's Podcast Transcripts:** [https://github.com/ChatPRD/lennys-podcast-transcripts](https://github.com/ChatPRD/lennys-podcast-transcripts)
