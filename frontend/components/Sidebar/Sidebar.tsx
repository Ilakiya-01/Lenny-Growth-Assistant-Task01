import type { Session } from "@/types";

import { NewChatButton } from "./NewChatButton";
import { SessionList } from "./SessionList";

type SidebarProps = {
  sessions: Session[];
  selectedSessionId: string | null;
  isCreating: boolean;
  onCreate: () => void;
  onSelect: (sessionId: string) => void;
};

export function Sidebar({
  sessions,
  selectedSessionId,
  isCreating,
  onCreate,
  onSelect,
}: SidebarProps) {
  return (
    <div className="flex h-full min-h-0 flex-col gap-4 bg-surface px-3 py-4">
      <div className="flex items-start justify-between gap-2 px-1">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold tracking-tight">
            Lenny Growth Assistant
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Grounded in Lenny&apos;s Podcast
          </p>
        </div>
      </div>

      <NewChatButton onClick={onCreate} isCreating={isCreating} />

      <SessionList
        sessions={sessions}
        selectedSessionId={selectedSessionId}
        onSelect={onSelect}
      />
    </div>
  );
}
