/**
 * Minimal Server-Sent Events frame parser.
 *
 * The chat stream is consumed with `fetch` rather than `EventSource` because the
 * request is a POST with a JSON body. Frames are separated by a blank line and
 * carry an `event:` name plus one or more `data:` lines.
 */

export type SSEFrame = {
  event: string;
  data: string;
};

export type ParseResult = {
  frames: SSEFrame[];
  /** Trailing text that is not a complete frame yet. */
  rest: string;
};

const DEFAULT_EVENT = "message";

export function parseSSE(buffer: string): ParseResult {
  const frames: SSEFrame[] = [];
  // A frame ends at the first blank line; tolerate CRLF from proxies.
  const normalized = buffer.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";

  for (const block of blocks) {
    if (!block.trim()) continue;
    let event = DEFAULT_EVENT;
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith(":")) continue; // comment / keep-alive
      const separator = line.indexOf(":");
      const field = separator === -1 ? line : line.slice(0, separator);
      let value = separator === -1 ? "" : line.slice(separator + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (data.length > 0) frames.push({ event, data: data.join("\n") });
  }

  return { frames, rest };
}
