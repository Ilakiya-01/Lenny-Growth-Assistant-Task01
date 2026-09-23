import type { LLMMode } from "@/types";

import { cn } from "@/lib/cn";

type LLMModeToggleProps = {
  mode: LLMMode;
  onChange: (mode: LLMMode) => void;
  disabled?: boolean;
};

const OPTIONS: { value: LLMMode; label: string; hint: string }[] = [
  { value: "cloud", label: "Cloud", hint: "Anthropic" },
  { value: "ollama", label: "Ollama", hint: "Local model" },
];

/**
 * Provider selection for subsequent requests.
 *
 * The choice is always sent to the backend, which owns the credentials and the
 * provider construction; switching never changes the conversation, and the
 * backend never substitutes a different provider on its own.
 */
export function LLMModeToggle({ mode, onChange, disabled }: LLMModeToggleProps) {
  return (
    <div
      role="group"
      aria-label="LLM mode"
      className="inline-flex items-center gap-0.5 rounded-md border border-border bg-surface-muted p-0.5"
    >
      {OPTIONS.map((option) => {
        const isSelected = option.value === mode;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            disabled={disabled}
            aria-pressed={isSelected}
            title={`${option.label} — ${option.hint}`}
            className={cn(
              "flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60",
              isSelected
                ? "bg-surface text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                "h-1.5 w-1.5 rounded-full border",
                isSelected
                  ? "border-success bg-success"
                  : "border-muted-foreground/50 bg-transparent",
              )}
            />
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
