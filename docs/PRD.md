# Product Requirements Document (PRD)

# The Lenny Growth Assistant

**Version:** 1.0  
**Status:** Final  
**Document:** `docs/PRD.md`

---

## 1. Product Overview

**The Lenny Growth Assistant** is a full-stack, agentic AI conversational web application that helps users explore product-management and growth insights from Lenny's Podcast transcripts.

The application combines:

- A conversational chat interface.
- An agentic backend.
- Lenny's Podcast transcript knowledge base.
- Retrieval-Augmented Generation (RAG).
- A Ship30for30 writing skill.
- Artifact generation for Markdown and HTML/CSS.
- An in-app Artifact Viewer.
- PostgreSQL persistence.
- Cloud and local LLM support.
- Local Ollama support for demonstration.
- Persistent, isolated chat sessions.
- Development-agent transcripts documenting the complete build process.

The application should demonstrate practical agentic AI engineering, backend/system design, full-stack implementation, prompt engineering, reliable retrieval, and a usable UI.

---

## 2. Problem Statement

Users often need practical product, growth, and startup advice but may not have time to search through long podcast transcripts manually.

The application should provide a conversational interface where users can ask questions and receive answers grounded in Lenny's Podcast transcript knowledge base.

The application should also demonstrate that an agent can identify when a request requires:

- Transcript-grounded Q&A.
- Ship30for30-style writing.
- Artifact generation.
- A combination of these capabilities.

---

## 3. Target User

The primary user is a person interested in:

- Product management.
- Product growth.
- Startups.
- Marketing and growth.
- Product strategy.
- Writing and content creation.

The application should be simple enough for a user to open it and immediately start a new conversation.

---

## 4. Goals

### 4.1 Primary Goals

1. Build a working full-stack conversational AI application.
2. Demonstrate an agentic architecture rather than a simple chatbot.
3. Ground product/growth Q&A in Lenny's Podcast transcripts.
4. Support persistent and isolated chat sessions.
5. Support both cloud LLMs and local Ollama models.
6. Provide an explicit LLM mode toggle.
7. Generate useful structured writing using the Ship30for30 skill.
8. Generate Markdown and HTML/CSS artifacts.
9. Render artifacts inside the application.
10. Persist application conversations and metadata in PostgreSQL.
11. Document the architecture and UI/UX decisions.
12. Preserve complete development-agent transcripts from the coding process.

### 4.2 Demonstration Goals

The final application should demonstrate:

- Agentic routing/skill selection.
- RAG over a real transcript dataset.
- Local LLM execution using Ollama.
- Cloud LLM configuration.
- Database-backed sessions and messages.
- Artifact generation and rendering.
- Robust handling of failures.
- A clean user interface.
- A reproducible setup documented in the repository.

---

## 5. Scope

### 5.1 Conversational Chat

The application must provide a ChatGPT-like conversational experience.

Users must be able to:

- Start a new chat.
- Send messages.
- Receive responses.
- Continue an existing conversation.
- See previous sessions.
- Switch between sessions.
- Maintain independent context per session.

Each session must have its own conversation history and must not accidentally use messages from another session.

---

## 5.2 Lenny's Podcast Knowledge Base

The knowledge base must use the provided Lenny's Podcast transcript repository:

https://github.com/ChatPRD/lennys-podcast-transcripts

The repository will be cloned locally as the **source dataset** for the application's ingestion pipeline.

The ingestion pipeline should:

1. Read the locally cloned transcript repository.
2. Discover episode transcript files from the `episodes/` directory.
3. Parse transcript metadata from the YAML frontmatter.
4. Extract transcript content.
5. Split transcripts into searchable chunks.
6. Generate embeddings for the chunks.
7. Store chunks, metadata, and embeddings in PostgreSQL using `pgvector`.
8. Make the stored chunks available for semantic retrieval by the RAG system.

The local repository clone is the source dataset.

Supabase/PostgreSQL is the persistent storage and retrieval layer for the processed transcript data.

The ingestion process should be repeatable so the knowledge base can be rebuilt when the transcript dataset is updated.

