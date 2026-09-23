import { Message } from "./Message";
import type { ChatMessage } from "@/lib/useWorkspace";

type MessageListProps = {
  messages: ChatMessage[];
  artifactMessageId: string | null;
  onOpenArtifact: (messageId: string) => void;
};

export function MessageList({ messages, artifactMessageId, onOpenArtifact }: MessageListProps) {
  if (messages.length === 0) return null;

  return (
    <ol className="flex flex-col gap-6" aria-label="Conversation">
      {messages.map((message) => (
        <Message
          key={message.id}
          message={message}
          isArtifactOpen={artifactMessageId === message.id}
          onOpenArtifact={onOpenArtifact}
        />
      ))}
    </ol>
  );
}
