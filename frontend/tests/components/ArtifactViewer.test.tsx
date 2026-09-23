import type React from "react";

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ArtifactErrorBoundary } from "@/components/ArtifactViewer/ArtifactErrorBoundary";
import { ArtifactViewer } from "@/components/ArtifactViewer/ArtifactViewer";
import type { Artifact } from "@/types";
import { HTML_ARTIFACT, MARKDOWN_ARTIFACT } from "../fixtures";

function renderViewer(artifact: Artifact = MARKDOWN_ARTIFACT) {
  const onClose = vi.fn();
  render(<ArtifactViewer artifact={artifact} onClose={onClose} />);
  return onClose;
}

function stubClipboard(writeText: (text: string) => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
    writable: true,
  });
}

afterEach(() => {
  stubClipboard(() => Promise.resolve());
});

describe("ArtifactViewer: Markdown", () => {
  it("renders the artifact content, title and type", () => {
    renderViewer();
    expect(
      screen.getByRole("complementary", { name: "Artifact viewer" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Product-market fit essay" })).toBeInTheDocument();
    expect(screen.getByText("Markdown")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Product-market fit" })).toBeInTheDocument();
    expect(screen.getByText("Pull, not push.")).toBeInTheDocument();
  });

  it("does not execute markup embedded in the artifact", () => {
    renderViewer({
      type: "markdown",
      title: "Hostile",
      content: '<script>steal()</script><img src="x" onerror="steal()">',
    });
    expect(document.querySelector("script")).toBeNull();
    expect(document.querySelector("img")).toBeNull();
  });
});

describe("ArtifactViewer: HTML/CSS", () => {
  it("renders generated HTML inside a sandboxed iframe", () => {
    renderViewer(HTML_ARTIFACT);
    const frame = screen.getByTitle("Landing page preview");
    expect(frame.tagName).toBe("IFRAME");
    expect(frame).toHaveAttribute("sandbox", "allow-scripts");
  });

  it("never grants the artifact same-origin access", () => {
    renderViewer(HTML_ARTIFACT);
    const sandbox = screen.getByTitle("Landing page preview").getAttribute("sandbox") ?? "";
    expect(sandbox).not.toContain("allow-same-origin");
    expect(sandbox).not.toContain("allow-top-navigation");
    expect(sandbox).not.toContain("allow-forms");
  });

  it("keeps the generated markup out of the application DOM", () => {
    renderViewer(HTML_ARTIFACT);
    // The artifact's own elements exist only inside the iframe document.
    expect(screen.queryByText("Ship it")).toBeNull();
    expect(document.querySelector("section.hero")).toBeNull();
  });

  it("hands the iframe a document that blocks network access", () => {
    renderViewer(HTML_ARTIFACT);
    const srcDoc = screen.getByTitle("Landing page preview").getAttribute("srcdoc") ?? "";
    expect(srcDoc).toContain("default-src 'none'");
    expect(srcDoc).toContain(".hero { padding: 2rem; }");
    expect(srcDoc).toContain('<section class="hero"><h1>Ship it</h1></section>');
  });

  it("labels HTML/CSS artifacts in the header", () => {
    renderViewer(HTML_ARTIFACT);
    expect(screen.getByText("HTML/CSS")).toBeInTheDocument();
  });
});

describe("ArtifactViewer: Preview | Code", () => {
  it("starts on Preview and exposes both tabs", () => {
    renderViewer();
    const preview = screen.getByRole("tab", { name: "Preview" });
    const code = screen.getByRole("tab", { name: "Code" });
    expect(preview).toHaveAttribute("aria-selected", "true");
    expect(code).toHaveAttribute("aria-selected", "false");
  });

  it("switches to the artifact source and back", async () => {
    const user = userEvent.setup();
    renderViewer(HTML_ARTIFACT);

    await user.click(screen.getByRole("tab", { name: "Code" }));
    expect(screen.getByRole("tab", { name: "Code" })).toHaveAttribute("aria-selected", "true");
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText(/\.hero \{ padding: 2rem; \}/)).toBeInTheDocument();
    expect(screen.queryByTitle("Landing page preview")).toBeNull();

    await user.click(screen.getByRole("tab", { name: "Preview" }));
    expect(screen.getByTitle("Landing page preview")).toBeInTheDocument();
  });

  it("shows Markdown source under Code", async () => {
    const user = userEvent.setup();
    renderViewer();
    await user.click(screen.getByRole("tab", { name: "Code" }));
    expect(screen.getByRole("tabpanel").textContent).toContain("# Product-market fit");
  });
});

describe("ArtifactViewer: controls", () => {
  it("copies the source to the clipboard", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn(() => Promise.resolve());
    stubClipboard(writeText);
    renderViewer();

    await user.click(screen.getByRole("button", { name: "Copy source" }));
    expect(writeText).toHaveBeenCalledWith("# Product-market fit\n\nPull, not push.");
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("explains a blocked clipboard instead of failing silently", async () => {
    const user = userEvent.setup();
    stubClipboard(() => Promise.reject(new Error("denied")));
    renderViewer();

    await user.click(screen.getByRole("button", { name: "Copy source" }));
    expect(await screen.findByText(/Copying is blocked/)).toBeInTheDocument();
  });

  it("closes from the button", async () => {
    const user = userEvent.setup();
    const onClose = renderViewer();
    await user.click(screen.getByRole("button", { name: "Close artifact" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes from Escape, and leaves full screen first", async () => {
    const user = userEvent.setup();
    const onClose = renderViewer();

    await user.click(screen.getByRole("button", { name: "Full screen" }));
    expect(screen.getByRole("button", { name: "Exit full screen" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Full screen" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("ArtifactViewer: failures", () => {
  it("reports an unsupported type without unmounting", () => {
    renderViewer({ type: "pdf", title: "Report", content: "binary" });
    expect(screen.getByText("No preview available")).toBeInTheDocument();
    expect(screen.getByText(/Unsupported artifact type "pdf"/)).toBeInTheDocument();
  });

  it("reports an empty artifact and still offers the source", async () => {
    const user = userEvent.setup();
    renderViewer({ type: "markdown", title: "Empty", content: "" });
    expect(screen.getByText(/This artifact is empty/)).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Code" }));
    expect(screen.getByRole("tabpanel").textContent).toContain("no source");
  });

  it("keeps the workspace alive when a preview throws while rendering", () => {
    function Exploding(): React.JSX.Element {
      throw new Error("renderer blew up");
    }
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);

    render(
      <ArtifactErrorBoundary resetKey="a">
        <Exploding />
      </ArtifactErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "This artifact could not be previewed.",
    );
    expect(screen.getByText(/The conversation is unaffected/)).toBeInTheDocument();
    spy.mockRestore();
  });

  it("recovers when a different artifact is opened", () => {
    function Exploding(): React.JSX.Element {
      throw new Error("renderer blew up");
    }
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { rerender } = render(
      <ArtifactErrorBoundary resetKey="a">
        <Exploding />
      </ArtifactErrorBoundary>,
    );

    rerender(
      <ArtifactErrorBoundary resetKey="b">
        <p>Fine again</p>
      </ArtifactErrorBoundary>,
    );

    expect(screen.getByText("Fine again")).toBeInTheDocument();
    spy.mockRestore();
  });
});
