import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LLMModeToggle } from "@/components/LLMSelector/LLMModeToggle";

function renderToggle(mode: "cloud" | "ollama" = "ollama", disabled = false) {
  const onChange = vi.fn();
  render(<LLMModeToggle mode={mode} onChange={onChange} disabled={disabled} />);
  return onChange;
}

describe("LLMModeToggle", () => {
  it("offers both providers in a labelled group", () => {
    renderToggle();
    const group = screen.getByRole("group", { name: "LLM mode" });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cloud/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ollama/i })).toBeInTheDocument();
  });

  it("shows which provider is selected", () => {
    renderToggle("cloud");
    expect(screen.getByRole("button", { name: /cloud/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: /ollama/i })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("reports the requested mode when switched", async () => {
    const user = userEvent.setup();
    const onChange = renderToggle("ollama");
    await user.click(screen.getByRole("button", { name: /cloud/i }));
    expect(onChange).toHaveBeenCalledWith("cloud");
  });

  it("cannot be switched while a request is in flight", async () => {
    const user = userEvent.setup();
    const onChange = renderToggle("ollama", true);
    await user.click(screen.getByRole("button", { name: /cloud/i }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
