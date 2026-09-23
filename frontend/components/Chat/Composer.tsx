"use client";

import { useEffect, useId, useRef, type RefObject } from "react";

import { LLMModeToggle } from "@/components/LLMSelector/LLMModeToggle";
import { cn } from "@/lib/cn";
import type { LLMMode } from "@/types";

const MAX_LENGTH = 8000;
const MAX_HEIGHT = 208;

type ComposerProps = {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onCancel: () => void;
  sending: boolean;
  disabled: boolean;
  llmMode: LLMMode;
  onLLMModeChange: (mode: LLMMode) => void;
  inputRef?: RefObject<HTMLTextAreaElement | null>;
};

export function Composer({
  value,
  onChange,
  onSend,
  onCancel,
  sending,
  disabled,
  llmMode,
  onLLMModeChange,
  inputRef,
}: ComposerProps) {
  const id = useId();
  const fallbackRef = useRef<HTMLTextAreaElement | null>(null);
  const textarea = inputRef ?? fallbackRef;
  const canSend = value.trim().length > 0 && !disabled && !sending;

  useEffect(() => {
    const element = textarea.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, MAX_HEIGHT)}px`;
  }, [value, textarea]);

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter inserts a newline; an IME composition is left alone.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (canSend) onSend();
  }

  return (
    <div className="rounded-lg border border-border bg-surface p-2 shadow-sm focus-within:border-primary/50">
      <label htmlFor={id} className="sr-only">
        Message
      </label>
      <textarea
        id={id}
        ref={textarea}
        rows={1}
        value={value}
        maxLength={MAX_LENGTH}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={
          disabled
            ? "Select or create a conversation to start"
            : "Ask about Lenny's transcripts, request an essay, or generate an artifact…"
        }
        className="max-h-52 w-full resize-none bg-transparent px-2 py-1.5 text-sm leading-relaxed outline-none placeholder:text-muted-foreground/70 disabled:cursor-not-allowed"
      />

      <div className="mt-1 flex items-center justify-between gap-3 px-1">
        <div className="flex min-w-0 items-center gap-2">
          <LLMModeToggle mode={llmMode} onChange={onLLMModeChange} disabled={sending} />
          <span className="hidden truncate text-xs text-muted-foreground sm:inline">
            {sending ? "Working…" : "Enter to send · Shift+Enter for a new line"}
          </span>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {sending ? (
            <button
              type="button"
              onClick={onCancel}
              className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-surface-muted hover:text-foreground"
            >
              Stop
            </button>
          ) : null}
          <button
            type="button"
            onClick={onSend}
            disabled={!canSend}
            aria-disabled={!canSend}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3.5 py-1.5 text-sm font-medium transition-colors",
              canSend
                ? "bg-primary text-primary-foreground hover:bg-primary/90 active:bg-primary/80"
                : "cursor-not-allowed bg-surface-muted text-muted-foreground",
            )}
          >
            {sending ? "Sending" : "Send"}
            <svg
              viewBox="0 0 16 16"
              aria-hidden="true"
              focusable="false"
              className="h-3.5 w-3.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
