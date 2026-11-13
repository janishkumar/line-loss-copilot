import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Actions from "./Actions";
import { SessionContext } from "../UserSwitcher";
import { demoUsers, mockApi, type ApiReply } from "./testkit";

afterEach(() => vi.unstubAllGlobals());

const routes: Record<string, ApiReply> = {
  "GET /api/actions/work_orders": [200, [{ work_order_id: 3, proposal_id: 7, asset_id: "s_3", failure_mode: "repeat A_006 stops on the infeed", priority: "high", description: "d", status: "open", created_by: "sup.b", created_at: "2026-11-07T10:00:00Z", closed_by: null, closed_at: null }]],
  "GET /api/actions/quality_holds": [200, []],
  "GET /api/actions/follow_ups": [200, []],
};

describe("Actions", () => {
  it("lists work orders and closes one through the route", async () => {
    const fn = mockApi({
      ...routes,
      "POST /api/actions/work_orders/3/close": [403, { outcome: "refused", message: "role may not close", checks: [] }],
    });
    render(
      <SessionContext.Provider value={{ user: demoUsers[1], users: demoUsers, signIn: async () => {}, signOut: async () => {} }}>
        <MemoryRouter><Actions /></MemoryRouter>
      </SessionContext.Provider>,
    );
    expect(await screen.findByText("repeat A_006 stops on the infeed")).toBeInTheDocument();
    expect(screen.getByText("2026-11-07 10:00")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("role may not close");
    expect(fn.mock.calls.some(([u, i]) => String(u).endsWith("/work_orders/3/close") && i?.method === "POST")).toBe(true);
  });
});
