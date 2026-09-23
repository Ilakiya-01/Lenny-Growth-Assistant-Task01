import { describe, expect, it } from "vitest";

import {
  artifactError,
  artifactSource,
  artifactTypeLabel,
  buildArtifactDocument,
  isHtmlArtifact,
  isMarkdownArtifact,
} from "@/lib/artifacts";
import type { Artifact } from "@/types";

const markdown: Artifact = {
  type: "markdown",
  title: "Essay",
  content: "# Heading\n\nBody text.",
};

const page: Artifact = {
  type: "html_css",
  title: "Landing page",
  content: '<section class="hero"><h1>Ship it</h1></section>',
  css: ".hero { padding: 2rem; }",
};

describe("artifact type helpers", () => {
  it("recognises both HTML artifact types", () => {
    expect(isHtmlArtifact("html")).toBe(true);
    expect(isHtmlArtifact("html_css")).toBe(true);
    expect(isHtmlArtifact("HTML_CSS ")).toBe(true);
    expect(isHtmlArtifact("markdown")).toBe(false);
    expect(isMarkdownArtifact("Markdown")).toBe(true);
  });

  it("labels types for the viewer header", () => {
    expect(artifactTypeLabel("html_css")).toBe("HTML/CSS");
    expect(artifactTypeLabel("markdown")).toBe("Markdown");
    expect(artifactTypeLabel("pdf")).toBe("PDF");
    expect(artifactTypeLabel("")).toBe("Unknown");
  });
});

describe("artifactError", () => {
  it("accepts a renderable artifact", () => {
    expect(artifactError(markdown)).toBeNull();
    expect(artifactError(page)).toBeNull();
  });

  it("reports a missing artifact", () => {
    expect(artifactError(null)).toBe("This artifact could not be read.");
  });

  it("reports a missing or unsupported type", () => {
    expect(artifactError({ title: "x", content: "y" } as Artifact)).toMatch(/no type/);
    expect(artifactError({ type: "pdf", title: "x", content: "y" } as Artifact)).toMatch(
      /Unsupported artifact type "pdf"/,
    );
  });

  it("reports empty content but leaves the source available", () => {
    expect(artifactError({ type: "markdown", title: "x", content: "  " })).toMatch(
      /empty[\s\S]*Code/,
    );
  });
});

describe("buildArtifactDocument", () => {
  it("wraps a fragment in a document that starts with the doctype", () => {
    const document = buildArtifactDocument(page);
    expect(document.startsWith("<!doctype html>")).toBe(true);
    expect(document).toContain("<body><section class=\"hero\">");
  });

  it("blocks every network request inside the sandbox", () => {
    const document = buildArtifactDocument(page);
    expect(document).toContain('http-equiv="Content-Security-Policy"');
    expect(document).toContain("default-src 'none'");
    expect(document).toContain("base-uri 'none'");
    expect(document).toContain("form-action 'none'");
  });

  it("inlines the stylesheet and cannot be broken out of it", () => {
    const hostile: Artifact = {
      type: "html_css",
      title: "Hostile",
      content: "<p>hi</p>",
      css: "body { color: red; }</style><script>steal()</script>",
    };
    const document = buildArtifactDocument(hostile);
    expect(document).toContain("body { color: red; }");
    // The closing tag is removed, so the artifact cannot escape the <style>.
    expect(document).not.toContain("</style><script>steal()</script>");
    expect(document.match(/<\/style>/g)).toHaveLength(1);
  });

  it("keeps a complete document's own structure", () => {
    const full: Artifact = {
      type: "html",
      title: "Full",
      content: '<!doctype html><html><head><title>t</title></head><body><p>hi</p></body></html>',
      css: "p { margin: 0; }",
    };
    const document = buildArtifactDocument(full);
    expect(document.startsWith("<!doctype html>")).toBe(true);
    expect(document).toContain('<head><meta http-equiv="Content-Security-Policy"');
    expect(document).toContain("<title>t</title>");
  });
});

describe("artifactSource", () => {
  it("returns Markdown unchanged", () => {
    expect(artifactSource(markdown)).toBe(markdown.content);
  });

  it("merges the stylesheet into the document head", () => {
    const source = artifactSource({
      type: "html",
      title: "t",
      content: "<html><head></head><body></body></html>",
      css: "body { margin: 0; }",
    });
    expect(source).toContain("<style>\nbody { margin: 0; }\n</style>\n</head>");
  });

  it("prepends a labelled stylesheet when there is no head", () => {
    const source = artifactSource(page);
    expect(source.startsWith("<!-- stylesheet -->")).toBe(true);
    expect(source).toContain(".hero { padding: 2rem; }");
    expect(source).toContain('<section class="hero">');
  });
});
