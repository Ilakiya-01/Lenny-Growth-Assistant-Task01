import type { Artifact } from "@/types";

export const ARTIFACT_TYPE_MARKDOWN = "markdown";
export const ARTIFACT_TYPE_HTML = "html";
export const ARTIFACT_TYPE_HTML_CSS = "html_css";

const HTML_TYPES = new Set([ARTIFACT_TYPE_HTML, ARTIFACT_TYPE_HTML_CSS]);
const SUPPORTED_TYPES = new Set([ARTIFACT_TYPE_MARKDOWN, ...HTML_TYPES]);

export function isHtmlArtifact(type: string | undefined | null): boolean {
  return HTML_TYPES.has((type ?? "").trim().toLowerCase());
}

export function isMarkdownArtifact(type: string | undefined | null): boolean {
  return (type ?? "").trim().toLowerCase() === ARTIFACT_TYPE_MARKDOWN;
}

export function artifactTypeLabel(type: string | undefined | null): string {
  const normalized = (type ?? "").trim().toLowerCase();
  if (HTML_TYPES.has(normalized)) return "HTML/CSS";
  if (normalized === ARTIFACT_TYPE_MARKDOWN) return "Markdown";
  return normalized ? normalized.toUpperCase() : "Unknown";
}

/**
 * Why an artifact cannot be rendered, or `null` when it can.
 *
 * A malformed artifact is reported inside the viewer: the conversation stays
 * visible and usable, because a bad artifact is not a broken session.
 */
export function artifactError(artifact: Artifact | null | undefined): string | null {
  if (!artifact || typeof artifact !== "object") {
    return "This artifact could not be read.";
  }
  const type = (artifact.type ?? "").trim().toLowerCase();
  if (!type) return "This artifact has no type and cannot be rendered.";
  if (!SUPPORTED_TYPES.has(type)) {
    return `Unsupported artifact type "${artifact.type}". Only Markdown and HTML/CSS artifacts can be rendered.`;
  }
  if (typeof artifact.content !== "string" || !artifact.content.trim()) {
    return "This artifact is empty, so there is nothing to preview. The source is still available under Code.";
  }
  return null;
}

/**
 * The document handed to the sandboxed iframe.
 *
 * Generated HTML is untrusted, so it is never inserted into the application
 * DOM: it becomes the `srcDoc` of an iframe that has no same-origin access to
 * the parent, and a Content-Security-Policy that blocks every network request.
 * A closing style tag inside the stylesheet is stripped so the artifact cannot
 * break out of the `<style>` element it is placed in.
 */
export function buildArtifactDocument(artifact: Artifact): string {
  const css = (artifact.css ?? "").replace(/<\/style/gi, "");
  const style = css.trim() ? `<style>${css}</style>` : "";
  const policy =
    "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; " +
    "img-src data:; font-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; " +
    "base-uri 'none'; form-action 'none'\">";
  const injection = `${policy}${style}`;
  const body = artifact.content ?? "";
  const isDocument = /<html[\s>]/i.test(body) || /<!doctype\s+html/i.test(body);

  if (!isDocument) {
    return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">${injection}</head><body>${body}</body></html>`;
  }

  // A complete document keeps its own structure. The policy and stylesheet are
  // injected after an existing head or body tag so the doctype stays first.
  if (/<head[^>]*>/i.test(body)) return body.replace(/<head[^>]*>/i, (tag) => `${tag}${injection}`);
  if (/<body[^>]*>/i.test(body)) return body.replace(/<body[^>]*>/i, (tag) => `${tag}${injection}`);
  return `${injection}${body}`;
}

/** Everything the Code view shows for an artifact. */
export function artifactSource(artifact: Artifact): string {
  if (!isHtmlArtifact(artifact.type)) return artifact.content ?? "";
  if (!artifact.css?.trim()) return artifact.content ?? "";
  const document = artifact.content ?? "";
  if (/<\/head>/i.test(document)) {
    return document.replace(/<\/head>/i, `<style>\n${artifact.css}\n</style>\n</head>`);
  }
  return `<!-- stylesheet -->\n<style>\n${artifact.css}\n</style>\n\n${document}`;
}
