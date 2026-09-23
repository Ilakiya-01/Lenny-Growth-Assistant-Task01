import { ApiError } from "@/lib/api";
import type { LLMMode } from "@/types";

export const OLLAMA_UNAVAILABLE_MESSAGE =
  "Cannot connect to Ollama. Make sure Ollama is running and the configured model is available, or switch to Cloud.";

/** Backend error categories that mean "the provider could not be reached". */
const PROVIDER_UNAVAILABLE_CATEGORIES = new Set([
  "llm_unavailable",
  "llm_timeout",
  "llm_model_unavailable",
]);

export type ChatFailure = {
  message: string;
  /** Secondary line from the backend, when it adds something actionable. */
  detail?: string;
  retryable: boolean;
};

export function describeChatFailure(cause: unknown, llmMode: LLMMode): ChatFailure {
  if (cause instanceof ApiError) {
    if (
      llmMode === "ollama" &&
      cause.category &&
      PROVIDER_UNAVAILABLE_CATEGORIES.has(cause.category)
    ) {
      return {
        message: OLLAMA_UNAVAILABLE_MESSAGE,
        detail: cause.message === OLLAMA_UNAVAILABLE_MESSAGE ? undefined : cause.message,
        retryable: true,
      };
    }
    return { message: cause.message, retryable: true };
  }

  if (cause instanceof Error && cause.message) {
    return { message: cause.message, retryable: true };
  }
  return { message: "The request could not be completed. Please try again.", retryable: true };
}

export function describeLoadFailure(cause: unknown, fallback: string): ChatFailure {
  const message =
    cause instanceof Error && cause.message ? cause.message : fallback;
  return { message, retryable: true };
}
