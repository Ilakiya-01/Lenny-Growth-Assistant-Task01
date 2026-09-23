import { describe, expect, it } from "vitest";

import { parseSSE } from "@/lib/sse";

describe("parseSSE", () => {
  it("reads a named event with its data", () => {
    const { frames, rest } = parseSSE('event: done\ndata: {"a":1}\n\n');
    expect(frames).toEqual([{ event: "done", data: '{"a":1}' }]);
    expect(rest).toBe("");
  });

  it("defaults the event name to message", () => {
    const { frames } = parseSSE("data: hello\n\n");
    expect(frames[0].event).toBe("message");
  });

  it("joins multiple data lines with a newline", () => {
    const { frames } = parseSSE("data: line one\ndata: line two\n\n");
    expect(frames[0].data).toBe("line one\nline two");
  });

  it("tolerates CRLF line endings", () => {
    const { frames } = parseSSE("event: activity\r\ndata: {}\r\n\r\n");
    expect(frames).toEqual([{ event: "activity", data: "{}" }]);
  });

  it("keeps an incomplete frame in rest", () => {
    const { frames, rest } = parseSSE('event: done\ndata: {"a"');
    expect(frames).toEqual([]);
    expect(rest).toBe('event: done\ndata: {"a"');
  });

  it("ignores comment keep-alives", () => {
    const { frames } = parseSSE(": ping\n\nevent: done\ndata: 1\n\n");
    expect(frames).toEqual([{ event: "done", data: "1" }]);
  });

  it("parses several frames from one buffer", () => {
    const { frames } = parseSSE("event: a\ndata: 1\n\nevent: b\ndata: 2\n\n");
    expect(frames.map((frame) => frame.event)).toEqual(["a", "b"]);
  });
});
