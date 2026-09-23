"use client";

import { useMemo } from "react";

import { buildArtifactDocument } from "@/lib/artifacts";
import type { Artifact } from "@/types";

/**
 * Renders generated HTML/CSS inside an isolated iframe.
 *
 * The artifact is untrusted model output, so it never becomes part of the
 * application DOM. `srcDoc` plus `sandbox="allow-scripts"` gives it an opaque
 * origin: it cannot reach the parent document, the API, cookies or storage. The
 * injected Content-Security-Policy additionally blocks every network request,
 * so a generated page cannot call Supabase, Anthropic, Ollama or anything else.
 */
export function HtmlRenderer({ artifact }: { artifact: Artifact }) {
  const document = useMemo(() => buildArtifactDocument(artifact), [artifact]);

  return (
    <div className="flex h-full flex-col bg-surface">
      <iframe
        title={`${artifact.title || "Artifact"} preview`}
        srcDoc={document}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        className="h-full w-full flex-1 border-0 bg-white"
      />
      <p className="shrink-0 border-t border-border bg-surface-muted px-3 py-1.5 text-[11px] text-muted-foreground">
        Rendered in an isolated sandbox with network access disabled.
      </p>
    </div>
  );
}
