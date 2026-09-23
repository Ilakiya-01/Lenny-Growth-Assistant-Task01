import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { useWorkspace } from "@/lib/useWorkspace";
import { OLLAMA_UNAVAILABLE_MESSAGE } from "@/lib/errors";
import type { ActivityEvent, ChatResponse, ChatStreamEvent } from "@/types";
import {
  HTML_ARTIFACT,
  MARKDOWN_ARTIFACT,
  chatResponse,
  message,
  session,
} from "../fixtures";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      getHealth: vi.fn(),
      listSessions: vi.fn(),
      createSession: vi.fn(),
      listMessages: vi.fn(),
      sendChat: vi.fn(),
      streamChat: vi.fn(),
    },
  };
});

const health = vi.mocked(api.getHealth);
const listSessions = vi.mocked(api.listSessions);
const createSession = vi.mocked(api.createSession);
const listMessages = vi.mocked(api.listMessages);
const streamChat = vi.mocked(api.streamChat);

const SESSIONS = [session("s2", "Ship30for30 essay"), session("s1", "Product-market fit")];

const S1_MESSAGES = [
  message("m1", "user", "What does Lenny say about product-market fit?", { session_id: "s1" }),
  message("m2", "assistant", "Pull, not push.", { session_id: "s1" }),
];

const S2_MESSAGES = [
  message("m9", "user", "Write an essay about activation.", { session_id: "s2" }),
];

function primeBackend() {
  health.mockResolvedValue({ status: "ok" });
  listSessions.mockResolvedValue(SESSIONS);
  listMessages.mockImplementation(async (sessionId: string) => {
    if (sessionId === "s1") return S1_MESSAGES;
    if (sessionId === "s2") return S2_MESSAGES;
    return [];
  });
  streamChat.mockImplementation(async (_payload, onEvent) => {
    onEvent({
      event: "activity",
      data: {
        stage: "retrieving_evidence",
        message: "Searching Lenny's transcripts",
        detail: {},
        created_at: "2026-09-22T09:31:00Z",
      },
    });
    return chatResponse();
  });
}

async function mountWorkspace() {
  const hook = renderHook(() => useWorkspace());
  await waitFor(() => expect(hook.result.current.status).toBe("ready"));
  return hook;
}

const ACTIVITY: ActivityEvent = {
  stage: "retrieving_evidence",
  message: "Searching Lenny's transcripts",
  detail: {},
  created_at: "2026-09-22T09:31:00Z",
};

/**
 * Chat streams that stay open until the test finishes them, recording each
 * session's abort signal so a switch can be shown not to cancel anything.
 */
function holdStreams(options: { activity?: boolean } = {}) {
  const signals: Record<string, AbortSignal> = {};
  const settle: Record<
    string,
    { resolve: (value: ChatResponse) => void; reject: (cause: unknown) => void }
  > = {};
  streamChat.mockImplementation((payload, onEvent, signal) => {
    if (signal) signals[payload.session_id] = signal;
    if (options.activity !== false) onEvent({ event: "activity", data: ACTIVITY });
    return new Promise<ChatResponse>((resolve, reject) => {
      settle[payload.session_id] = { resolve, reject };
      signal?.addEventListener("abort", () => {
        reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
      });
    });
  });
  return { signals, settle };
}

beforeEach(() => {
  vi.clearAllMocks();
  primeBackend();
});

describe("workspace bootstrap", () => {
  it("loads the session list and selects one", async () => {
    const { result } = await mountWorkspace();
    expect(result.current.sessions).toHaveLength(2);
    expect(result.current.selectedSessionId).toBe("s2");
    expect(result.current.selectedSession?.title).toBe("Ship30for30 essay");
  });

  it("loads the selected session's messages and nothing else", async () => {
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(listMessages).toHaveBeenCalledWith("s2");
    expect(result.current.messages.map((item) => item.id)).toEqual(["m9"]);
  });

  it("restores the previously selected session when it still exists", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    const { result } = await mountWorkspace();
    expect(result.current.selectedSessionId).toBe("s1");
  });

  it("ignores a stored session id that no longer exists", async () => {
    localStorage.setItem("lenny.workspace.session", "deleted");
    const { result } = await mountWorkspace();
    expect(result.current.selectedSessionId).toBe("s2");
  });

  it("creates the first session for an empty workspace", async () => {
    listSessions.mockResolvedValue([]);
    createSession.mockResolvedValue(session("s1", "New chat"));
    const { result } = await mountWorkspace();
    expect(createSession).toHaveBeenCalledTimes(1);
    expect(result.current.selectedSessionId).toBe("s1");
  });

  it("reports an unreachable backend instead of rendering a blank page", async () => {
    health.mockRejectedValue(new ApiError("Could not reach the backend at http://localhost:8000.", 0));
    const { result } = await mountWorkspace();
    expect(result.current.error?.scope).toBe("sessions");
    expect(result.current.error?.message).toMatch(/Could not reach the backend/);
    expect(result.current.sessions).toEqual([]);
  });

  it("reports a failed message load without losing the session list", async () => {
    listMessages.mockRejectedValue(new ApiError("The database is currently unavailable.", 503));
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.error?.scope).toBe("messages"));
    expect(result.current.sessions).toHaveLength(2);
    expect(result.current.messages).toEqual([]);
  });
});

