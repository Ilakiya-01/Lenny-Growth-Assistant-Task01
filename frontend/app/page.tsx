"use client";

import { useCallback, useState } from "react";

import { ArtifactViewer } from "@/components/ArtifactViewer/ArtifactViewer";
import { ChatPane } from "@/components/Chat/ChatPane";
import { Sidebar } from "@/components/Sidebar/Sidebar";
import { cn } from "@/lib/cn";
import { useWorkspace } from "@/lib/useWorkspace";

/**
 * The workspace: Sidebar | Chat | Artifact Viewer.
 *
 * Every value comes from {@link useWorkspace}; this component only lays the
 * three regions out and adapts them for a narrow viewport.
 */
export default function WorkspacePage() {
  const workspace = useWorkspace();
  const [creating, setCreating] = useState(false);
  const [navOpen, setNavOpen] = useState(false);

  const handleCreate = useCallback(async () => {
    setCreating(true);
    try {
      await workspace.createSession();
      setNavOpen(false);
    } finally {
      setCreating(false);
    }
  }, [workspace]);

  const handleSelect = useCallback(
    (sessionId: string) => {
      workspace.selectSession(sessionId);
      setNavOpen(false);
    },
    [workspace],
  );

  const handleRetry = useCallback(() => {
    if (workspace.error?.scope === "chat") workspace.retry();
    else workspace.refresh();
  }, [workspace]);

  const { artifactView } = workspace;

  return (
    <main className="flex h-dvh w-full overflow-hidden">
      {navOpen ? (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setNavOpen(false)}
          className="fixed inset-0 z-40 bg-foreground/30 md:hidden"
        />
      ) : null}

      <div
        className={cn(
          "fixed inset-y-0 left-0 z-50 w-72 shrink-0 border-r border-border transition-transform duration-200 md:static md:z-auto md:w-64 md:translate-x-0 md:shadow-none lg:w-72",
          navOpen ? "translate-x-0 shadow-xl" : "-translate-x-full",
        )}
      >
        <Sidebar
          sessions={workspace.sessions}
          selectedSessionId={workspace.selectedSessionId}
          isCreating={creating}
          onCreate={() => void handleCreate()}
          onSelect={handleSelect}
        />
      </div>

      <ChatPane
        session={workspace.selectedSession}
        messages={workspace.messages}
        status={workspace.status}
        activity={workspace.activity}
        activityStartedAt={workspace.activityStartedAt}
        error={workspace.error}
        draft={workspace.draft}
        llmMode={workspace.llmMode}
        artifactMessageId={artifactView?.messageId ?? null}
        onOpenSessions={() => setNavOpen(true)}
        onDraftChange={workspace.setDraft}
        onSend={(text) => void workspace.send(text)}
        onCancel={workspace.cancel}
        onRetry={handleRetry}
        onDismissError={workspace.dismissError}
        onLLMModeChange={workspace.setLLMMode}
        onOpenArtifact={workspace.openArtifact}
      />

      {artifactView ? (
        <ArtifactViewer
          key={`${artifactView.messageId}:${artifactView.artifact.title}`}
          artifact={artifactView.artifact}
          onClose={workspace.closeArtifact}
        />
      ) : null}
    </main>
  );
}
