import type { Artifact, ChatResponse, Message, Session, Source } from "@/types";

export const MARKDOWN_ARTIFACT: Artifact = {
  type: "markdown",
  title: "Product-market fit essay",
  content: "# Product-market fit\n\nPull, not push.",
};

export const HTML_ARTIFACT: Artifact = {
  type: "html_css",
  title: "Landing page",
  content: '<section class="hero"><h1>Ship it</h1></section>',
  css: ".hero { padding: 2rem; }",
};

export function session(id: string, title: string): Session {
  return {
    id,
    title,
    created_at: "2026-09-22T09:00:00Z",
    updated_at: "2026-09-22T09:30:00Z",
  };
}

export function message(
  id: string,
  role: "user" | "assistant",
  content: string,
  extra: Partial<Message> = {},
): Message {
  return {
    id,
    session_id: "s1",
    role,
    content,
    artifact: null,
    created_at: "2026-09-22T09:31:00Z",
    ...extra,
  };
}

export const SOURCES: Source[] = [
  {
    episode_id: "ep-001",
    title: "Finding product-market fit",
    guest: "Ada Lovelace",
    publish_date: "2024-01-15",
    youtube_url: "https://www.youtube.com/watch?v=example",
    chunk_index: 4,
    similarity: 0.82,
    excerpt: "Pull versus push is the clearest signal.",
  },
];

export function chatResponse(overrides: Partial<ChatResponse> = {}): ChatResponse {
  return {
    session_id: "s1",
    user_message: message("m1", "user", "What does Lenny say about product-market fit?"),
    message: message("m2", "assistant", "**Pull, not push.** Look for organic demand."),
    artifact: null,
    sources: SOURCES,
    activity: [],
    llm_mode: "ollama",
    provider: "ollama",
    model: "qwen3:4b",
    intent: "grounded_qa",
    skills: ["grounded_qa"],
    metrics: { word_count: 12, evidence_count: 1 },
    ...overrides,
  };
}
