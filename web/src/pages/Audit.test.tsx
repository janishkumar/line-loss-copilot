import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Audit from "./Audit";
import { mockApi } from "./testkit";

afterEach(() => vi.unstubAllGlobals());

const row = (audit_id: number, event: string, outcome: string, over: Record<string, unknown> = {}) => ({
  audit_id, at: "2026-11-07T10:00:00Z", event, action: "work_order", proposal_id: 7, principal: "copilot-agent",
  on_behalf_of: "sup.a", channel: "mcp", payload_sha256: "abc", outcome, checks: [], detail: null, ...over,
});

describe("Audit", () => {
  it("renders events newest first with outcome and proposal link", async () => {
    mockApi({
      "GET /api/audit": [200, [
        row(3, "approved", "approved", { principal: "sup.b", channel: "web_form" }),
        row(2, "proposed", "proposed"),
        row(1, "refused", "refused", { detail: "bad code" }),
      ]],
    });
    render(<MemoryRouter><Audit /></MemoryRouter>);
    expect(await screen.findByText("bad code")).toBeInTheDocument();
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("approved");
    expect(rows[0]).toHaveTextContent("sup.b");
    expect(screen.getAllByRole("link", { name: "#7" })[0]).toHaveAttribute("href", "/approvals/7");
  });
});
