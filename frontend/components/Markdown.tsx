import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/cn";

type MarkdownProps = {
  children: string;
  className?: string;
};

/**
 * Safe Markdown rendering for assistant replies and Markdown artifacts.
 *
 * `react-markdown` builds elements from the Markdown AST and does not render
 * raw HTML, so model output cannot inject markup into the application DOM.
 */
export function Markdown({ children, className }: MarkdownProps) {
  return (
    <div className={cn("markdown", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node: _node, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