describe("session switching", () => {
  it("replaces the conversation, never mixes two sessions", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages.map((m) => m.id)).toEqual(["m1", "m2"]));

    act(() => result.current.selectSession("s2"));

    await waitFor(() => expect(result.current.messages.map((m) => m.id)).toEqual(["m9"]));
    expect(result.current.messages.every((m) => !m.content.includes("product-market fit"))).toBe(true);
    expect(listMessages).toHaveBeenLastCalledWith("s2");
  });

  it("clears the previous session's open artifact", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    act(() => result.current.openArtifact("m2"));
    expect(result.current.artifactView).toBeNull(); // m2 carries no artifact

    act(() => result.current.selectSession("s2"));
    await waitFor(() => expect(result.current.selectedSessionId).toBe("s2"));
    expect(result.current.artifactView).toBeNull();
  });

  it("creates a session from the sidebar action", async () => {
    createSession.mockResolvedValue(session("s3", "New chat"));
    const { result } = await mountWorkspace();

    await act(async () => {
      await result.current.createSession();
    });

    expect(result.current.sessions.map((s) => s.id)).toEqual(["s3", "s2", "s1"]);
    expect(result.current.selectedSessionId).toBe("s3");
    expect(result.current.messages).toEqual([]);
  });

  it("reports a failed session creation", async () => {
    createSession.mockRejectedValue(new ApiError("The database is currently unavailable.", 503));
    const { result } = await mountWorkspace();

    await act(async () => {
      await result.current.createSession();
    });

    expect(result.current.error?.message).toBe("The database is currently unavailable.");
    expect(result.current.selectedSessionId).toBe("s2");
  });

  it("drops a late reply that belongs to a session the user left", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    let release: (value: ChatResponse) => void = () => undefined;
    streamChat.mockImplementation(
      () => new Promise((resolve) => { release = resolve; }) as Promise<ChatResponse>,
    );

    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    act(() => {
      void result.current.send("Explain activation");
    });
    await waitFor(() => expect(result.current.status).toBe("sending"));

    act(() => result.current.selectSession("s2"));

    release(chatResponse());
    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(result.current.messages.map((m) => m.id)).toEqual(["m9"]);
    expect(result.current.messages.some((m) => m.pending)).toBe(false);
  });
});

