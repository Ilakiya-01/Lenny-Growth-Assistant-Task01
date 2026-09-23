# UI/UX Design Document: The Lenny Growth Assistant

**Document:** `design.md`  
**Purpose:** Define the visual system, interaction patterns, component behavior, and UX decisions for The Lenny Growth Assistant. The design is inspired by modern AI workspace paradigms such as Claude and applies principles from [Impeccable.style](https://impeccable.style/) while remaining implementation-focused.

---

## 1. Design Goals & Philosophy

The Lenny Growth Assistant should feel like a focused AI workspace for product managers, founders, and builders. Natural conversation is the primary interaction, while structured outputs such as Ship30for30 essays and generated artifacts remain easy to inspect and use.

### Core principles

- **Focus on content:** Typography, whitespace, hierarchy, and readable widths should support long-form essays and transcript-grounded answers.
- **Seamless context switching:** Users should be able to continue the conversation while inspecting an artifact.
- **System transparency:** Show the selected LLM mode and high-level agent activity without exposing hidden chain-of-thought.
- **Fast path to useful work:** New Chat, prompt entry, skill execution, and artifact viewing should require minimal interaction.
- **Strict grounding:** Product/growth answers must be based on retrieved Lenny transcript evidence. Unsupported claims must not be presented as Lenny's advice.
- **Progressive disclosure:** Secondary information such as source evidence and artifact controls should appear when useful without overwhelming the chat.
- **Accessible by default:** Contrast, keyboard navigation, focus states, readable typography, and responsive behavior should be considered during implementation.

### Impeccable.style inspiration

Use [Impeccable.style](https://impeccable.style/) as a design-quality reference rather than as a requirement for a particular color palette. Emphasize clear hierarchy, consistent spacing, restrained borders/shadows, strong typography, purposeful accents, readable density, consistent component states, responsive layouts, and accessibility. The review should focus on practical improvements that can be implemented without expanding the take-home unnecessarily.

---

## 2. Assignment-to-UX Mapping

| Assignment requirement | UX implementation |
|---|---|
| New Chat / sessions | Persistent left sidebar with New Chat and session history |
| Session-specific context | Each conversation is an isolated session |
| PostgreSQL persistence | Sessions and messages reload after refresh |
| Lenny transcript knowledge base | Agent activity and source/evidence presentation communicate transcript retrieval |
| Transcript-grounded Q&A | Answers are grounded in Lenny transcripts; insufficient evidence is explicitly stated |
| Ship30for30 skill | Skill-aware activity state and long-form formatted response |
| Artifact generation | Structured artifact response opens the Artifact Viewer |
| Artifact Viewer | Rendered Markdown/HTML/CSS appears inside the application |
| Cloud / Ollama | Visible LLM Mode toggle |
| Local Ollama demo | Ollama can be selected without changing the core workflow |
| Agentic architecture | High-level activity indicators show current capability/tool use |
| 2–3 minute demo | UI makes sessions, routing, Ollama, transcript retrieval, and artifacts easy to demonstrate |

---

## 3. Layout & Visual Hierarchy

The primary experience is a responsive multi-pane AI workspace.

### Desktop-first layout

The primary target for the take-home demo is a desktop viewport of approximately **1280px and above**. The layout should prioritize a polished, reliable desktop experience rather than expanding scope for elaborate mobile behavior.

1. **Sidebar** — approximately 240–280px wide; contains New Chat and session history and can collapse.
2. **Chat** — flexible central workspace; expands when no artifact is open and remains usable when the artifact panel is open.
3. **Artifact Viewer** — hidden by default; opens on the right and uses roughly 40% of the remaining workspace when active.

Use flexible CSS sizing rather than fixed percentage positioning. Basic responsive behavior should still be supported for narrower screens, but a full mobile navigation system is not a primary implementation target.

### Visual hierarchy

1. Conversation content
2. Current user input
3. Agent activity / progress
4. Generated artifact
5. Session navigation and secondary controls

Avoid decorative elements that compete with the conversation.

---

## 4. Typography & Visual Language

### Typography

Use a clean modern sans-serif, preferably **Inter** if available. Use **Fira Code** or **JetBrains Mono** for code, technical snippets, artifact source/code views, and developer metadata.

Long-form assistant content should have a readable maximum width. Ship30for30 essays should have comfortable line length, clear section spacing, headings, bullets, and emphasis.

### Color

Use a restrained neutral base with semantic accents for primary, success, warning, and error states. Final colors should be selected during implementation and checked for contrast. Do not rely on color alone to communicate state.

### Borders and shadows

Prefer subtle borders, light surface separation, minimal shadows, and consistent spacing. The interface should feel polished and calm rather than dashboard-heavy.

### Theme scope

A polished primary theme is sufficient for the take-home. Light/dark theme support may be added if it is inexpensive and does not delay core functionality. If implemented, both themes must preserve readable contrast, clear focus states, artifact readability, and semantic status distinctions.

---

## 5. Core Component Behavior

### 5.1 Sidebar

Contents:
- Application name/logo
- **New Chat** button
- Session history grouped optionally as Today / Previous 7 Days
- Session titles based on the first user message or a concise server-generated title

Behavior:
- New Chat creates a fresh session and clears active conversation context.
- Selecting a session loads persisted messages.
- Active session is visually distinct.
- Long titles are truncated.
- Desktop sidebar can collapse.
- Mobile sidebar becomes a drawer.

### 5.2 Chat

User messages should be visually distinct and aligned toward the right. Assistant messages remain integrated with the main content area. Long responses use readable typography and spacing. Markdown is rendered, and code blocks use monospace formatting.

The composer provides:
- multiline text input
- send action
- disabled/loading state
- clear focus state
- keyboard-friendly submission
- selected LLM mode visibility

### 5.3 LLM Mode Toggle

Provide a clear `Cloud | Ollama` control. The selected state must be obvious.

When Ollama is selected, show that the local model is active and provide a clear connection/error state if Ollama is unavailable. Allow switching to Cloud without changing the conversation workflow. Do not silently switch providers.

### 5.4 Agent Activity

Show high-level activity, not hidden reasoning. Examples:

- `Searching Lenny's Podcast`
- `Retrieved relevant insights`
- `Applying Ship30for30`
- `Generating artifact`
- `Preparing response`

These indicators demonstrate agentic behavior without exposing chain-of-thought.

### 5.5 Artifact Viewer

The Artifact Viewer is a core feature.

When the application agent generates an artifact, the backend should return structured artifact data separately from ordinary assistant text, for example:

```json
{
  "type": "html",
  "title": "Landing Page",
  "content": "<html>...</html>"
}
```

**The frontend should not parse `<artifact>` tags from streaming text.** Artifact delivery should use a structured event in the backend/frontend streaming protocol.

Behavior:
- Opens as a right-side panel.
- Displays artifact title and type.
- Shows rendered output as the primary view.
- Provides a **Preview | Code** toggle so the reviewer can inspect both the rendered result and the generated source.
- Keeps chat independently scrollable.
- Supports close/reopen.
- Provides Copy Code where applicable.
- Provides Fullscreen where useful.

HTML/CSS should be rendered in an isolated sandboxed iframe using `srcDoc` with appropriate restrictions. Generated HTML must not freely access the parent application's DOM or sensitive browser context.

Markdown artifacts should render as formatted content rather than raw Markdown syntax.

---

## 6. Skill-Aware UX

### 6.1 Transcript-grounded Q&A

Typical flow:

`User question → Agent → Transcript Search → Relevant evidence → Grounded answer`

When useful, show source metadata such as episode/guest, transcript title, and relevant evidence reference. Unsupported claims must not be presented as coming from Lenny's podcast.

### 6.2 Ship30for30 Skill

The writing behavior is based on the [Ship30for30 Ultimate Guide](https://www.ship30for30.com/post/how-to-start-writing-online-the-ship-30-for-30-ultimate-guide).

Typical flow:

`User request → Agent → Ship30for30 skill → Structured essay`

The essay UI should support a strong hook, clear headings, short paragraphs, bullets, bold emphasis, skimmability, and a clear takeaway. Target approximately 1,250 words. Where practical, show a compact metadata chip after generation, such as `1,240 words • 5 min read`, to make the output length easy to understand.

### 6.3 Artifact Generator

Typical flow:

`User request → Agent → Artifact generation → Structured artifact → Artifact Viewer`

Supported artifact types are Markdown and HTML/CSS. The artifact should feel like part of the workspace rather than an external page.

---

## 7. Interaction States

### 7.1 Empty state

Show a concise welcome area with prompt cards such as:
- **Ask Lenny:** “What does Lenny say about finding product-market fit?”
- **Write with Ship30for30:** “Write an essay about building products users love.”
- **Build an artifact:** “Create a simple landing page for a SaaS product.”

Prompt cards should populate the composer rather than automatically executing a request unless intentionally implemented otherwise.

### 7.2 Loading / Streaming

Use progressive responses where practical, preferably SSE. The UI should consume structured events rather than attempting to infer artifact boundaries from assistant text.

Recommended event flow:

```text
SSE
├── activity
│   └── high-level agent status
├── token
│   └── normal assistant text
├── artifact_ready
│   ├── type
│   ├── title
│   └── content
└── done
```

This allows normal assistant text to stream while an artifact can arrive as a separate structured payload when ready. Show subtle activity, communicate high-level activity, control the composer appropriately, and preserve already-rendered content when possible. Avoid fake progress percentages.

### 7.3 No sufficient transcript evidence

If the agent cannot retrieve enough relevant Lenny transcript evidence, it must not supplement the answer with unrelated general knowledge while presenting it as Lenny's advice.

Suggested response:

> “I couldn't find enough relevant information in Lenny's transcripts to answer this reliably.”

### 7.4 Ollama unavailable

Suggested message:

> “Cannot connect to Ollama. Make sure Ollama is running and the configured model is available, or switch to Cloud.”

Provide a clear recovery path.

### 7.5 Database / session failure

Show a concise inline error, preserve unsaved input where possible, provide Retry, and never imply successful persistence when it failed.

### 7.6 Agent / generation failure

Show a concise error, provide Retry, preserve the user's request, and avoid exposing API keys, internal prompts, stack traces, or hidden reasoning.

### 7.7 Artifact generation failure

Keep the assistant response visible, show that rendering failed, provide Retry or Copy Code where available, and avoid breaking the rest of the chat.

---

## 8. Responsive Behavior

The take-home is **desktop-first**, with 1280px+ as the primary design target.

### Desktop

`Sidebar | Chat | Artifact Viewer`, with the Artifact Viewer hidden until needed.

### Tablet / narrower desktop

The sidebar can become narrower or collapsible. The artifact panel can use reduced width or temporarily take focus while preserving access to the chat.

### Mobile

Provide basic responsive behavior such as stacked/flexible layout and usable scrolling. A full hamburger-driven mobile drawer or dedicated mobile navigation system is optional and should not be implemented at the expense of the core desktop experience.

The implementation priority is a polished, reliable desktop workflow for the assignment demo.

## 9. Accessibility

Support:
- keyboard navigation
- visible focus indicators
- semantic buttons and form controls
- accessible labels for icon-only controls
- sufficient color contrast
- non-color status indicators
- readable text sizing
- appropriate heading hierarchy
- screen-reader-friendly loading/error announcements where practical
- reduced-motion consideration

Interactive controls should have consistent hover, focus, active, disabled, and loading states.

---

## 10. Impeccable.style Design Review

Reference: [https://impeccable.style/](https://impeccable.style/)

Before considering the UI complete, review:

### Visual hierarchy
- Can the user immediately identify where to read and type?
- Are primary actions stronger than secondary controls?
- Is the Artifact Viewer clearly secondary until opened?

### Typography
- Are long answers comfortable to read?
- Are headings, body text, metadata, and code clearly differentiated?
- Are line lengths appropriate?

### Spacing
- Are related elements grouped consistently?
- Is there enough whitespace around long-form content?
- Are component paddings consistent?

### Contrast
- Are text and controls readable in supported themes?
- Are states distinguishable without relying only on color?

### Component consistency
- Do buttons, inputs, cards, toggles, badges, and panels share a consistent language?
- Are states handled consistently?

### Interaction quality
- Is feedback immediate when a request starts?
- Can the user tell whether Cloud or Ollama is active?
- Can the user understand whether the agent is retrieving transcripts, applying a skill, or generating an artifact?
- Can the user recover from errors without restarting the session?

### Information density
- Does the interface show enough information without becoming a dashboard?
- Is secondary metadata minimized until useful?

### Responsive behavior
- Does the main workflow remain usable on smaller screens?
- Does artifact viewing have a clear mobile equivalent?

### Accessibility
- Can the core workflow be completed using keyboard interaction?
- Are focus and disabled states obvious?
- Are contrast and semantic structure acceptable?

---

## 11. Suggested Component Structure

```text
frontend/
└── components/
    ├── Sidebar/
    │   ├── Sidebar.tsx
    │   ├── NewChatButton.tsx
    │   └── SessionList.tsx
    ├── Chat/
    │   ├── ChatPane.tsx
    │   ├── MessageList.tsx
    │   ├── Message.tsx
    │   ├── Composer.tsx
    │   └── AgentActivity.tsx
    ├── ArtifactViewer/
    │   ├── ArtifactViewer.tsx
    │   ├── ArtifactHeader.tsx
    │   ├── HtmlRenderer.tsx
    │   └── MarkdownRenderer.tsx
    └── LLMSelector/
        └── LLMModeToggle.tsx
```

The exact component structure may change during implementation if the resulting code remains clear and maintainable.

---

## 12. Helpful Resources & Tools

- **Impeccable.style:** [https://impeccable.style/](https://impeccable.style/)
- **Ship30for30 Ultimate Guide:** [https://www.ship30for30.com/post/how-to-start-writing-online-the-ship-30-for-30-ultimate-guide](https://www.ship30for30.com/post/how-to-start-writing-online-the-ship-30-for-30-ultimate-guide)

## 13. Design Validation Checklist

- [ ] New Chat is obvious and functional.
- [ ] Sessions are visually distinct and reloadable.
- [ ] Chat is the primary workspace.
- [ ] Cloud/Ollama mode is visible and understandable.
- [ ] Ollama failure has a clear recovery path.
- [ ] Agent activity is visible without exposing chain-of-thought.
- [ ] Transcript retrieval is represented in the UX.
- [ ] Unsupported Lenny claims are not presented as grounded answers.
- [ ] Ship30for30 output is readable and skimmable.
- [ ] Ship30for30 output can show word count / reading time when practical.
- [ ] Artifact generation opens the in-app Artifact Viewer.
- [ ] Artifact Viewer provides Preview | Code views.
- [ ] Markdown artifacts render as formatted content.
- [ ] HTML/CSS artifacts render safely in an isolated context.
- [ ] Chat and Artifact Viewer can be used together.
- [ ] Loading, error, empty, and success states are implemented.
- [ ] Streaming uses structured events when SSE is implemented.
- [ ] Mobile behavior is usable.
- [ ] Keyboard and accessibility states are considered.
- [ ] Impeccable.style review has been completed.
- [ ] UI matches the PRD and architecture documents.

---

## 14. Design-to-Implementation Guidance

Keep the design implementation-oriented. Do not introduce UI features requiring substantial backend work unless they directly support the assignment.

Preferred implementation order:

1. Workspace shell and responsive layout
2. Sidebar and session navigation
3. Chat and composer
4. LLM mode toggle
5. Agent activity states
6. Transcript-grounded response rendering
7. Ship30for30 output rendering
8. Structured Artifact Viewer
9. Loading/error/empty states
10. Accessibility and responsive refinement
11. Impeccable.style design review

Prioritize a polished, reliable end-to-end workflow over a large number of optional features.