The exact chunk size, overlap, embedding model, retrieval count, and vector-index configuration should be documented in `architecture.md` rather than treated as arbitrary product requirements.

---

## 5.3 Transcript-Grounded Q&A

The application must provide a transcript-grounded Q&A capability.

When a user asks a product/growth question that should be answered using Lenny's Podcast knowledge, the agent should:

1. Identify that transcript retrieval is required.
2. Retrieve relevant transcript chunks.
3. Provide the retrieved information to the response-generation step.
4. Generate an answer grounded in the retrieved transcript content.

The application should not present unsupported information as though it came from the Lenny transcript knowledge base.

If sufficient relevant transcript evidence cannot be found, the application should communicate that limitation instead of fabricating transcript-derived claims.

Where practical, the response should expose useful source context such as episode title or other transcript metadata.

---

## 5.4 Agentic Skill Selection

The application must use an agentic approach to determine which capability or skill is needed for a user request.

The agent should be able to decide whether to:

- Retrieve Lenny transcript knowledge.
- Use the Ship30for30 writing skill.
- Generate an artifact.
- Combine multiple capabilities when the request requires it.
- Respond directly when no specialized tool/skill is necessary.

The implementation should avoid making every request follow the same fixed pipeline.

The application agent must use one of the assignment-approved approaches:

- Anthropic Claude SDK / Agent SDK, or
- Pi Coding Agent.

The development coding agent used to build the application is separate from the application agent.

---

## 5.5 Ship30for30 Skill

The application must provide a Ship30for30 writing capability based on:

https://www.ship30for30.com/post/how-to-start-writing-online-the-ship-30-for-30-ultimate-guide

When requested, the skill should generate an approximately **1250-word essay**.

The output should include:

- A strong opening hook.
- Clear structure.
- Strong formatting.
- Short, readable sections.
- Bullets where useful.
- Bold emphasis where useful.
- High skimmability.
- A clear takeaway or conclusion.

The skill should use the conversation context when appropriate.

The generated content should not falsely imply that it is directly quoted from Lenny's transcripts unless transcript retrieval was actually used.

---

## 5.6 Artifact Generation

The application must be able to generate artifacts based on the conversation context.

Supported artifact types must include:

### Markdown

Examples:

- Notes.
- Structured documents.
- Summaries.
- Plans.
- Guides.

### HTML/CSS

Examples:

- Landing pages.
- Product mockups.
- Simple dashboards.
- Styled documents.
- UI prototypes.

The agent should return complete artifact content suitable for rendering.

---

## 5.7 Artifact Viewer

Generated artifacts must be viewable inside the application.

The UI should support a side-by-side experience such as:

```text
+-------------------------+-----------------------------+
|                         |                             |
|       Chat              |       Artifact Viewer       |
|                         |                             |
|  User / Agent messages  |  Rendered Markdown / HTML   |
|                         |                             |
+-------------------------+-----------------------------+
```

The Artifact Viewer must:

- Render Markdown as formatted content.
- Render HTML/CSS as an actual UI/page where appropriate.
- Display the artifact inside the application.
- Allow the user to continue chatting while viewing the artifact.
- Avoid requiring an external redirect simply to view the generated artifact.

The implementation must safely handle generated HTML/CSS and must not unnecessarily expose the host application to arbitrary unsafe execution.

---

## 5.8 Cloud LLM Support

The application must support a cloud LLM configuration.

The exact provider/model should be configurable through environment variables or application configuration rather than hard-coded into the product requirements.

API keys must be loaded securely through environment variables or equivalent secret configuration.

Secrets must never be committed to the repository.

---

## 5.9 Local LLM Support

The application must support local LLM execution through **Ollama**.

Ollama support is mandatory because the final demonstration must be possible using a local LLM.

The application should provide a clear configuration for:

- Ollama base URL.
- Ollama model.
- Local/cloud mode.

The README must explain how to install/configure Ollama and run the required model.

---

## 5.10 LLM Toggle

The application must provide an explicit mechanism for selecting the LLM mode.

At minimum:

```text
Cloud LLM  <---->  Local Ollama
```

The selected mode must determine which LLM provider is used by the application's agent.

