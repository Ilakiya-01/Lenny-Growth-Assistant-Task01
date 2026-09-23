# Implementation Roadmap

This document defines the sequential implementation plan for The Lenny Growth Assistant.

The project will be implemented one phase at a time. The development agent must complete and verify the current phase before moving to the next phase.

The PRD, architecture, and design documents remain the source of truth for product requirements, technical architecture, and UI/UX decisions.

---

## Phase 1 — Foundation

### Goal

Establish the runnable project skeleton and core infrastructure without implementing AI/RAG/agent functionality.

### Scope

- Git repository structure and directory layout.
- FastAPI backend skeleton.
- Basic CORS configuration.
- Next.js frontend skeleton.
- Tailwind CSS setup where appropriate.
- Root `.env.example`.
- Backend configuration management.
- Supabase/PostgreSQL connection.
- Initial database migrations/schema.
- Users, sessions, and messages tables.
- Basic session management API endpoints.
- Basic frontend ↔ backend API connectivity.
- Development-agent transcript directory.
- Basic health/connectivity verification.

### Explicitly excluded

- Lenny transcript ingestion.
- Transcript chunking.
- Embedding generation.
- pgvector retrieval.
- Claude Agent SDK integration.
- Agentic routing.
- Ship30for30 skill.
- Artifact generation.
- Full chat experience.
- Ollama runtime integration.

### Completion criteria

- Backend starts successfully.
- Frontend starts successfully.
- Backend can connect to the configured database.
- Database schema/migrations execute successfully.
- A session can be created and persisted.
- Session messages can be persisted and retrieved.
- Frontend can communicate with the backend.
- No secrets are committed.
- Phase 1 development transcript is preserved.

---

## Phase 2 — Knowledge Base & Ingestion

### Goal

Build the Lenny transcript knowledge base and semantic retrieval foundation.

### Scope

- Discover transcripts from the configured local Lenny repository.
- Parse Markdown and YAML frontmatter.
- Extract transcript metadata and content.
- Normalize transcript text.
- Chunk transcripts.
- Generate embeddings.
- Store transcript chunks, metadata, and embeddings in PostgreSQL/pgvector.
- Configure vector similarity search.
- Implement transcript retrieval.
- Make ingestion repeatable.
- Add useful ingestion/retrieval tests.

### Completion criteria

- Lenny transcripts can be ingested successfully.
- Metadata is preserved.
- Embeddings are stored in pgvector.
- Semantic search returns relevant transcript chunks.
- Ingestion can be rerun safely.
- No secrets are stored in the knowledge base or logs.

---

## Phase 3 — Application Agent & LLM Provider Layer

### Goal

Implement the runtime agent architecture and cloud/local LLM abstraction.

### Scope

- Integrate the Anthropic Claude Agent SDK as the application's approved runtime agent.
- Define the application agent responsibilities.
- Implement agent/session context handling.
- Implement agent tool interfaces.
- Implement the LLM/provider abstraction required by the architecture.
- Implement Cloud/Anthropic provider configuration.
- Implement Ollama/local provider configuration.
- Implement the LLM mode selection mechanism.
- Define high-level agent activity/status events.
- Implement graceful provider and agent failures.

### Important constraint

The Claude Agent SDK integration and Ollama integration must follow the current supported APIs and documented capabilities.

Do not assume that Ollama can simply be substituted into the Claude Agent SDK. The implementation must preserve the assignment requirement for the approved Anthropic agent integration while also supporting the required local Ollama mode.

### Completion criteria

- Application agent can be invoked from the backend.
- Session context is isolated correctly.
- Cloud provider configuration works.
- Ollama provider configuration works.
- Provider selection is explicit.
- Agent/tool failures are handled cleanly.
- No chain-of-thought is exposed to the user.

---

## Phase 4 — Core Skills & Tools

### Goal

Implement the specialized capabilities required by the assignment.

### Scope

### Transcript-grounded Q&A

- Connect the agent to the transcript search tool.
- Retrieve relevant Lenny transcript evidence.
- Require product/growth answers to be grounded in retrieved evidence.
- Handle insufficient evidence explicitly.
- Preserve useful transcript metadata.

### Ship30for30

