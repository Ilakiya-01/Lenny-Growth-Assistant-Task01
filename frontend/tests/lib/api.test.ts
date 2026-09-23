import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, isAbort } from "@/lib/api";
import type { ChatStreamEvent } from "@/types";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    json: async () => body,
  } as unknown as Response;
}

/** A fetch body that yields the given SSE chunks and then ends. */
function streamResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  let index = 0;
  const reader = {
    read: async () =>
      index < chunks.length
        ? { done: false, value: encoder.encode(chunks[index++]) }
        : { done: true, value: undefined },
    releaseLock: () => undefined,
  };
  return {
    ok: status < 400,
    status,
    body: { getReader: () => reader },
    json: async () => ({}),
  } as unknown as Response;
}

function stubFetch(response: Response | (() => Response)) {
  const fetchMock = vi.fn(
    async (_input: RequestInfo | URL, _init?: RequestInit): Promise<Response> =>
      typeof response === "function" ? response() : response,
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api requests", () => {
  it("unwraps the session list", async () => {
    stubFetch(jsonResponse({ sessions: [{ id: "s1", title: "First" }] }));
    await expect(api.listSessions()).resolves.toEqual([{ id: "s1", title: "First" }]);
  });

  it("unwraps the message list", async () => {
    const fetchMock = stubFetch(jsonResponse({ messages: [] }));
    await api.listMessages("s1");
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/sessions/s1/messages");
  });

  it("sends the chat payload as JSON", async () => {
    const fetchMock = stubFetch(jsonResponse({}));
    await api.sendChat({ session_id: "s1", message: "hello", llm_mode: "cloud" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/chat");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      session_id: "s1",
      message: "hello",
      llm_mode: "cloud",
    });
  });

  it("surfaces the backend detail, status and category", async () => {
    stubFetch(
      jsonResponse({ detail: "The LLM configuration is incomplete.", category: "llm_config" }, 503),
    );
    const error = await api.getHealth().catch((cause: unknown) => cause);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe("The LLM configuration is incomplete.");
    expect((error as ApiError).status).toBe(503);
    expect((error as ApiError).category).toBe("llm_config");
  });

  it("reports an unreachable backend without leaking internals", async () => {
    stubFetch(() => {
      throw new TypeError("fetch failed");
    });
    const error = await api.getHealth().catch((cause: unknown) => cause);
    expect((error as ApiError).status).toBe(0);
    expect((error as ApiError).message).toMatch(/Could not reach the backend/);
  });

  it("rethrows an abort so the caller can tell a cancellation apart", async () => {
    const abort = Object.assign(new Error("aborted"), { name: "AbortError" });
    stubFetch(() => {
      throw abort;
    });
    await expect(api.getHealth()).rejects.toBe(abort);
    expect(isAbort(abort)).toBe(true);
    expect(isAbort(new Error("aborted"))).toBe(false);
  });
});

describe("api.streamChat", () => {
  const donePayload = { session_id: "s1", message: { id: "m2" } };

  it("emits activity and artifact events, then resolves with done", async () => {
    stubFetch(
      streamResponse([
        'event: activity\ndata: {"stage":"classifying_intent","message":"Classifying request"}\n\n',
        'event: artifact_ready\ndata: {"type":"markdown","title":"Essay","content":"# Hi"}\n\n',
        `event: done\ndata: ${JSON.stringify(donePayload)}\n\n`,
      ]),
    );

    const events: ChatStreamEvent[] = [];
    const result = await api.streamChat(
      { session_id: "s1", message: "write", llm_mode: "ollama" },
      (event) => events.push(event),
    );

    expect(events.map((event) => event.event)).toEqual(["activity", "artifact_ready", "done"]);
    expect(result).toEqual(donePayload);
  });

  it("reassembles a frame that arrives in two chunks", async () => {
    stubFetch(
      streamResponse([
        "event: act",
        'ivity\ndata: {"stage":"completed"}\n\nevent: done\ndata: {"ok":true}\n\n',
      ]),
    );
    const events: ChatStreamEvent[] = [];
    await api.streamChat({ session_id: "s1", message: "hi" }, (event) => events.push(event));
    expect(events.map((event) => event.event)).toEqual(["activity", "done"]);
  });

  it("ignores unknown events", async () => {
    stubFetch(
      streamResponse([
        'event: future\ndata: {"x":1}\n\n',
        'event: done\ndata: {"ok":true}\n\n',
      ]),
    );
    const events: ChatStreamEvent[] = [];
    await api.streamChat({ session_id: "s1", message: "hi" }, (event) => events.push(event));
    expect(events).toHaveLength(1);
  });

  it("turns an error event into an ApiError", async () => {
    stubFetch(
      streamResponse([
        'event: error\ndata: {"detail":"Cannot connect to Ollama.","status":503,"category":"llm_unavailable"}\n\n',
      ]),
    );
    const error = await api
      .streamChat({ session_id: "s1", message: "hi" }, () => undefined)
      .catch((cause: unknown) => cause);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(503);
    expect((error as ApiError).category).toBe("llm_unavailable");
  });

  it("fails when the stream ends without done", async () => {
    stubFetch(streamResponse(['event: activity\ndata: {"stage":"completed"}\n\n']));
    const error = await api
      .streamChat({ session_id: "s1", message: "hi" }, () => undefined)
      .catch((cause: unknown) => cause);
    expect((error as ApiError).status).toBe(502);
  });

  it("reports a rejected stream request before any bytes arrive", async () => {
    stubFetch(jsonResponse({ detail: "Session not found." }, 404));
    const error = await api
      .streamChat({ session_id: "missing", message: "hi" }, () => undefined)
      .catch((cause: unknown) => cause);
    expect((error as ApiError).status).toBe(404);
    expect((error as ApiError).message).toBe("Session not found.");
  });

  it("passes the abort signal through to fetch", async () => {
    const fetchMock = stubFetch(streamResponse(['event: done\ndata: {"ok":true}\n\n']));
    const controller = new AbortController();
    await api.streamChat({ session_id: "s1", message: "hi" }, () => undefined, controller.signal);
    expect(fetchMock.mock.calls[0][1]?.signal).toBe(controller.signal);
  });
});