The implementation should isolate provider-specific logic behind a common LLM interface/factory so the agent does not need to be rewritten when the provider changes.

---

## 5.11 Database and Session Persistence

The application must use PostgreSQL through either:

- Supabase, or
- Railway.

The database must persist application data required for the conversational experience.

At minimum, the data model should support:

- Users/user metadata where applicable.
- Sessions.
- Messages.
- Transcript chunks.
- Embeddings/vector data required for retrieval.

Each session must have a unique session identifier.

Messages must be associated with their corresponding session.

The exact database schema, relationships, indexes, and SQL/vector configuration must be documented in `architecture.md`.

---

# 6. Backend Requirements

The backend must use **FastAPI**.

The backend should provide APIs for:

- Creating/listing/selecting sessions.
- Sending chat messages.
- Retrieving conversation history.
- LLM configuration/mode selection where required.
- Artifact generation or artifact delivery where appropriate.
- Health/status checks where useful.

The exact endpoint definitions should be documented in `architecture.md`.

The backend must keep application logic separated into appropriate modules for:

- API/routes.
- Agent orchestration.
- Skills/tools.
- LLM providers.
- RAG/retrieval.
- Database access.
- Session/message management.
- Artifact handling.

---

# 7. Agent Integration

The submitted application must contain a real application-level agent.

The application agent is responsible for:

- Understanding the user's request.
- Selecting appropriate capabilities/tools/skills.
- Retrieving transcript context when required.
- Generating grounded responses.
- Calling the Ship30for30 skill when required.
- Calling artifact generation when required.
- Combining capabilities when required.
- Handling tool failures and insufficient retrieval results.

The agent architecture must be documented.

The architecture documentation must explain:

- Agent entry point.
- Available skills/tools.
- Routing/decision mechanism.
- Tool inputs and outputs.
- RAG interaction.
- LLM provider abstraction.
- Error handling.
- Session context handling.

---

# 8. Functional Requirements

## FR1 — New Session

The user can create a new chat session.

## FR2 — Session Isolation

Each session maintains independent conversation context.

## FR3 — Session Persistence

Sessions remain available after page reload/restart when the database is available.

## FR4 — Message Persistence

User and assistant messages are persisted in PostgreSQL.

## FR5 — Transcript Ingestion

The application can ingest the locally cloned Lenny transcript repository.

## FR6 — Semantic Retrieval

The application can retrieve relevant transcript chunks using vector similarity search.

## FR7 — Grounded Q&A

The application can answer product/growth questions using retrieved transcript context.

## FR8 — Insufficient Evidence Handling

The application does not fabricate transcript-derived claims when relevant evidence is unavailable.

## FR9 — Agentic Routing

The application agent determines which capability/skill/tool is appropriate for the request.

## FR10 — Ship30for30

The application can generate an approximately 1250-word Ship30for30-style essay.

## FR11 — Markdown Artifact

The application can generate a Markdown artifact.

## FR12 — HTML/CSS Artifact

The application can generate a complete HTML/CSS artifact.

## FR13 — Artifact Rendering

Artifacts are rendered inside the application.

## FR14 — Cloud LLM

The application can use a configured cloud LLM.

## FR15 — Local Ollama

The application can use a configured local Ollama model.

## FR16 — LLM Toggle

The user can switch between supported LLM modes.

## FR17 — Error Handling

The system handles failures such as:

- Missing/invalid cloud API key.
- Cloud provider failure.
- Ollama unavailable.
- Ollama timeout.
- Database connection failure.
- Database timeout.
- Embedding failure.
- No relevant transcript results.
- Agent/tool failure.
- Invalid artifact output.

The frontend should show a clear, user-readable error instead of crashing or remaining indefinitely stuck.

## FR18 — Conversation Context

The agent receives the appropriate context from the current session without accidentally mixing sessions.

## FR19 — Artifact + Chat Context

Artifact generation can use relevant information from the current conversation.

## FR20 — Transcript Metadata

Retrieved transcript information should retain useful metadata such as episode title and guest where available.

## FR21 — Repeatable Ingestion

The transcript ingestion process can be rerun when the source dataset changes.

## FR22 — Environment Configuration

