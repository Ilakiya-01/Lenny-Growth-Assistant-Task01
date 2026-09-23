import { Markdown } from "@/components/Markdown";
import { artifactTypeLabel } from "@/lib/artifacts";
import { cn } from "@/lib/cn";
import type { ChatMessage } from "@/lib/useWorkspace";
import type { ChatMetrics, Source } from "@/types";

type MessageProps = {
  message: ChatMessage;
  isArtifactOpen: boolean;
  onOpenArtifact: (messageId: string) => void;
};

function metricsLabel(metrics: ChatMetrics): string | null {
  const words = typeof metrics.word_count === "number" ? metrics.word_count : null;
  if (!words) return null;
  const minutes =
    typeof metrics.reading_time_minutes === "number" ? metrics.reading_time_minutes : null;
  const count = `${words.toLocaleString()} words`;
  return minutes ? `${count} • ${minutes} min read` : count;
}

function SourceList({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return null;
  return (
    <details className="mt-3 rounded-md border border-border bg-surface-muted/60 px-3 py-2">
      <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
        Sources ({sources.length})
      </summary>
      <ul className="mt-2 flex flex-col gap-2">
        {sources.map((source, index) => (
          <li key={`${source.episode_id}-${source.chunk_index ?? index}`} className="text-xs">
            <p className="font-medium text-foreground">{source.title ?? source.episode_id}</p>
            <p className="text-muted-foreground">
              {[source.guest, source.publish_date].filter(Boolean).join(" · ")}
            </p>
            {source.excerpt ? (
              <p className="mt-1 line-clamp-3 text-muted-foreground">{source.excerpt}</p>
            ) : null}
            {source.youtube_url ? (
              <a
                href={source.youtube_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary underline underline-offset-2"
              >
                Watch episode
              </a>
            ) : null}
          </li>
        ))}
      </ul>
    </details>
  );
}

export function Message({ message, isArtifactOpen, onOpenArtifact }: MessageProps) {
  const isUser = message.role === "user";
  const label = metricsLabel(message.metrics);

  if (isUser) {
    return (
      <li className="flex justify-end" data-role="user">
        <div className="max-w-[85%] rounded-lg rounded-br-sm border border-border bg-primary/10 px-3.5 py-2.5">
          <span className="sr-only">You said:</span>
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.content}</p>
        </div>
      </li>
    );
  }

  return (
    <li className="flex flex-col gap-1" data-role="assistant">
      <span className="sr-only">Assistant replied:</span>
      <div className="max-w-[76ch]">
        <Markdown>{message.content}</Markdown>
      </div>

      {label ? (
        <p className="mt-1 text-xs tabular-nums text-muted-foreground">{label}</p>
      ) : null}

      {message.artifact ? (
        <button
          type="button"
          onClick={() => onOpenArtifact(message.id)}
          aria-pressed={isArtifactOpen}
          className={cn(
            "mt-2 inline-flex w-fit max-w-full items-center gap-2 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
            isArtifactOpen
              ? "border-primary/40 bg-primary/10 text-foreground"
              : "border-border bg-surface text-muted-foreground hover:bg-surface-muted hover:text-foreground",
          )}
        >
          <svg
            viewBox="0 0 16 16"
            aria-hidden="true"
            focusable="false"
            className="h-3.5 w-3.5 shrink-0"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <rect x="2" y="2.5" width="12" height="11" rx="1.5" />
            <path d="M2 6h12" />
          </svg>
          <span className="truncate">
            {isArtifactOpen ? "Viewing" : "Open"} {message.artifact.title || "artifact"}
          </span>
          <span className="shrink-0 rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
            {artifactTypeLabel(message.artifact.type)}
          </span>
        </button>
      ) : null}

      <SourceList sources={message.sources} />
    </li>
  );
}
