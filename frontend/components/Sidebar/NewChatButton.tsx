type NewChatButtonProps = {
  onClick: () => void;
  isCreating: boolean;
};

export function NewChatButton({ onClick, isCreating }: NewChatButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isCreating}
      aria-busy={isCreating}
      className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 active:bg-primary/80 disabled:cursor-not-allowed disabled:opacity-60"
    >
      <svg
        viewBox="0 0 16 16"
        aria-hidden="true"
        focusable="false"
        className="h-4 w-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
      >
        <path d="M8 3.5v9M3.5 8h9" />
      </svg>
      {isCreating ? "Creating…" : "New chat"}
    </button>
  );
}