Provider credentials, database configuration, transcript path, Ollama configuration, and other environment-specific values must be configurable without modifying application source code.

## FR23 — Safe Artifact Handling

Generated HTML/CSS must be rendered using an approach appropriate for untrusted generated content.

## FR24 — Documentation

The repository contains the required PRD, architecture documentation, UI/UX design documentation, README, and development-agent transcripts.

## FR25 — Complete Development-Agent Transcript Archive

The repository must include the complete development-agent transcripts produced during the coding/build process.

No development-agent interactions should be filtered, selectively omitted, or replaced with a summary for submission.

The transcript archive should include:

- Initial development prompts.
- Coding tasks.
- Implementation attempts.
- Successful outputs.
- Failed attempts.
- Errors.
- Debugging.
- Corrections.
- Retries.
- Design/implementation decisions.
- Relevant resulting changes.

Secrets must never be included in the transcript archive.

---

# 9. Non-Functional Requirements

## 9.1 Reliability

The application should fail gracefully when external services or infrastructure are unavailable.

## 9.2 Maintainability

The codebase should use clear modules and separation of concerns.

## 9.3 Configuration

Environment-specific configuration should not be hard-coded.

## 9.4 Security

The application must:

- Keep API keys and secrets out of source control.
- Provide `.env.example`.
- Avoid logging secrets.
- Handle generated HTML safely.
- Validate external/tool inputs where appropriate.

## 9.5 Usability

A first-time user should be able to:

1. Open the application.
2. Start a chat.
3. Ask a question.
4. Receive a response.
5. Create another session.
6. Generate an artifact.
7. View the artifact without leaving the application.

## 9.6 Reproducibility

Another developer should be able to understand how to:

- Install dependencies.
- Configure environment variables.
- Configure PostgreSQL/Supabase.
- Run transcript ingestion.
- Configure Ollama.
- Start the backend.
- Start the frontend.
- Run the application locally.

The README must document these steps.

---

# 10. Architecture Requirements

A separate `architecture.md` document must describe the technical architecture.

It must include:

### 10.1 System Architecture

The major components and their relationships.

### 10.2 Frontend Architecture

Pages/components and communication with the FastAPI backend.

### 10.3 Backend Architecture

FastAPI routes, services, agent layer, skills, tools, database layer, and LLM abstraction.

### 10.4 Database Schema

At minimum:

- Users/user metadata.
- Sessions.
- Messages.
- Transcript chunks.
- Embeddings/vector data.

### 10.5 API Endpoints

Document:

- HTTP method.
- Path.
- Request.
- Response.
- Authentication/requirements if applicable.
- Error responses.

### 10.6 Agentic Routing

Explain how the application agent determines whether to:

- Retrieve transcripts.
- Use Ship30for30.
- Generate an artifact.
- Combine skills.
- Answer directly.

### 10.7 LLM Abstraction

Explain:

- Cloud provider integration.
- Ollama integration.
- Provider configuration.
- LLM mode toggle.
- Common interface/factory.

### 10.8 RAG Architecture

Explain:

- Transcript source.
- Parsing.
- Chunking.
- Embedding.
- Storage.
- Vector indexing.
- Similarity search.
- Retrieval count.
- Passing retrieved context to the agent.

### 10.9 Transcript Ingestion Architecture

Explain:

- Location/configuration of the local transcript repository.
- Transcript discovery.
- YAML frontmatter parsing.
- Transcript extraction.
- Chunking strategy.
- Embedding model.
- PostgreSQL/pgvector schema.
- Vector index configuration.
- Insertion/upsert process.
- Similarity-search process.
- How retrieved chunks are passed to the agent.

### 10.10 Error Architecture

Explain how failures from:

- Cloud LLMs.
- Ollama.
- PostgreSQL.
- Embeddings.
- Retrieval.
- Agent tools.
- Artifact rendering.

are detected and surfaced.

### 10.11 Performance Decisions

Document important implementation decisions such as:

- Chunk size and overlap.
- Embedding model.
- Vector index.
- Similarity metric.
- Retrieval `top-k`.
- Caching, if used.
- Response streaming, if implemented.

Exact technical choices belong here rather than being unnecessarily hard-coded into the PRD.