describe("in-flight request across session switches", () => {
  it("keeps running when the reader switches to another session", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    const held = holdStreams();
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    act(() => {
      void result.current.send("What about activation?");
    });
    await waitFor(() => expect(result.current.status).toBe("sending"));

    act(() => result.current.selectSession("s2"));
    await waitFor(() => expect(result.current.messages.map((m) => m.id)).toEqual(["m9"]));

    expect(held.signals.s1.aborted).toBe(false);
    expect(result.current.error).toBeNull();

    // Still the same request: it finishes on its own terms, not as a failure.
    held.settle.s1.resolve(chatResponse());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.error).toBeNull();
    expect(result.current.draft).toBe("");
  });

  it("restores the in-flight turn when the reader returns", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    holdStreams();
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    act(() => {
      void result.current.send("What about activation?");
    });
    await waitFor(() => expect(result.current.status).toBe("sending"));
    const startedAt = result.current.activityStartedAt;
    expect(startedAt).not.toBeNull();
    expect(result.current.activity.map((event) => event.message)).toEqual([
      "Searching Lenny's transcripts",
    ]);

    act(() => result.current.selectSession("s2"));
    await waitFor(() => expect(result.current.selectedSessionId).toBe("s2"));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    // The other session stays isolated: no borrowed message, stage or timer.
    expect(result.current.activity).toEqual([]);
    expect(result.current.activityStartedAt).toBeNull();
    expect(result.current.messages.some((m) => m.pending)).toBe(false);

    act(() => result.current.selectSession("s1"));
    await waitFor(() => expect(result.current.messages).toHaveLength(3));
    expect(result.current.status).toBe("sending");
    expect(result.current.messages.at(-1)).toMatchObject({
      role: "user",
      content: "What about activation?",
      pending: true,
    });
    expect(result.current.activity.map((event) => event.message)).toEqual([
      "Searching Lenny's transcripts",
    ]);
    expect(result.current.activityStartedAt).toBe(startedAt);
    // The turn was never restarted, duplicated or cancelled by the switching.
    expect(streamChat).toHaveBeenCalledTimes(1);
  });

  it("keeps collecting progress for the session that is not on screen", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    let progress: ((event: ChatStreamEvent) => void) | null = null;
    streamChat.mockImplementation((_payload, onEvent) => {
      progress = onEvent;
      return new Promise<ChatResponse>(() => undefined);
    });
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    act(() => {
      void result.current.send("What about activation?");
    });
    await waitFor(() => expect(result.current.status).toBe("sending"));
    act(() => result.current.selectSession("s2"));
    await waitFor(() => expect(result.current.selectedSessionId).toBe("s2"));

    // The background turn keeps its own progress, and nothing else changes.
    act(() => {
      progress?.({ event: "activity", data: ACTIVITY });
      progress?.({ event: "activity", data: { ...ACTIVITY, stage: "generating_response" } });
    });
    expect(result.current.messages.map((m) => m.id)).toEqual(["m9"]);
    expect(result.current.activity).toEqual([]);

    act(() => result.current.selectSession("s1"));
    await waitFor(() => expect(result.current.activity).toHaveLength(2));
    expect(result.current.activity.map((event) => event.stage)).toEqual([
      "retrieving_evidence",
      "generating_response",
    ]);
  });

  it("finishes a background turn in its own session only", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    const held = holdStreams({ activity: false });
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    act(() => {
      void result.current.send("Explain activation");
    });
    await waitFor(() => expect(result.current.status).toBe("sending"));
    act(() => result.current.selectSession("s2"));
    await waitFor(() => expect(result.current.messages.map((m) => m.id)).toEqual(["m9"]));

    // The turn persists while s2 is on screen; the database now holds both rows.
    listMessages.mockImplementation(async (sessionId: string) =>
      sessionId === "s1"
        ? [
            ...S1_MESSAGES,
            message("m3", "user", "Explain activation"),
            message("m4", "assistant", "Activation is the first win."),
          ]
        : S2_MESSAGES,
    );
    await act(async () => {
      held.settle.s1.resolve(
        chatResponse({
          user_message: message("m3", "user", "Explain activation"),
          message: message("m4", "assistant", "Activation is the first win."),
        }),
      );
    });
    await waitFor(() => expect(listSessions).toHaveBeenCalledTimes(2));

    // Nothing about the finished turn appears in the session on screen.
    expect(result.current.messages.map((m) => m.id)).toEqual(["m9"]);
    expect(result.current.artifactView).toBeNull();
    expect(result.current.error).toBeNull();

    // Opening the origin shows the completed turn like any other reply.
    act(() => result.current.selectSession("s1"));
    await waitFor(() =>
      expect(result.current.messages.map((m) => m.id)).toEqual(["m1", "m2", "m3", "m4"]),
    );
    expect(result.current.status).toBe("ready");
    expect(result.current.messages.every((m) => !m.pending)).toBe(true);
    expect(result.current.messages.at(-1)?.content).toBe("Activation is the first win.");
  });

  it("reports a failed background turn to its own session only", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    const held = holdStreams({ activity: false });
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    act(() => {
      void result.current.send("What about activation?");
    });
    await waitFor(() => expect(result.current.status).toBe("sending"));
    act(() => result.current.selectSession("s2"));
    await waitFor(() => expect(result.current.selectedSessionId).toBe("s2"));

    await act(async () => {
      held.settle.s1.reject(new ApiError("Connection refused", 503, "llm_unavailable"));
    });

    // s2 shows neither the other session's failure nor its unsent message.
    expect(result.current.error).toBeNull();
    expect(result.current.draft).toBe("");
    expect(result.current.messages.map((m) => m.id)).toEqual(["m9"]);

    act(() => result.current.selectSession("s1"));
    await waitFor(() => expect(result.current.error?.message).toBe(OLLAMA_UNAVAILABLE_MESSAGE));
    expect(result.current.error?.scope).toBe("chat");
    expect(result.current.messages.some((m) => m.pending)).toBe(false);
  });

  it("stops only the session on screen", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    const held = holdStreams({ activity: false });
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    act(() => {
      void result.current.send("What about activation?");
    });
    await waitFor(() => expect(result.current.status).toBe("sending"));

    act(() => result.current.selectSession("s2"));
    await waitFor(() => expect(result.current.selectedSessionId).toBe("s2"));
    act(() => {
      void result.current.send("Write an essay about activation.");
    });
    await waitFor(() => expect(result.current.status).toBe("sending"));
    expect(result.current.messages.at(-1)?.pending).toBe(true);

    act(() => result.current.cancel());
    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(held.signals.s2.aborted).toBe(true);
    // The turn started first is untouched by a stop issued in another session.
    expect(held.signals.s1.aborted).toBe(false);
    expect(result.current.messages.map((m) => m.id)).toEqual(["m9"]);
    expect(result.current.draft).toBe("Write an essay about activation.");

    act(() => result.current.selectSession("s1"));
    await waitFor(() => expect(result.current.status).toBe("sending"));
    expect(result.current.messages.at(-1)).toMatchObject({
      content: "What about activation?",
      pending: true,
    });
  });

  it("runs one request per session and replaces the finished turn", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    const held = holdStreams({ activity: false });
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    act(() => {
      void result.current.send("First question");
    });
    await waitFor(() => expect(result.current.status).toBe("sending"));
    const first = held.signals.s1;

    // A second send in the same session is refused while the first is running.
    await act(async () => {
      await result.current.send("Second question");
    });
    expect(streamChat).toHaveBeenCalledTimes(1);

    await act(async () => {
      held.settle.s1.resolve(chatResponse());
    });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(first.aborted).toBe(false);

    // The finished turn is replaced, not stacked under the new one.
    act(() => {
      void result.current.send("Second question");
    });
    await waitFor(() => expect(streamChat).toHaveBeenCalledTimes(2));
    expect(held.signals.s1).not.toBe(first);
    expect(result.current.messages.at(-1)).toMatchObject({
      content: "Second question",
      pending: true,
    });
    await act(async () => {
      held.settle.s1.resolve(chatResponse());
    });
    await waitFor(() => expect(result.current.status).toBe("ready"));
  });
});

