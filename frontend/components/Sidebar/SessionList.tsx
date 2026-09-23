import type { Session } from "@/types";

import { cn } from "@/lib/cn";

type SessionListProps = {
  sessions: Session[];
  selectedSessionId: string | null;
  onSelect: (sessionId: string) => void;
};

function formatUpdated(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) {
    return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function SessionList({ sessions, selectedSessionId, onSelect }: SessionListProps) {
  if (sessions.length === 0) {
    return (
      <p className="rounded-md bg-surface-muted px-3 py-4 text-xs text-muted-foreground">
        No conversations yet.
      </p>
    );
  }

  return (
    <nav aria-label="Sessions" className="min-h-0 flex-1">
      <h2 className="px-2 pb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Recent
      </h2>
      <ul className="flex min-h-0 flex-col gap-0.5 overflow-y-auto pr-0.5">
        {sessions.map((session) => {
          const isActive = session.id === selectedSessionId;
          return (
            <li key={session.id}>
              <button
                type="button"
                onClick={() => onSelect(session.id)}
                aria-current={isActive ? "true" : undefined}
                data-session-id={session.id}
                data-active={isActive ? "true" : "false"}
                className={cn(
                  "flex w-full flex-col gap-0.5 rounded-md border-l-2 px-2.5 py-2 text-left transition-colors",
                  isActive
                    ? "border-l-primary bg-primary/10 text-foreground"
                    : "border-l-transparent text-muted-foreground hover:bg-surface-muted hover:text-foreground",
                )}
              >
                <span className="truncate text-sm font-medium">{session.title}</span>
                <span className="truncate text-xs tabular-nums opacity-80">
                  {formatUpdated(session.updated_at)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