---

# 11. UI/UX Requirements

A separate `design.md` document must describe the UI/UX design.

The UI should include:

## 11.1 Sidebar

The sidebar should allow users to:

- Create a new chat.
- View existing sessions.
- Select a session.
- Clearly understand which session is active.

## 11.2 Chat Area

The chat area should provide:

- User messages.
- Assistant messages.
- Input area.
- Clear loading state.
- Error state.
- Appropriate response formatting.

## 11.3 Artifact Viewer

The Artifact Viewer should appear alongside or in an integrated panel with the chat.

It should:

- Render Markdown.
- Render HTML/CSS artifacts.
- Remain usable while the conversation continues.
- Clearly indicate when an artifact has been generated.

## 11.4 LLM Mode

The UI should clearly indicate the currently selected LLM mode:

- Cloud.
- Local Ollama.

## 11.5 Design Quality

The interface should be:

- Clean.
- Consistent.
- Responsive where practical.
- Easy to understand.
- Appropriate for a modern AI productivity application.

---

# 12. Development-Agent Transcripts

Complete development-agent transcripts are a mandatory submission artifact.

These transcripts document the process used to build the application with the coding/development agent.

They are separate from the application's end-user chat history.

## 12.1 No Filtering

The development transcript archive must not selectively remove interactions because they appear:

- Simple.
- Unimportant.
- Repetitive.
- Incorrect.
- Failed.
- Embarrassing.
- Unsuccessful.

The goal is to preserve the complete development process.

## 12.2 Failures and Corrections

The archive must preserve failed attempts and subsequent corrections.

This should make it possible for a reviewer to understand:

```text
Task
  ↓
Attempt
  ↓
Error / Failure
  ↓
Debugging
  ↓
Correction
  ↓
Successful Result
```

## 12.3 Organization

The transcripts may be organized into clearly named files/folders such as:

```text
agent-transcripts/
├── 001-project-setup.md
├── 002-database-and-ingestion.md
├── 003-fastapi-backend.md
├── 004-agent-and-skills.md
├── 005-rag.md
├── 006-frontend.md
├── 007-artifacts.md
├── 008-testing.md
└── ...
```

The exact organization can be decided during implementation.

## 12.4 Secret Protection

Complete development transcripts must be preserved, but secrets must not be exposed.

The archive must never contain:

- API keys.
- Passwords.
- Database credentials.
- Access tokens.
- Private secrets.

If a development-agent transcript contains a secret, the secret must be removed/replaced before committing the transcript.

This is the only required redaction.

---

# 13. Testing Requirements

The application must be tested locally before submission.

Testing should cover at least:

### Chat

- New session.
- Multiple sessions.
- Session switching.
- Page reload.
- Message persistence.

### RAG

- Transcript ingestion.
- Relevant transcript retrieval.
- Grounded answer generation.
- Insufficient evidence handling.

### Ship30for30

- Skill invocation.
- Approximately 1250-word output.
- Formatting.
- Hook.
- Takeaway.

### Artifacts

- Markdown generation.
- HTML/CSS generation.
- Artifact rendering.
- Chat + artifact interaction.
- Safe rendering behavior.

### LLM Providers

- Cloud LLM.
- Local Ollama.
- LLM mode switching.

### Failure Cases

- Missing API key.
- Invalid API key.
- Ollama unavailable.
- Ollama timeout.
- Database unavailable.
- Retrieval failure.
- Agent/tool failure.
- Invalid artifact output.

### Regression Testing

Previously working features should be retested after major changes.

---

# 14. Submission Deliverables

The public GitHub repository must contain:

1. Working application source code.
2. `docs/PRD.md`
3. `docs/architecture.md`
4. `docs/design.md`
5. Development-agent transcript archive.
6. `README.md`
7. `.env.example`
8. Database/ingestion scripts required to reproduce the knowledge base.
9. Tests where applicable.
10. Any required configuration/setup files.

---

# 15. README Requirements

The README must contain:

## 15.1 Project Overview

Explain what the application does.

## 15.2 Features

List the major capabilities.

## 15.3 Architecture Overview

