import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Message } from "@/components/Chat/Message";
import type { ChatMessage } from "@/lib/useWorkspace";
import { MARKDOWN_ARTIFACT, SOURCES } from "../fixtures";

function chatMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "m2",
    role: "assistant",
    content: "**Pull, not push.** Look for organic demand.",
    artifact: null,
    sources: [],
    metrics: {},
    pending: false,
    ...overrides,
  };
}

function renderMessage(message: ChatMessage, isArtifactOpen = false) {
  const onOpenArtifact = vi.fn();
  render(
    <ul>
      <Message message={message} isArtifactOpen={isArtifactOpen} onOpenArtifact={onOpenArtifact} />
    </ul>,
  );
  return onOpenArtifact;
}

describe("Message", () => {
  it("renders a user message as plain text", () => {
    renderMessage(chatMessage({ id: "m1", role: "user", content: "What did Lenny say?" }));
    expect(screen.getByText("What did Lenny say?")).toBeInTheDocument();
    expect(screen.getByText("You said:")).toBeInTheDocument();
  });

  it("renders assistant Markdown as elements", () => {
    renderMessage(chatMessage());
    expect(screen.getByText("Pull, not push.").tagName).toBe("STRONG");
  });

  it("does not execute markup embedded in model output", () => {
    renderMessage(chatMessage({ content: '<img src="x" onerror="steal()"> text' }));
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src="x"/)).toBeInTheDocument();
  });

  it("shows word count and reading time when the backend measured them", () => {
    renderMessage(
      chatMessage({ metrics: { word_count: 1180, reading_time_minutes: 5 } }),
    );
    expect(screen.getByText("1,180 words • 5 min read")).toBeInTheDocument();
  });

  it("lists transcript sources behind a disclosure", async () => {
    const user = userEvent.setup();
    renderMessage(chatMessage({ sources: SOURCES }));
    const details = screen.getByText("Sources (1)").closest("details");
    expect(details).not.toHaveAttribute("open");

    await user.click(screen.getByText("Sources (1)"));
    expect(details).toHaveAttribute("open");
    expect(within(details as HTMLElement).getByText("Finding product-market fit")).toBeInTheDocument();
    expect(within(details as HTMLElement).getByText(/Ada Lovelace/)).toBeInTheDocument();
    expect(
      within(details as HTMLElement).getByRole("link", { name: "Watch episode" }),
    ).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("opens the artifact viewer for a message that produced one", async () => {
    const user = userEvent.setup();
    const onOpenArtifact = renderMessage(chatMessage({ artifact: MARKDOWN_ARTIFACT }));
    await user.click(screen.getByRole("button", { name: /open product-market fit essay/i }));
    expect(onOpenArtifact).toHaveBeenCalledWith("m2");
  });

  it("reports when its artifact is already open, so it can be reopened", () => {
    renderMessage(chatMessage({ artifact: MARKDOWN_ARTIFACT }), true);
    const button = screen.getByRole("button", { name: /viewing product-market fit essay/i });
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(button).toHaveTextContent("Markdown");
  });

  it("renders no artifact control without an artifact", () => {
    renderMessage(chatMessage());
    expect(screen.queryByRole("button")).toBeNull();
  });
});
