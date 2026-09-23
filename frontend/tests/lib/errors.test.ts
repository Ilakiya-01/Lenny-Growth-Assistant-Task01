import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import {
  OLLAMA_UNAVAILABLE_MESSAGE,
  describeChatFailure,
  describeLoadFailure,
} from "@/lib/errors";

describe("describeChatFailure", () => {
  it("uses the agreed Ollama wording when the local provider is unreachable", () => {
    expect(OLLAMA_UNAVAILABLE_MESSAGE).toBe(
      "Cannot connect to Ollama. Make sure Ollama is running and the configured model is available, or switch to Cloud.",
    );

    const failure = describeChatFailure(
      new ApiError("Connection refused", 503, "llm_unavailable"),
      "ollama",
    );
    expect(failure.message).toBe(OLLAMA_UNAVAILABLE_MESSAGE);
    expect(failure.detail).toBe("Connection refused");
    expect(failure.retryable).toBe(true);
  });

  it("treats a timeout and an unknown model as provider problems too", () => {
    for (const category of ["llm_timeout", "llm_model_unavailable"]) {
      const failure = describeChatFailure(new ApiError("nope", 503, category), "ollama");
      expect(failure.message).toBe(OLLAMA_UNAVAILABLE_MESSAGE);
    }
  });

  it("does not blame Ollama for a Cloud failure", () => {
    const failure = describeChatFailure(
      new ApiError("The language model provider is unavailable.", 503, "llm_unavailable"),
      "cloud",
    );
    expect(failure.message).toBe("The language model provider is unavailable.");
    expect(failure.detail).toBeUndefined();
  });

  it("keeps the backend wording for unrelated failures", () => {
    const failure = describeChatFailure(
      new ApiError("The request could not be classified.", 502, "agent_classification"),
      "ollama",
    );
    expect(failure.message).toBe("The request could not be classified.");
  });

  it("does not duplicate the detail when it already is the Ollama message", () => {
    const failure = describeChatFailure(
      new ApiError(OLLAMA_UNAVAILABLE_MESSAGE, 503, "llm_unavailable"),
      "ollama",
    );
    expect(failure.detail).toBeUndefined();
  });

  it("falls back to a generic message for a non-error", () => {
    expect(describeChatFailure(undefined, "ollama").message).toBe(
      "The request could not be completed. Please try again.",
    );
  });
});

describe("describeLoadFailure", () => {
  it("prefers the error message and falls back otherwise", () => {
    expect(describeLoadFailure(new Error("boom"), "ignored").message).toBe("boom");
    expect(describeLoadFailure(null, "Sessions could not be loaded.").message).toBe(
      "Sessions could not be loaded.",
    );
  });
});
