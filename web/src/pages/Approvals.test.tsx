import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Approvals from "./Approvals";
import { mockApi } from "./testkit";

afterEach(() => vi.unstubAllGlobals());

const prop = (proposal_id: number, over: Record<string, unknown> = {}) => ({
  proposal_id, action: "work_order", summary: `Work order for s_${proposal_id}`, status: "pending",
  principal: "copilot-agent", on_behalf_of: "sup.a", channel: "mcp", created_at: "2026-11-07T10:00:00Z",
  decided_by: null, decided_at: null, target_id: null, ...over,
});

describe("Approvals", () => {
  it("lists pending proposals with proposer, on behalf of and channel", async () => {
    const fn = mockApi({
      "GET /api/proposals": [200, [prop(7), prop(8, { action: "follow_up", principal: "op.a", on_behalf_of: "op.a", channel: "web_form" })]],
    });
    render(<MemoryRouter><Approvals /></MemoryRouter>);
    expect(await screen.findByText("Work order for s_7")).toBeInTheDocument();
    expect(screen.getByText("Work order for s_8")).toBeInTheDocument();
    expect(String(fn.mock.calls[0][0])).toContain("status=pending");
    expect(screen.getByRole("link", { name: "Work order for s_7" })).toHaveAttribute("href", "/approvals/7");
    expect(screen.getByText("copilot-agent")).toBeInTheDocument();
    expect(screen.getByText("mcp")).toBeInTheDocument();
  });

  it("says when the inbox is empty", async () => {
    mockApi({ "GET /api/proposals": [200, []] });
    render(<MemoryRouter><Approvals /></MemoryRouter>);
    expect(await screen.findByText(/No pending proposals/)).toBeInTheDocument();
  });
});
