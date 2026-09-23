import type { WorkspaceError } from "@/lib/useWorkspace";

type ErrorNoticeProps = {
  error: WorkspaceError;
  onRetry?: () => void;
  onDismiss?: () => void;
};

/**
 * Inline failure state.
 *
 * The text is whatever the backend considered safe to show (or the frontend's
 * own connectivity copy): never a stack trace, a prompt or a credential.
 */
export function ErrorNotice({ error, onRetry, onDismiss }: ErrorNoticeProps) {
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-md border border-danger/30 bg-danger/5 px-3.5 py-2.5"
    >
      <svg
        viewBox="0 0 16 16"
        aria-hidden="true"
        focusable="false"
        className="mt-0.5 h-4 w-4 shrink-0 text-danger"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      >
        <circle cx="8" cy="8" r="6.25" />
        <path d="M8 5v3.75M8 11h.01" />
      </svg>

      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-danger">{error.message}</p>
        {error.detail ? (
          <p className="mt-0.5 text-xs text-muted-foreground">{error.detail}</p>
        ) : null}
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="rounded-md border border-danger/40 px-2.5 py-1 text-xs font-medium text-danger transition-colors hover:bg-danger/10"
          >
            Retry
          </button>
        ) : null}
        {onDismiss ? (
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss error"
            className="rounded-md px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-surface-muted hover:text-foreground"
          >
            Dismiss
          </button>
        ) : null}
      </div>
    </div>
  );
}
