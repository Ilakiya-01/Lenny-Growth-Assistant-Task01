import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Sidebar } from "@/components/Sidebar/Sidebar";
import { session } from "../fixtures";

const SESSIONS = [session("s2", "Ship30for30 essay"), session("s1", "Product-market fit")];

function renderSidebar(overrides: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  const props = {
    sessions: SESSIONS,
    selectedSessionId: "s1",
    isCreating: false,
    onCreate: vi.fn(),
    onSelect: vi.fn(),
    ...overrides,
  };
  render(<Sidebar {...props} />);
  return props;
}

describe("Sidebar", () => {
  it("lists every session", () => {
    renderSidebar();
    const nav = screen.getByRole("navigation", { name: "Sessions" });
    expect(within(nav).getAllByRole("button")).toHaveLength(2);
    expect(within(nav).getByText("Ship30for30 essay")).toBeInTheDocument();
    expect(within(nav).getByText("Product-market fit")).toBeInTheDocument();
  });

  it("marks the selected session for assistive technology", () => {
    renderSidebar();
    const active = screen.getByText("Product-market fit").closest("button");
    expect(active).toHaveAttribute("aria-current", "true");
    expect(screen.getByText("Ship30for30 essay").closest("button")).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("selects a session when it is clicked", async () => {
    const user = userEvent.setup();
    const { onSelect } = renderSidebar();
    await user.click(screen.getByText("Ship30for30 essay"));
    expect(onSelect).toHaveBeenCalledWith("s2");
  });

  it("creates a session from New chat", async () => {
    const user = userEvent.setup();
    const { onCreate } = renderSidebar();
    await user.click(screen.getByRole("button", { name: /new chat/i }));
    expect(onCreate).toHaveBeenCalledTimes(1);
  });

  it("shows progress and blocks double submission while creating", () => {
    renderSidebar({ isCreating: true });
    const button = screen.getByRole("button", { name: /creating/i });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });

  it("explains an empty list instead of rendering nothing", () => {
    renderSidebar({ sessions: [], selectedSessionId: null });
    expect(screen.getByText("No conversations yet.")).toBeInTheDocument();
  });
});