describe("sending a turn", () => {
  it("shows the pending user message while the agent works", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    let release: (value: ChatResponse) => void = () => undefined;
    streamChat.mockImplementation(
      (_payload, onEvent) => {
        onEvent({
          event: "activity",
          data: {
            stage: "retrieving_evidence",
            message: "Searching Lenny's transcripts",
            detail: {},
            created_at: "2026-09-22T09:31:00Z",
          },
        });
        return new Promise((resolve) => {
          release = resolve;
        }) as Promise<ChatResponse>;
      },
    );

    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    act(() => {
      void result.current.send("What about activation?");
    });

    await waitFor(() => expect(result.current.status).toBe("sending"));
    expect(result.current.messages.at(-1)).toMatchObject({
      role: "user",
      content: "What about activation?",
      pending: true,
    });
    expect(result.current.activity.at(-1)?.message).toBe("Searching Lenny's transcripts");

    release(chatResponse());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.activity).toEqual([]);
  });

  it("replaces the optimistic row with the persisted messages", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    streamChat.mockResolvedValue(
      chatResponse({
        user_message: message("m3", "user", "What about activation?", { session_id: "s1" }),
        message: message("m4", "assistant", "Activation follows retention.", { session_id: "s1" }),
      }),
    );
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.send("What about activation?");
    });

    const ids = result.current.messages.map((m) => m.id);
    expect(ids).toEqual(["m1", "m2", "m3", "m4"]);
    expect(result.current.messages.every((m) => !m.pending)).toBe(true);
    expect(result.current.messages.at(-1)?.sources).toHaveLength(1);
    expect(result.current.messages.at(-1)?.metrics.word_count).toBe(12);
    expect(result.current.draft).toBe("");
  });

  it("sends the session id, message and provider to the backend", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      result.current.setLLMMode("cloud");
    });
    await act(async () => {
      await result.current.send("What about activation?");
    });

    expect(streamChat).toHaveBeenCalledWith(
      { session_id: "s1", message: "What about activation?", llm_mode: "cloud" },
      expect.any(Function),
      expect.any(AbortSignal),
    );
  });

  it("remembers the provider choice for the next visit", async () => {
    const { result } = await mountWorkspace();
    act(() => result.current.setLLMMode("cloud"));
    expect(localStorage.getItem("lenny.workspace.llm-mode")).toBe("cloud");

    const next = renderHook(() => useWorkspace());
    await waitFor(() => expect(next.result.current.status).toBe("ready"));
    expect(next.result.current.llmMode).toBe("cloud");
    next.unmount();
  });

  it("ignores an empty or whitespace-only message", async () => {
    const { result } = await mountWorkspace();
    await act(async () => {
      await result.current.send("   ");
    });
    expect(streamChat).not.toHaveBeenCalled();
    expect(result.current.status).toBe("ready");
  });

  it("opens the viewer when the turn produced an artifact", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    streamChat.mockImplementation(async (_payload, onEvent) => {
      onEvent({ event: "artifact_ready", data: MARKDOWN_ARTIFACT });
      return chatResponse({
        artifact: MARKDOWN_ARTIFACT,
        message: message("m2", "assistant", "Here is the essay.", {
          artifact: MARKDOWN_ARTIFACT,
        }),
      });
    });

    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.send("Write an essay");
    });

    expect(result.current.artifactView?.artifact.title).toBe("Product-market fit essay");
    expect(result.current.artifactView?.messageId).toBe("m2");
  });

  it("leaves the viewer closed when the turn produced no artifact", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.send("What about activation?");
    });

    expect(result.current.artifactView).toBeNull();
  });

  it("reopens an artifact from an earlier message and closes it again", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    listMessages.mockResolvedValue([
      message("m1", "user", "Write an essay", { session_id: "s1" }),
      message("m2", "assistant", "Here it is.", { session_id: "s1", artifact: HTML_ARTIFACT }),
    ]);
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    act(() => result.current.openArtifact("m2"));
    expect(result.current.artifactView?.artifact.type).toBe("html_css");

    act(() => result.current.closeArtifact());
    expect(result.current.artifactView).toBeNull();

    act(() => result.current.openArtifact("m2"));
    expect(result.current.artifactView?.artifact.title).toBe("Landing page");
  });

  it("keeps a persisted reply even if refreshing the sidebar fails", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    listSessions.mockRejectedValueOnce(new ApiError("boom", 503));
    await act(async () => {
      await result.current.send("What about activation?");
    });

    expect(result.current.messages.at(-1)?.id).toBe("m2");
    expect(result.current.error).toBeNull();
  });

  it("refreshes the sidebar after a turn so the new title shows", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    listSessions.mockResolvedValue([session("s1", "Product-market fit questions")]);
    await act(async () => {
      await result.current.send("What about activation?");
    });

    expect(result.current.sessions[0].title).toBe("Product-market fit questions");
  });
});

