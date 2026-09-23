"use client";

import { useCallback, useEffect, useRef } from "react";

import { AgentActivity } from "./AgentActivity";
import { Composer } from "./Composer";
import { EmptyState } from "./EmptyState";
import { ErrorNotice } from "./ErrorNotice";
import { MessageList } from "./MessageList";
import type { ChatMessage, WorkspaceError, WorkspaceStatus } from "@/lib/useWorkspace";
import type { ActivityEvent, LLMMode, Session } from "@/types";

/** Keep auto-scrolling only while the reader is already at the bottom. */
const NEAR_BOTTOM_PX = 96;

type ChatPaneProps = {
  session: Session | null;
  messages: ChatMessage[];
  status: WorkspaceStatus;
  activity: ActivityEvent[];
  /** Start time of the running turn, so elapsed survives a session switch. */
  activityStartedAt?: number | null;
  error: WorkspaceError | null;
  draft: string;
  llmMode: LLMMode;
  artifactMessageId: string | null;
  onOpenSessions: () => void;
  onDraftChange: (value: string) => void;
  onSend: (text: string) => void;
  onCancel: () => void;
  onRetry: () => void;
  onDismissError: () => void;
  onLLMModeChange: (mode: LLMMode) => void;
  onOpenArtifact: (messageId: string) => void;
};

export function ChatPane({
  session,
  messages,
  status,
  activity,
  activityStartedAt,
  error,
  draft,
  llmMode,
  artifactMessageId,
  onOpenSessions,
  onDraftChange,
  onSend,
  onCancel,
  onRetry,
  onDismissError,
  onLLMModeChange,
  onOpenArtifact,
}: ChatPaneProps) {
  const sending = status === "sending";
  const hasSession = session !== null;
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const nearBottomRef = useRef(true);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  function handleScroll() {
    const element = scrollRef.current;
    if (!element) return;
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    nearBottomRef.current = distance <= NEAR_BOTTOM_PX;
  }

  useEffect(() => {
    const element = scrollRef.current;
    if (!element || !nearBottomRef.current) return;
    element.scrollTop = element.scrollHeight;
  }, [messages, activity, sending]);

  // A new conversation starts with the cursor where the user types.
  useEffect(() => {
    if (messages.length === 0) composerRef.current?.focus();
  }, [session?.id, messages.length]);

  const handlePick = useCallback(
    (prompt: string) => {
      onDraftChange(prompt);
      composerRef.current?.focus();
    },
    [onDraftChange],
  );

  const handleSend = useCallback(() => {
    onSend(draft);
  }, [draft, onSend]);

  const showError = error;

  return (
    <section
      aria-label="Conversation"
      className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-background"
    >
      <header className="flex min-h-14 shrink-0 items-center gap-3 border-b border-border bg-surface px-5">
        <button
          type="button"
          onClick={onOpenSessions}
          aria-label="Show conversations"
          className="-ml-2 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface-muted hover:text-foreground md:hidden"
        >
          <svg
            viewBox="0 0 16 16"
            aria-hidden="true"
            focusable="false"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          >
            <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" />
          </svg>
        </button>
        <div className="min-w-0">
          <h1 className="truncate text-sm font-semibold tracking-tight">
            {session?.title ?? "New conversation"}
          </h1>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {sending
              ? "Working on your request"
              : hasSession
                ? "Grounded answers, essays and artifacts"
                : "Create a conversation to start"}
          </p>
        </div>
      </header>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="min-h-0 flex-1 overflow-y-auto px-5 py-6"
      >
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-5">
          {showError ? (
            <ErrorNotice error={showError} onRetry={onRetry} onDismiss={onDismissError} />
          ) : null}

          {messages.length === 0 ? (
            <EmptyState onPick={handlePick} disabled={sending || !hasSession} />
          ) : (
            <MessageList
              messages={messages}
              artifactMessageId={artifactMessageId}
              onOpenArtifact={onOpenArtifact}
            />
          )}

          <AgentActivity
            activity={activity}
            active={sending}
            startedAt={activityStartedAt}
          />
        </div>
      </div>

      <div className="shrink-0 border-t border-border bg-surface px-5 py-3">
        <div className="mx-auto w-full max-w-3xl">
          <Composer
            value={draft}
            onChange={onDraftChange}
            onSend={handleSend}
            onCancel={onCancel}
            sending={sending}
            disabled={!hasSession || status === "initialising"}
            llmMode={llmMode}
            onLLMModeChange={onLLMModeChange}
            inputRef={composerRef}
          />
        </div>
      </div>
    </section>
  );
}
