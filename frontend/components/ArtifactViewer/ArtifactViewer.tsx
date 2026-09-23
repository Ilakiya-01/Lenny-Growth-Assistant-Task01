"use client";

import { useCallback, useEffect, useState } from "react";

import { ArtifactErrorBoundary } from "./ArtifactErrorBoundary";
import { ArtifactHeader, type ArtifactViewMode } from "./ArtifactHeader";
import { HtmlRenderer } from "./HtmlRenderer";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { artifactError, artifactSource, isHtmlArtifact, isMarkdownArtifact } from "@/lib/artifacts";
import { cn } from "@/lib/cn";
import type { Artifact } from "@/types";

type ArtifactViewerProps = {
  artifact: Artifact;
  onClose: () => void;
};

type CopyState = "idle" | "copied" | "failed";

function PreviewBody({ artifact }: { artifact: Artifact }) {
  if (isMarkdownArtifact(artifact.type)) return <MarkdownRenderer artifact={artifact} />;
  if (isHtmlArtifact(artifact.type)) return <HtmlRenderer artifact={artifact} />;
  return null;
}

/**
 * The right-hand artifact panel.
 *
 * It only exists while an artifact is open. On a desktop workspace it takes
 * roughly 40% of the width and scrolls independently of the conversation; on a
 * narrow viewport the same panel overlays the chat instead of squeezing it.
 */
export function ArtifactViewer({ artifact, onClose }: ArtifactViewerProps) {
  const [view, setView] = useState<ArtifactViewMode>("preview");
  const [fullscreen, setFullscreen] = useState(false);
  const [copyState, setCopyState] = useState<CopyState>("idle");

  const problem = artifactError(artifact);
  const source = artifactSource(artifact);
  const resetKey = `${artifact.type}:${artifact.title}:${source.length}`;

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      if (fullscreen) setFullscreen(false);
      else onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [fullscreen, onClose]);

  useEffect(() => {
    if (copyState === "idle") return;
    const timer = window.setTimeout(() => setCopyState("idle"), 2000);
    return () => window.clearTimeout(timer);
  }, [copyState]);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(source);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }, [source]);

  return (
    <aside
      aria-label="Artifact viewer"
      className={cn(
        "fixed inset-0 z-40 flex flex-col bg-surface shadow-xl",
        "lg:static lg:z-auto lg:w-[40%] lg:min-w-[22rem] lg:shrink-0 lg:border-l lg:border-border lg:shadow-none",
        fullscreen && "lg:w-full lg:min-w-0",
      )}
    >
      <ArtifactHeader
        title={artifact.title}
        type={artifact.type}
        view={view}
        onViewChange={setView}
        copied={copyState === "copied"}
        onCopy={() => void handleCopy()}
        fullscreen={fullscreen}
        onToggleFullscreen={() => setFullscreen((current) => !current)}
        onClose={onClose}
      />

      <div id="artifact-panel" role="tabpanel" aria-labelledby={`artifact-tab-${view}`} className="min-h-0 flex-1">
        {view === "code" ? (
          <pre className="h-full overflow-auto bg-[#101014] px-4 py-3 font-mono text-xs leading-relaxed text-zinc-100">
            <code>{source || "// This artifact has no source."}</code>
          </pre>
        ) : problem ? (
          <div className="flex h-full items-center justify-center p-6 text-center">
            <div className="max-w-sm">
              <p className="text-sm font-medium text-foreground">No preview available</p>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{problem}</p>
            </div>
          </div>
        ) : (
          <ArtifactErrorBoundary resetKey={resetKey}>
            <div className="h-full">
              <PreviewBody artifact={artifact} />
            </div>
          </ArtifactErrorBoundary>
        )}
      </div>

      {copyState === "failed" ? (
        <p role="status" className="shrink-0 border-t border-border px-3 py-1.5 text-xs text-muted-foreground">
          Copying is blocked in this browser. Select the source under Code instead.
        </p>
      ) : null}
    </aside>
  );
}
