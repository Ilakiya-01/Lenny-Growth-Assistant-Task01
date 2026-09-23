import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { TextDecoder, TextEncoder } from "node:util";
import { afterEach } from "vitest";

// jsdom does not ship the streaming codecs the chat API layer relies on.
if (typeof globalThis.TextDecoder === "undefined") {
  globalThis.TextDecoder = TextDecoder as unknown as typeof globalThis.TextDecoder;
}
if (typeof globalThis.TextEncoder === "undefined") {
  globalThis.TextEncoder = TextEncoder as unknown as typeof globalThis.TextEncoder;
}

afterEach(() => {
  cleanup();
  localStorage.clear();
});
