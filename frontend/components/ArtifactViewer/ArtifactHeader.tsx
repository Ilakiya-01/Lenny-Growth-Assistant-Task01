"use client";

import { artifactTypeLabel } from "@/lib/artifacts";
import { cn } from "@/lib/cn";

export type ArtifactViewMode = "preview" | "code";

type ArtifactHeaderProps = {
  title: string;
  type: string;
  view: ArtifactViewMode;
  onViewChange: (view: ArtifactViewMode) => void;
  copied: boolean;
  onCopy: () => void;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
  onClose: () => void;
};

const TABS: { id: ArtifactViewMode; label: string }[] = [
  { id: "preview", label: "Preview" },
  { id: "code", label: "Code" },
];

function IconButton({
  label,
  pressed,
  onClick,
  children,
}: {
  label: string;
  pressed?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      className={cn(
        "inline-flex h-7 w-7 items-center justify-center rounded-md border border-transparent text-muted-foreground transition-colors hover:bg-surface-muted hover:text-foreground",
        pressed && "border-border bg-surface-muted text-foreground",
      )}
    >
      {children}
    </button>
  );
}

export function ArtifactHeader({
  title,
  type,
  view,
  onViewChange,
  copied,
  onCopy,
  fullscreen,
  onToggleFullscreen,
  onClose,
}: ArtifactHeaderProps) {
  return (
    <header className="flex shrink-0 flex-col gap-2 border-b border-border bg-surface px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-center gap-2">
        <h2 className="truncate text-sm font-semibold tracking-tight" title={title}>
          {title || "Untitled artifact"}
        </h2>
        <span className="shrink-0 rounded border border-border bg-surface-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          {artifactTypeLabel(type)}
        </span>
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        <div role="tablist" aria-label="Artifact view" className="flex rounded-md border border-border p-0.5">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`artifact-tab-${tab.id}`}
              aria-selected={view === tab.id}
              aria-controls="artifact-panel"
              tabIndex={view === tab.id ? 0 : -1}
              onClick={() => onViewChange(tab.id)}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                view === tab.id
                  ? "bg-foreground text-background"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <IconButton label={copied ? "Copied" : "Copy source"} onClick={onCopy}>
          <svg
            viewBox="0 0 16 16"
            aria-hidden="true"
            focusable="false"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            {copied ? (
              <path d="M3.5 8.5 6.5 11.5 12.5 5" />
            ) : (
              <>
                <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
                <path d="M10.5 5.5v-2a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2" />
              </>
            )}
          </svg>
        </IconButton>

        <IconButton
          label={fullscreen ? "Exit full screen" : "Full screen"}
          pressed={fullscreen}
          onClick={onToggleFullscreen}
        >
          <svg
            viewBox="0 0 16 16"
            aria-hidden="true"
            focusable="false"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            {fullscreen ? (
              <path d="M6 2.5V6H2.5M10 13.5V10h3.5M2.5 10H6v3.5M13.5 6H10V2.5" />
            ) : (
              <path d="M2.5 6V2.5H6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10" />
            )}
          </svg>
        </IconButton>

        <IconButton label="Close artifact" onClick={onClose}>
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
            <path d="M4 4l8 8M12 4l-8 8" />
          </svg>
        </IconButton>
      </div>
    </header>
  );
}
