"use client";

import { useEffect, useState } from "react";

import type { ActivityEvent } from "@/types";

type AgentActivityProps = {
  activity: ActivityEvent[];
  active: boolean;
  /** When the running turn started, so the timer survives a session switch. */
  startedAt?: number | null;
};

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}m ${String(rest).padStart(2, "0")}s`;
}

/**
 * The agent's high-level progress, and nothing else.
 *
 * The events come from the backend's fixed activity vocabulary: no prompts, no
 * model reasoning, no tool arguments. The elapsed time is real, so a slow local
 * model is visible without inventing a percentage.
 */export function AgentActivity({ activity, active, startedAt }: AgentActivityProps) {
  const [elapsed, setElapsed] = useState(0);
  const [wasActive, setWasActive] = useState(active);

  // The timer restarts for every run, so the previous run's total is cleared
  // when activity begins.
  if (wasActive !== active) {
    setWasActive(active);
    setElapsed(0);
  }

  useEffect(() => {
    if (!active) return;
    // A turn that started in another session keeps its own elapsed time.
    const started = startedAt ?? Date.now();
    const tick = () => setElapsed(Math.max(0, Math.round((Date.now() - started) / 1000)));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [active, startedAt]);

  if (!active) return null;

  const latest = activity[activity.length - 1];

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-2.5 rounded-md border border-border bg-surface-muted px-3 py-2 text-xs text-muted-foreground"
    >
      <span className="relative flex h-3.5 w-3.5 shrink-0" aria-hidden="true">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/40 motion-reduce:hidden" />
        <span className="relative inline-flex h-3.5 w-3.5 rounded-full bg-primary/70" />
      </span>
      <span className="truncate font-medium text-foreground">
        {latest?.message ?? "Preparing response"}
      </span>
      {elapsed >= 3 ? (
        <span className="ml-auto shrink-0 tabular-nums">{formatElapsed(elapsed)}</span>
      ) : null}
    </div>
  );
}
