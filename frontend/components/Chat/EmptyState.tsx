type PromptCard = {
  label: string;
  prompt: string;
  description: string;
};

const PROMPT_CARDS: PromptCard[] = [
  {
    label: "Ask Lenny",
    prompt: "What does Lenny say about finding product-market fit?",
    description: "An answer grounded in the podcast transcripts.",
  },
  {
    label: "Write with Ship30for30",
    prompt: "Write an essay about building products users love.",
    description: "A skimmable ~1,250-word article.",
  },
  {
    label: "Build an artifact",
    prompt: "Create a simple landing page for a SaaS product.",
    description: "A rendered artifact you can inspect and copy.",
  },
];

type EmptyStateProps = {
  onPick: (prompt: string) => void;
  disabled?: boolean;
};

/**
 * Welcome state for an empty conversation.
 *
 * A card fills the composer; it never sends a request by itself, so nothing is
 * generated until the user decides to.
 */
export function EmptyState({ onPick, disabled }: EmptyStateProps) {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 py-10">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">
          What are you building today?
        </h2>
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
          Ask a question grounded in 303 episodes of Lenny&apos;s Podcast, draft a
          Ship30for30 article, or generate an artifact.
        </p>
      </div>

      <ul className="grid gap-3 sm:grid-cols-3">
        {PROMPT_CARDS.map((card) => (
          <li key={card.label}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onPick(card.prompt)}
              className="flex h-full w-full flex-col gap-1.5 rounded-lg border border-border bg-surface p-3.5 text-left transition-colors hover:border-primary/40 hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span className="text-xs font-semibold uppercase tracking-wide text-primary">
                {card.label}
              </span>
              <span className="text-sm font-medium leading-snug">&ldquo;{card.prompt}&rdquo;</span>
              <span className="mt-auto text-xs text-muted-foreground">{card.description}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
