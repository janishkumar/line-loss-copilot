import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import NewAction from "./NewAction";
import { SessionContext } from "../UserSwitcher";
import { demoUsers, mockApi } from "./testkit";

afterEach(() => vi.unstubAllGlobals());

const session = (user: (typeof demoUsers)[number] | null) => ({
  user, users: demoUsers, signIn: async () => {}, signOut: async () => {},
});
const wrap = (url: string, user = demoUsers[1]) =>
  render(
    <SessionContext.Provider value={session(user)}>
      <MemoryRouter initialEntries={[url]}><NewAction /></MemoryRouter>
    </SessionContext.Provider>,
  );

const preview = {
  action: "work_order", summary: "Work order (low) for s_3: jam", code: "ABCD2345", blocked: false, evidence: [],
  args: { asset_id: "s_3", failure_mode: "jam", priority: "low", description: "Jams", evidence_event_ids: [11, 12, 13] },
  checks: [
    { name: "evidence_exists", level: "pass", message: "3 events found", detail: {} },
    { name: "instruction_like_text", level: "warn", message: "looks like instructions", detail: {} },
  ],
};

describe("NewAction", () => {
  it("prefills asset and evidence from the query string", () => {
    wrap("/actions/new?asset=s_3&events=11,12,13");
    expect(screen.getByLabelText("Asset")).toHaveValue("s_3");
    expect(screen.getByLabelText("Evidence event ids")).toHaveValue("11, 12, 13");
  });

  it("previews, shows checks without displaying the code, then proposes with it", async () => {
    const fn = mockApi({
      "POST /api/actions/work_order/preview": [200, preview],
      "POST /api/actions/work_order/propose": [200, { outcome: "proposed", message: "pending", proposal_id: 9, checks: [], target_id: null }],
    });
    const { container } = wrap("/actions/new?asset=s_3&events=11,12,13");
    fireEvent.change(screen.getByLabelText("Failure mode"), { target: { value: "jam" } });
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Jams" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText("evidence_exists")).toBeInTheDocument();
    expect(screen.getByText("instruction_like_text").closest("li")).toHaveClass("warn");
    expect(container.textContent).not.toContain("ABCD2345");
    const pv = fn.mock.calls[0];
    expect(JSON.parse(String(pv[1]!.body))).toMatchObject({
      asset_id: "s_3", failure_mode: "jam", priority: "low", evidence_event_ids: [11, 12, 13],
    });
    fireEvent.click(screen.getByRole("button", { name: "Propose" }));
    expect(await screen.findByText(/Proposal 9 is waiting/)).toBeInTheDocument();
    const prop = fn.mock.calls.find(([u]) => String(u).endsWith("/propose"))!;
    expect(JSON.parse(String(prop[1]!.body))).toMatchObject({ code: "ABCD2345", args: preview.args });
    expect(screen.getByRole("link", { name: "Open in the inbox" })).toHaveAttribute("href", "/approvals/9");
  });

  it("drops the preview when a field changes, so a stale code is not proposed", async () => {
    mockApi({ "POST /api/actions/work_order/preview": [200, preview] });
    wrap("/actions/new?asset=s_3&events=11");
    fireEvent.change(screen.getByLabelText("Failure mode"), { target: { value: "jam" } });
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Jams" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await screen.findByText("evidence_exists");
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Jams a lot" } });
    await waitFor(() => expect(screen.queryByText("evidence_exists")).toBeNull());
    expect(screen.queryByRole("button", { name: "Propose" })).toBeNull();
  });

  it("shows a blocked preview and no Propose button", async () => {
    mockApi({
      "POST /api/actions/work_order/preview": [200, { ...preview, code: null, blocked: true,
        checks: [{ name: "duplicate_open_action", level: "block", message: "an open work order exists", detail: {} }] }],
    });
    wrap("/actions/new?asset=s_3&events=11");
    fireEvent.change(screen.getByLabelText("Failure mode"), { target: { value: "jam" } });
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect((await screen.findByText("duplicate_open_action")).closest("li")).toHaveClass("block");
    expect(screen.queryByRole("button", { name: "Propose" })).toBeNull();
  });
});

describe("NewAction follow-up with orders", () => {
  it("prefills the follow-up type and order ids, and sends order_ids", async () => {
    const fn = mockApi({
      "POST /api/actions/follow_up/preview": [200, { ...preview, action: "follow_up", args: {} }],
    });
    wrap("/actions/new?action=follow_up&role=planner&orders=O-1,O-2");
    expect(screen.getByLabelText("Action type")).toHaveValue("follow_up");
    expect(screen.getByLabelText("Assignee role")).toHaveValue("planner");
    expect(screen.getByLabelText("Order ids")).toHaveValue("O-1, O-2");
    fireEvent.change(screen.getByLabelText("Due date"), { target: { value: "2026-01-09" } });
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Chase supplier" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(fn).toHaveBeenCalled());
    expect(JSON.parse(String(fn.mock.calls[0][1]!.body))).toMatchObject({
      assignee_role: "planner", order_ids: ["O-1", "O-2"], evidence_event_ids: [],
    });
  });
});
