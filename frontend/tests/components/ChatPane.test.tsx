import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ComponentProps } from "react";

import { ChatPane } from "@/components/Chat/ChatPane";
import type { ChatMessage, WorkspaceError } from "@/lib/useWorkspace";
import type { ActivityEvent } from "@/types";
import { MARKDOWN_ARTIFACT, SOURCES, session } from "../fixtures";

type ChatPaneProps = ComponentProps<typeof ChatPane>;

const SESSION = session("s1", "Product-market fit");

const MESSAGES: ChatMessage[] = [
  {
    id: "m1",
    role: "user",
    content: "What does Lenny say about product-market fit?",
    artifact: null,
    sources: [],
    metrics: {},
    pending: false,
  },
  {
    id: "m2",
    role: "assistant",
    content: "**Pull, not push.** Look for organic demand.",
    artifact: MARKDOWN_ARTIFACT,
    sources: SOURCES,
    metrics: { word_count: 12 },
    pending: false,
  },
];

const ACTIVITY: ActivityEvent[] = [
  {
    stage: "retrieving_evidence",
    message: "Searching Lenny's transcripts",
    detail: { evidence_count: 3 },
    created_at: "2026-09-22T09:31:00Z",
  },
];

function renderPane(overrides: Partial<ChatPaneProps> = {}) {
  const props: ChatPaneProps = {
    session: SESSION,
    messages: [],
    status: "ready",
    activity: [],
    error: null,
    draft: "",
    llmMode: "ollama",
    artifactMessageId: null,
    onOpenSessions: vi.fn(),
    onDraftChange: vi.fn(),
    onSend: vi.fn(),
    onCancel: vi.fn(),
    onRetry: vi.fn(),
    onDismissError: vi.fn(),
    onLLMModeChange: vi.fn(),
    onOpenArtifact: vi.fn(),
    ...overrides,
  };
  render(<ChatPane {...props} />);
  return props;
}

describe("ChatPane: empty state", () => {
  it("offers the three starting points", () => {
    renderPane();
    expect(screen.getByText("What are you building today?")).toBeInTheDocument();
    expect(screen.getByText("Ask Lenny")).toBeInTheDocument();
    expect(screen.getByText("Write with Ship30for30")).toBeInTheDocument();
    expect(screen.getByText("Build an artifact")).toBeInTheDocument();
  });

  it("fills the composer from a prompt card without sending anything", async () => {
    const user = userEvent.setup();
    const { onSend, onDraftChange } = renderPane();

    await user.click(screen.getByText("Ask Lenny"));

    expect(onDraftChange).toHaveBeenCalledWith(
      "What does Lenny say about finding product-market fit?",
    );
    expect(onSend).not.toHaveBeenCalled();
  });

  it("shows the session title in the header", () => {
    renderPane();
    expect(screen.getByRole("heading", { level: 1, name: "Product-market fit" })).toBeInTheDocument();
  });
});

describe("ChatPane: messages", () => {
  it("renders the conversation in order", () => {
    renderPane({ messages: MESSAGES });
    const conversation = screen.getByRole("list", { name: "Conversation" });
    // Only the top level counts: a source list nests its own list items.
    const items = Array.from(conversation.children);
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveAttribute("data-role", "user");
    expect(items[1]).toHaveAttribute("data-role", "assistant");
    expect(within(items[1] as HTMLElement).getByText("Pull, not push.")).toBeInTheDocument();
  });

  it("marks the message whose artifact is open", () => {
    renderPane({ messages: MESSAGES, artifactMessageId: "m2" });
    expect(screen.getByRole("button", { name: /viewing product-market fit essay/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("opens an artifact from the message", async () => {
    const user = userEvent.setup();
    const { onOpenArtifact } = renderPane({ messages: MESSAGES });
    await user.click(screen.getByRole("button", { name: /open product-market fit essay/i }));
    expect(onOpenArtifact).toHaveBeenCalledWith("m2");
  });

  it("hides the empty-state cards once a conversation exists", () => {
    renderPane({ messages: MESSAGES });
    expect(screen.queryByText("What are you building today?")).toBeNull();
  });
});

describe("ChatPane: composer", () => {
  it("submits the draft from the Send button", async () => {
    const user = userEvent.setup();
    const { onSend } = renderPane({ draft: "Tell me about activation" });
    await user.click(screen.getByRole("button", { name: /^send/i }));
    expect(onSend).toHaveBeenCalledWith("Tell me about activation");
  });

  it("submits on Enter and keeps Shift+Enter for a new line", async () => {
    const user = userEvent.setup();
    const { onSend } = renderPane({ draft: "hello" });
    const field = screen.getByLabelText("Message");

    await user.type(field, "{Shift>}{Enter}{/Shift}");
    expect(onSend).not.toHaveBeenCalled();

    await user.type(field, "{Enter}");
    expect(onSend).toHaveBeenCalledWith("hello");
  });

  it("cannot submit an empty draft", async () => {
    const user = userEvent.setup();
    const { onSend } = renderPane({ draft: "   " });
    const send = screen.getByRole("button", { name: /^send/i });
    expect(send).toBeDisabled();
    await user.click(send);
    expect(onSend).not.toHaveBeenCalled();
  });

  it("is disabled until a session exists", () => {
    renderPane({ session: null });
    expect(screen.getByLabelText("Message")).toBeDisabled();
    expect(screen.getByText("Create a conversation to start")).toBeInTheDocument();
  });

  it("switches provider from the composer footer", async () => {
    const user = userEvent.setup();
    const { onLLMModeChange } = renderPane();
    await user.click(screen.getByRole("button", { name: /cloud/i }));
    expect(onLLMModeChange).toHaveBeenCalledWith("cloud");
  });
});

describe("ChatPane: activity and errors", () => {
  it("shows the agent's current stage while working", () => {
    renderPane({ status: "sending", activity: ACTIVITY, draft: "question" });
    const status = screen.getByRole("status");
    expect(within(status).getByText("Searching Lenny's transcripts")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
  });

  it("shows a placeholder stage before the first event arrives", () => {
    renderPane({ status: "sending" });
    expect(screen.getByRole("status")).toHaveTextContent("Preparing response");
  });

  it("reports nothing once the turn is finished", () => {
    renderPane({ status: "ready", activity: ACTIVITY });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("times a resumed turn from its real start, not from the redisplay", () => {
    renderPane({
      status: "sending",
      activity: ACTIVITY,
      activityStartedAt: Date.now() - 65_000,
    });
    expect(screen.getByRole("status")).toHaveTextContent("1m 05s");
  });

  it("offers a stop control that cancels the request", async () => {
    const user = userEvent.setup();
    const { onCancel } = renderPane({ status: "sending" });
    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("renders a failure with a retry action", async () => {
    const user = userEvent.setup();
    const error: WorkspaceError = {
      message:
        "Cannot connect to Ollama. Make sure Ollama is running and the configured model is available, or switch to Cloud.",
      detail: "Connection refused",
      retryable: true,
      scope: "chat",
    };
    const { onRetry, onDismissError } = renderPane({ error });

    const alert = screen.getByRole("alert");
    expect(within(alert).getByText(/Cannot connect to Ollama/)).toBeInTheDocument();
    expect(within(alert).getByText("Connection refused")).toBeInTheDocument();

    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);

    await user.click(within(alert).getByRole("button", { name: "Dismiss error" }));
    expect(onDismissError).toHaveBeenCalledTimes(1);
  });
});
