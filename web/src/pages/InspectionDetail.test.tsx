import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import InspectionDetail, { holdLink } from "./InspectionDetail";
import { SessionContext } from "../UserSwitcher";
import { demoUsers, env, mockApi } from "./testkit";

afterEach(() => vi.unstubAllGlobals());

const insp = (over: Record<string, unknown> = {}) => ({
  inspection_id: 5, subset: "fryum", image_name: "17", split: "test", score: 0.9, decision: "review",
  threshold: 0.915, review_lower: 0.88, created_at: "2026-11-09T10:00:00Z", source: "synthetic",
  asset_id: "SIM-VIS-fryum", heatmap_url: "/api/inspections/5/heatmap", image_url: "/api/inspections/5/image", review: null, quality_event_id: null,
  is_synthetic: true, ...over,
});
const envelope = (data: unknown) => ({ ...env, status: "ok", data, assumptions: ["SIMULATED stream."] });
const session = (user: (typeof demoUsers)[number] | null) => ({
  user, users: demoUsers, signIn: async () => {}, signOut: async () => {},
});
const wrap = (user: (typeof demoUsers)[number] | null) =>
  render(
    <SessionContext.Provider value={session(user)}>
      <MemoryRouter initialEntries={["/inspection/5"]}>
        <Routes><Route path="/inspection/:id" element={<InspectionDetail />} /></Routes>
      </MemoryRouter>
    </SessionContext.Provider>,
  );
const operator = { user_id: "op.a", display_name: "Operator A", role: "operator", source: "synthetic" };

describe("InspectionDetail", () => {
  it("shows the badge, score against threshold, heatmap and a toggle", async () => {
    mockApi({ "GET /api/inspections/5": [200, envelope(insp())] });
    wrap(demoUsers[0]);
    expect(await screen.findByAltText(/Defect heatmap for fryum 17/)).toHaveAttribute("src", "/api/inspections/5/heatmap");
    expect(screen.getByText("Simulated / synthetic")).toBeInTheDocument();
    expect(screen.getByText(/0.900 against reject threshold 0.915/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/Show heatmap overlay/));
    expect(screen.queryByAltText(/Defect heatmap/)).toBeNull();
    expect(screen.getByAltText(/Product image fryum 17/)).toHaveAttribute("src", "/api/inspections/5/image");
  });

  it("lets a supervisor reject and shows the quality event, then reloads", async () => {
    let reviewed = false;
    const fn = mockApi({
      "GET /api/inspections/5": () => [200, envelope(insp(reviewed ? { review: { decision: "reject", reviewer: "sup.a", score_at_review: 0.9, created_at: "x" }, quality_event_id: 9000000001 } : {}))],
      "POST /api/inspections/5/review": () => { reviewed = true; return [200, { status: "ok", data: { inspection: insp(), review_id: 1, quality_event_id: 9000000001 } }]; },
    });
    wrap(demoUsers[0]);
    fireEvent.click(await screen.findByRole("button", { name: /Reject/ }));
    expect(await screen.findByText(/simulated quality event 9000000001 created/)).toBeInTheDocument();
    const post = fn.mock.calls.find(([, i]) => i?.method === "POST")!;
    expect(JSON.parse(String(post[1]!.body))).toEqual({ decision: "reject" });
    expect(await screen.findByRole("link", { name: "Draft quality hold" })).toHaveAttribute(
      "href", "/actions/new?action=quality_hold&asset=SIM-VIS-fryum&events=9000000001");
  });

  it("hides the buttons for an operator and says why", async () => {
    mockApi({ "GET /api/inspections/5": [200, envelope(insp())] });
    wrap(operator);
    await screen.findByText(/Your role \(operator\) cannot review images/);
    expect(screen.queryByRole("button", { name: /Accept/ })).toBeNull();
  });

  it("shows the server's refusal message", async () => {
    mockApi({
      "GET /api/inspections/5": [200, envelope(insp())],
      "POST /api/inspections/5/review": [403, { status: "out_of_scope", data: null, missing: "role planner may not review inspection images" }],
    });
    wrap(demoUsers[0]);
    fireEvent.click(await screen.findByRole("button", { name: /Accept/ }));
    expect(await screen.findByText(/role planner may not review/)).toBeInTheDocument();
  });

  it("shows no review controls once reviewed, and a missing heatmap note", async () => {
    mockApi({ "GET /api/inspections/5": [200, envelope(insp({ heatmap_url: null, image_url: null, review: { decision: "accept", reviewer: "sup.b", score_at_review: 0.9, created_at: "x" } }))] });
    wrap(demoUsers[0]);
    expect(await screen.findByText("accept by sup.b")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Reject/ })).toBeNull();
    expect(screen.getByText(/No image or heatmap file/)).toBeInTheDocument();
  });
});

describe("class label", () => {
  it("never renders the class folder or the full id", async () => {
    mockApi({ "GET /api/inspections/5": [200, envelope(insp({ image_name: "000.JPG", subset: "cashew" }))] });
    const { container } = wrap(demoUsers[0]);
    await screen.findByAltText(/Defect heatmap for cashew 000.JPG/);
    expect(container.textContent).not.toMatch(/Anomaly|Normal|Data\/Images/);
    expect(container.innerHTML).not.toMatch(/Anomaly|Normal/);
    expect(container.textContent).toContain("000.JPG");
  });
});

describe("hold link by role", () => {
  const withEvent = insp({ decision: "reject", quality_event_id: 9000000001 });
  it("shows for a supervisor and not for a plant manager", async () => {
    mockApi({ "GET /api/inspections/5": [200, envelope(withEvent)] });
    const a = wrap(demoUsers[0]);
    expect(await screen.findByRole("link", { name: "Draft quality hold" })).toBeInTheDocument();
    a.unmount();
    wrap(demoUsers[2]);
    await screen.findByText(/9000000001 \(simulated\)/);
    expect(screen.queryByRole("link", { name: "Draft quality hold" })).toBeNull();
  });
});

describe("review errors", () => {
  it("joins an array detail", async () => {
    mockApi({
      "GET /api/inspections/5": [200, envelope(insp())],
      "POST /api/inspections/5/review": [422, { detail: [{ msg: "bad id" }, { msg: "worse" }] }],
    });
    wrap(demoUsers[0]);
    fireEvent.click(await screen.findByRole("button", { name: /Accept/ }));
    expect(await screen.findByText("bad id; worse")).toBeInTheDocument();
  });
});

describe("holdLink", () => {
  it("is null for a pass or an inspection with no quality event", () => {
    expect(holdLink(insp({ decision: "pass" }) as never)).toBeNull();
    expect(holdLink(insp() as never)).toBeNull();
  });
});