describe("failures", () => {
  it("explains an unreachable local provider and restores the draft", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    streamChat.mockRejectedValue(new ApiError("Connection refused", 503, "llm_unavailable"));
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.send("What about activation?");
    });

    expect(result.current.error?.message).toBe(OLLAMA_UNAVAILABLE_MESSAGE);
    expect(result.current.error?.scope).toBe("chat");
    expect(result.current.draft).toBe("What about activation?");
    expect(result.current.messages.some((m) => m.pending)).toBe(false);
    expect(result.current.messages).toHaveLength(2);
  });

  it("keeps the backend wording for a Cloud failure", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    streamChat.mockRejectedValue(new ApiError("The LLM configuration is incomplete.", 503));
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      result.current.setLLMMode("cloud");
    });
    await act(async () => {
      await result.current.send("What about activation?");
    });

    expect(result.current.error?.message).toBe("The LLM configuration is incomplete.");
  });

  it("restores the draft silently when the user stops the request", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    streamChat.mockImplementation(
      (_payload, _onEvent, signal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener("abort", () => {
            reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
          });
        }),
    );

    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    act(() => {
      void result.current.send("What about activation?");
    });
    await waitFor(() => expect(result.current.status).toBe("sending"));

    act(() => result.current.cancel());
    await waitFor(() => expect(result.current.status).toBe("ready"));

    expect(result.current.error).toBeNull();
    expect(result.current.draft).toBe("What about activation?");
    expect(result.current.messages).toHaveLength(2);
  });

  it("retries the failed turn", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    streamChat.mockRejectedValueOnce(new ApiError("Connection refused", 503, "llm_unavailable"));
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.send("What about activation?");
    });
    expect(result.current.error).not.toBeNull();

    streamChat.mockResolvedValueOnce(chatResponse());
    await act(async () => {
      result.current.retry();
    });

    await waitFor(() => expect(result.current.error).toBeNull());
    expect(result.current.messages.at(-1)?.pending).toBe(false);
  });

  it("dismisses an error", async () => {
    localStorage.setItem("lenny.workspace.session", "s1");
    streamChat.mockRejectedValue(new ApiError("Connection refused", 503, "llm_unavailable"));
    const { result } = await mountWorkspace();
    await waitFor(() => expect(result.current.messages).toHaveLength(2));

    await act(async () => {
      await result.current.send("What about activation?");
    });
    act(() => result.current.dismissError());
    expect(result.current.error).toBeNull();
  });
});
