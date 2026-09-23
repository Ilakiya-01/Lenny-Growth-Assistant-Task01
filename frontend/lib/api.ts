import { parseSSE, type SSEFrame } from "@/lib/sse";
import type {
  ChatRequest,
  ChatResponse,
  ChatStreamEvent,
  HealthResponse,
  Message,
  Session,
} from "@/types";

const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

export class ApiError extends Error {
  readonly status: number;
  /** Coarse backend error category, present on streamed failures. */
  readonly category?: string;

  constructor(message: string, status: number, category?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.category = category;
  }
}

export function isAbort(cause: unknown): boolean {
  return cause instanceof Error && cause.name === "AbortError";
}

async function readErrorBody(
  response: Response,
): Promise<{ detail: string; category?: string }> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      const category = (body as { category?: unknown }).category;
      if (typeof detail === "string") {
        return {
          detail,
          category: typeof category === "string" ? category : undefined,
        };
      }
    }
  } catch {
    // Response was not JSON; fall through to the generic message.
  }
  return { detail: `The request failed with status ${response.status}.` };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
      cache: "no-store",
    });
  } catch (cause) {
    if (isAbort(cause)) throw cause;
    throw new ApiError(backendUnreachableMessage(), 0);
  }

  if (!response.ok) {
    const { detail, category } = await readErrorBody(response);
    throw new ApiError(detail, response.status, category);
  }

  return (await response.json()) as T;
}

function backendUnreachableMessage(): string {
  return `Could not reach the backend at ${API_BASE_URL}. Make sure the FastAPI server is running.`;
}

function asStreamEvent(frame: SSEFrame): ChatStreamEvent | null {
  let data: unknown;
  try {
    data = JSON.parse(frame.data);
  } catch {
    return null;
  }
  switch (frame.event) {
    case "activity":
    case "artifact_ready":
    case "done":
    case "error":
      return { event: frame.event, data } as ChatStreamEvent;
    default:
      // Unknown events are ignored so the protocol can grow without breaking
      // an older client.
      return null;
  }
}

export const api = {
  getHealth: () => request<HealthResponse>("/api/health"),

  listSessions: async (): Promise<Session[]> => {
    const body = await request<{ sessions: Session[] }>("/api/sessions");
    return body.sessions;
  },

  createSession: (title?: string): Promise<Session> =>
    request<Session>("/api/sessions", {
      method: "POST",
      body: JSON.stringify(title ? { title } : {}),
    }),

  listMessages: async (sessionId: string): Promise<Message[]> => {
    const body = await request<{ messages: Message[] }>(
      `/api/sessions/${sessionId}/messages`,
    );
    return body.messages;
  },

  /** One complete turn, without progressive events. */
  sendChat: (payload: ChatRequest): Promise<ChatResponse> =>
    request<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  /**
   * One turn as Server-Sent Events: high-level activity arrives while the model
   * is still working, the artifact arrives as its own structured payload, and
   * the completed turn resolves the returned promise.
   */
  streamChat: async (
    payload: ChatRequest,
    onEvent: (event: ChatStreamEvent) => void,
    signal?: AbortSignal,
  ): Promise<ChatResponse> => {
    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify(payload),
        cache: "no-store",
        signal,
      });
    } catch (cause) {
      if (isAbort(cause)) throw cause;
      throw new ApiError(backendUnreachableMessage(), 0);
    }

    if (!response.ok) {
      const { detail, category } = await readErrorBody(response);
      throw new ApiError(detail, response.status, category);
    }
    if (!response.body) {
      throw new ApiError("The chat stream returned no data.", 502);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let completed: ChatResponse | null = null;

    try {
      for (;;) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const parsed = parseSSE(buffer);
        buffer = parsed.rest;
        for (const frame of parsed.frames) {
          const event = asStreamEvent(frame);
          if (!event) continue;
          if (event.event === "done") completed = event.data;
          if (event.event === "error") {
            throw new ApiError(
              event.data.detail,
              event.data.status,
              event.data.category,
            );
          }
          onEvent(event);
        }
      }
    } finally {
      reader.releaseLock();
    }

    if (!completed) {
      throw new ApiError(
        "The chat stream ended before the response was complete.",
        502,
      );
    }
    return completed;
  },
};

export { API_BASE_URL };
