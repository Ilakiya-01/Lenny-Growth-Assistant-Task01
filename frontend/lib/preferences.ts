import type { LLMMode } from "@/types";

const SESSION_KEY = "lenny.workspace.session";
const MODE_KEY = "lenny.workspace.llm-mode";

const MODES: readonly LLMMode[] = ["cloud", "ollama"];

/**
 * Local UI preferences only. Conversation data stays in the backend database:
 * nothing here is a cache of messages, and losing it costs one click.
 */
function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // Storage can be unavailable (private mode, embedded previews); the
    // preference is then simply not remembered.
  }
}

export function readStoredSessionId(): string | null {
  return read(SESSION_KEY);
}

export function storeSessionId(sessionId: string | null): void {
  write(SESSION_KEY, sessionId);
}

export function readStoredLLMMode(): LLMMode | null {
  const stored = read(MODE_KEY);
  return MODES.includes(stored as LLMMode) ? (stored as LLMMode) : null;
}

export function storeLLMMode(mode: LLMMode): void {
  write(MODE_KEY, mode);
}