Provide a concise overview and link to `architecture.md`.

## 15.4 Prerequisites

Document required software/services such as:

- Python.
- Node.js.
- PostgreSQL/Supabase or Railway.
- Ollama.
- Required Ollama model.

## 15.5 Installation

Explain how to install frontend/backend dependencies.

## 15.6 Environment Variables

Document all required environment variables.

Provide `.env.example`.

Never commit real secrets.

## 15.7 Transcript Dataset

Explain:

- Where the Lenny transcript repository should be cloned.
- How the local path is configured.
- How ingestion is executed.
- How the transcript data reaches PostgreSQL/pgvector.

## 15.8 Database Setup

Explain how to configure PostgreSQL/Supabase and create the required schema/vector support.

## 15.9 Ollama Setup

Explain how to:

1. Install Ollama.
2. Pull the required model.
3. Start Ollama.
4. Configure the application.
5. Select local mode.

## 15.10 Running the Application

Document the commands needed to start:

- Backend.
- Frontend.
- Any required services.

## 15.11 Testing

Explain how to run the test suite and/or validation commands.

## 15.12 Architecture and Design

Link to:

- `docs/architecture.md`
- `docs/design.md`
- `docs/PRD.md`

## 15.13 Development-Agent Transcripts

Explain where the complete development-agent transcripts are stored.

---

# 16. Security Requirements

The project must follow basic application security practices.

### Secrets

Never commit:

- API keys.
- Passwords.
- Database credentials.
- Access tokens.

### Environment Configuration

Use environment variables or equivalent configuration for secrets and deployment-specific values.

### Logs

Logs must not expose secrets.

Development-agent transcripts must preserve the development process while removing only actual secrets.

### Generated HTML

Generated HTML/CSS should be rendered in a controlled/sandboxed context appropriate to the implementation.

### Input Validation

Backend endpoints and tool inputs should validate expected data.

---

# 17. Acceptance Criteria

The project is considered functionally complete when all of the following are demonstrated:

### Chat

- User can create a new session.
- User can switch between sessions.
- Session context remains isolated.
- Messages persist in PostgreSQL.

### Knowledge Base

- Local Lenny transcript repository is ingested.
- Transcript metadata is retained.
- Chunks and embeddings are stored.
- Semantic retrieval works.

### Agent

- Application uses the required approved agent integration.
- Agent can select appropriate skills/tools.
- Agent can combine capabilities when needed.

### Q&A

- Product/growth questions can be answered using retrieved transcript context.
- Unsupported transcript claims are not fabricated.

### Ship30for30

- User can request the writing skill.
- Output is approximately 1250 words.
- Output has a strong hook, formatting, skimmability, and takeaway.

### Artifacts

- Markdown artifacts can be generated.
- HTML/CSS artifacts can be generated.
- Artifacts render inside the application.
- User does not need to leave the application to view them.

### LLMs

- Cloud mode works with configured credentials.
- Local Ollama mode works.
- User can switch modes.

### Reliability

- Expected infrastructure/provider failures are handled gracefully.

### Documentation

- PRD exists.
- Architecture documentation exists.
- UI/UX design documentation exists.
- README contains complete setup instructions.
- `.env.example` exists.
- Complete development-agent transcripts are included.

---

# 18. Demo Requirements

A **2–3 minute YouTube demonstration** must be provided.

The demonstration should show the working application and should use the required local Ollama setup where applicable.

The demonstration should include the developer's camera.

A concise demonstration flow can include:

1. Open the application.
2. Create a new chat.
3. Ask a Lenny/product-growth question.
4. Show transcript-grounded output.
5. Ask for a Ship30for30-style article.
6. Generate an artifact.
7. Show the Artifact Viewer.
8. Switch between cloud/local LLM mode if configured.
9. Briefly show the agentic workflow or architecture.

The video should be free-form and focused on demonstrating the working product.

---

# 19. Development Process

The project should be developed using a structured software-building process:

```text
PRD
 ↓
Architecture
 ↓
UI/UX Design
 ↓
Implementation
 ↓
Ingestion / RAG
 ↓
Agent + Skills
 ↓
Frontend
 ↓
Testing
 ↓
Documentation
 ↓
Public GitHub
 ↓
Demo
```

