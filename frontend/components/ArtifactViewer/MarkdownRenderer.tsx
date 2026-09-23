import { Markdown } from "@/components/Markdown";
import type { Artifact } from "@/types";

/** Markdown artifacts are rendered as markup-safe React nodes, never as HTML. */
export function MarkdownRenderer({ artifact }: { artifact: Artifact }) {
  return (
    <div className="h-full overflow-y-auto bg-surface px-6 py-5">
      <article className="mx-auto max-w-[72ch]">
        <Markdown>{artifact.content}</Markdown>
      </article>
    </div>
  );
}
