export type Session = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type MessageRole = "user" | "assistant" | "system";

/**
 * Structured artifact payload. It always travels beside the assistant text and
 * is never embedded in it, so the UI never parses tags out of a reply.
 */
export type Artifact = {
  type: string;
  title: string;
  content: string;
  css?: string | null;
};

export type Message = {
  id: string;
  session_id: string;
  role: MessageRole;
  content: string;
  artifact: Artifact | null;
  created_at: string;
};

export type HealthResponse = {
  status: string;
};

/** Provider selection sent with every chat request. The backend owns the keys. */
export type LLMMode = "cloud" | "ollama";

export type ActivityEvent = {
  stage: string;
  message: string;
  detail: Record<string, string | number | boolean | null>;
  created_at: string;
};

export type Source = {
  episode_id: string;
  title?: string | null;
  guest?: string | null;
  publish_date?: string | null;
  youtube_url?: string | null;
  chunk_index?: number | null;
  similarity?: number | null;
  excerpt?: string | null;
};

/** Capability measurements (word count, reading time, artifact type). */
export type ChatMetrics = Record<string, string | number | boolean>;

export type ChatRequest = {
  session_id: string;
  message: string;
  llm_mode?: LLMMode | null;
};

export type ChatResponse = {
  session_id: string;
  message: Message;
  user_message: Message;
  artifact: Artifact | null;
  sources: Source[];
  activity: ActivityEvent[];
  llm_mode: string;
  provider: string;
  model: string | null;
  intent: string;
  skills: string[];
  metrics: ChatMetrics;
};

export type ChatErrorPayload = {
  detail: string;
  status: number;
  category: string;
};

export type ChatStreamEvent =
  | { event: "activity"; data: ActivityEvent }
  | { event: "artifact_ready"; data: Artifact }
  | { event: "done"; data: ChatResponse }
  | { event: "error"; data: ChatErrorPayload };