The development coding agent may be used to implement the application.

The development coding agent and the application's runtime agent are separate concerns.

For example:

```text
Development phase

Developer
   ↓
Qoder / coding agent
   ↓
Application source code
   ↓
agent-transcripts/


Runtime

User
   ↓
Lenny Growth Assistant
   ↓
Application Agent
   ↓
Skills / Tools / RAG
   ↓
LLM
   ↓
Response / Artifact
```

---

# 20. Development Agent vs Application Agent

This distinction must remain explicit throughout implementation.

## Development Agent

The development agent is the coding assistant used to build the project.

Its responsibilities include:

- Writing code.
- Modifying files.
- Debugging.
- Running tests.
- Helping implement architecture.
- Iterating on the application.

Its complete development interaction history must be preserved in the repository.

## Application Agent

The application agent is the agent that exists inside the submitted Lenny Growth Assistant.

It is responsible for:

- Understanding user requests.
- Selecting skills/tools.
- Retrieving Lenny transcript information.
- Generating responses.
- Generating Ship30for30 content.
- Generating artifacts.
- Combining capabilities.

The application agent must use the assignment-approved Claude SDK/Agent SDK or Pi Coding Agent integration.

---

# 21. Final End-to-End Product Flow

The intended runtime flow is:

```text
                         ┌──────────────────────┐
                         │        User          │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │    Chat Interface    │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   FastAPI Backend    │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   Application Agent │
                         └──────────┬───────────┘
                                    │
                    ┌───────────────┼────────────────┐
                    │               │                │
                    ▼               ▼                ▼
              Transcript        Ship30for30      Artifact
               Retrieval           Skill          Generator
                    │               │                │
                    ▼               │                ▼
             PostgreSQL +          │          Artifact Viewer
                pgvector           │
                    │               │
                    └───────┬───────┘
                            ▼
                     LLM Abstraction
                       /          \
                      /            \
                     ▼              ▼
               Cloud LLM         Ollama
```

The exact technical architecture, database schema, endpoint definitions, routing mechanism, retrieval implementation, vector index, embedding configuration, and provider implementation must be documented in `architecture.md`.

---

# 22. Out of Scope

To keep the take-home focused, the following are not required unless needed by the implementation:

- Multi-user enterprise administration.
- Complex authentication/authorization.
- Billing/subscriptions.
- Mobile applications.
- Production-scale distributed infrastructure.
- Fine-tuning a custom LLM.
- Training a custom embedding model.
- Advanced analytics dashboards.
- Unnecessary microservices.

The goal is a complete, understandable, working take-home rather than an unnecessarily large production platform.

---

# 23. Success Definition

The project succeeds when a reviewer can:

1. Clone the public repository.
2. Follow the README.
3. Configure the required environment variables.
4. Configure PostgreSQL/Supabase or Railway.
5. Ingest the local Lenny transcript dataset.
6. Configure Ollama for local execution.
7. Start the application.
8. Create and use independent chat sessions.
9. Ask transcript-grounded product/growth questions.
10. Generate a Ship30for30-style article.
11. Generate Markdown or HTML/CSS artifacts.
12. View artifacts inside the application.
13. Switch between supported LLM modes.
14. Understand the architecture from the documentation.
15. Review the complete development-agent transcript archive and see both successful and unsuccessful implementation attempts.

The final result should demonstrate a practical, agentic, full-stack AI application with grounded knowledge retrieval, multiple skills, local LLM support, persistent sessions, artifact generation, clear architecture, and transparent development history.


---

# 24. Helpful Resources & Tools

- **Lenny's Podcast Transcripts:** [https://github.com/ChatPRD/lennys-podcast-transcripts](https://github.com/ChatPRD/lennys-podcast-transcripts)
- **Ship30for30 Concept:** [https://www.ship30for30.com/post/how-to-start-writing-online-the-ship-30-for-30-ultimate-guide](https://www.ship30for30.com/post/how-to-start-writing-online-the-ship-30-for-30-ultimate-guide)
- **Impeccable.style:** [https://impeccable.style/](https://impeccable.style/)