- Implement the Ship30for30 writing capability.
- Target approximately 1250 words.
- Strong opening hook.
- Headings and readable structure.
- Bold emphasis and bullets where appropriate.
- Clear takeaway.
- Include word-count/reading-time information where appropriate.

### Artifact generation

- Generate Markdown artifacts.
- Generate HTML/CSS artifacts.
- Return structured artifact data.
- Validate artifact output.
- Prepare artifacts for safe in-application rendering.

### Skill composition

The agent should be able to combine capabilities when a request requires multiple skills/tools.

### Completion criteria

- Transcript Q&A works with retrieved evidence.
- Unsupported claims are not presented as Lenny's advice.
- Ship30for30 output meets the required structure and approximate length.
- Markdown artifacts work.
- HTML/CSS artifacts work.
- Combined skill requests work where appropriate.

---

## Phase 5 — Frontend Workspace & Artifact Viewer

### Goal

Implement the complete user-facing AI workspace described in `design.md`.

### Scope

- Chat interface.
- Message rendering.
- Session sidebar.
- New Chat.
- Session switching.
- Persistent conversation loading.
- Composer/input.
- Loading and streaming states.
- LLM mode indicator/toggle.
- High-level agent activity indicators.
- Artifact Viewer.
- Markdown rendering.
- HTML/CSS preview in a controlled/sandboxed context.
- Preview / Code view.
- Ship30for30 word-count/reading-time display.
- Empty states.
- Error states.
- Desktop-first responsive behavior.
- Accessibility basics.

### Completion criteria

- User can create and switch sessions.
- Conversations persist across refreshes.
- Chat responses render correctly.
- Agent activity is understandable without exposing chain-of-thought.
- Artifacts can be viewed inside the application.
- Preview and Code views work.
- Cloud/Ollama mode is visible.
- UI follows `design.md`.

---

## Phase 6 — Integration & Verification

### Goal

Verify the complete system end to end.

### Scope

- End-to-end chat flow.
- Session isolation.
- Transcript retrieval.
- Grounded Q&A.
- Ship30for30 generation.
- Artifact generation and rendering.
- Cloud LLM testing.
- Local Ollama testing.
- Provider switching.
- Database failure handling.
- Ollama unavailable/timeout handling.
- Retrieval failure handling.
- Agent/tool failure handling.
- Artifact validation/rendering failures.
- Streaming/progressive response behavior.
- Regression testing after major changes.
- Security review.
- Secret/log review.

### Required local verification

The application must be tested locally using:

- The configured PostgreSQL/Supabase database.
- The local Lenny transcript dataset.
- A configured cloud API key where applicable.
- Local Ollama.
- The selected Ollama model.

### Completion criteria

The complete application can be run locally and the primary assignment workflows can be demonstrated successfully.

---

## Phase 7 — Documentation & Submission

### Goal

Prepare the repository for evaluation and public release.

### Scope

- Final README.
- Setup instructions.
- Environment-variable documentation.
- Database setup instructions.
- Lenny transcript ingestion instructions.
- Ollama setup instructions.
- Cloud provider setup instructions.
- Architecture documentation verification.
- Design documentation verification.
- PRD verification.
- Development-agent transcript organization.
- Remove actual secrets from committed files/transcripts.
- Final code cleanup.
- Public GitHub repository.
- 2–3 minute YouTube demonstration.

### Completion criteria

A reviewer can clone the repository, follow the README, configure the required services, run the application, understand the architecture, and reproduce the primary workflows.

---

# Development Rules

### Naming Convention

a.) Use `agent-transcripts/` consistently for all development-agent logs.

b.) Do not use `transcripts/` for development-agent logs, as the project also uses Lenny podcast transcripts as its knowledge-base dataset.

1. Read `PRD.md`, `architecture.md`, `design.md`, and this roadmap before beginning a phase.
2. Implement only the current phase.
3. Do not silently implement later-phase functionality.
4. If a later-phase dependency is required, create only the minimum interface/placeholder needed by the current phase.
5. Follow the architecture and design documents rather than inventing a conflicting architecture.
6. Prefer simple, maintainable implementation over unnecessary abstraction.
7. Verify the current phase before declaring it complete.
8. Preserve complete development-agent transcripts, including failures and corrections.
9. Never commit secrets.
10. Update documentation when an implementation decision materially changes the documented architecture.
