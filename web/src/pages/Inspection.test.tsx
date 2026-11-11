import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Inspection from "./Inspection";
import { env, mockApi } from "./testkit";

afterEach(() => vi.unstubAllGlobals());

const row = (inspection_id: number, over: Record<string, unknown> = {}) => ({
  inspection_id, subset: "cashew", image_name: `${inspection_id}`, split: "test", score: 0.87, decision: "review",
  threshold: 0.881, review_lower: 0.85, created_at: "2026-11-09T10:00:00Z", source: "synthetic",
  asset_id: "SIM-VIS-cashew", heatmap_url: null, image_url: null, review: null, quality_event_id: null, is_synthetic: true, ...over,
});
const body = (rows: unknown[]) => ({
  ...env, status: "ok", assumptions: ["The inspection stream is SIMULATED."],
  data: { label: "x", is_synthetic: true, counts: { pass: 5, review: 2, reject: 7 }, total: rows.length,
    pending_review: 2, rows, limit: 50, offset: 0 },
});

describe("Inspection queue", () => {
  it("shows the badge, counts, defaults to the unreviewed review queue and links rows", async () => {
    const fn = mockApi({ "GET /api/inspections": [200, body([row(3), row(4)])] });
    render(<MemoryRouter><Inspection /></MemoryRouter>);
    expect(await screen.findByRole("link", { name: "#3 cashew 3" })).toHaveAttribute("href", "/inspection/3");
    expect(screen.getByText("Simulated / synthetic")).toBeInTheDocument();
    expect(screen.getByText(/5 passed, 2 to review, 7 rejected/)).toBeInTheDocument();
    const url = String(fn.mock.calls[0][0]);
    expect(url).toContain("decision=review");
    expect(url).toContain("unreviewed=true");
  });

  it("refetches by decision when a filter is chosen", async () => {
    const fn = mockApi({ "GET /api/inspections": [200, body([row(9, { decision: "reject", score: 1.2 })])] });
    render(<MemoryRouter><Inspection /></MemoryRouter>);
    await screen.findByText("#9 cashew 9");
    fireEvent.click(screen.getByRole("button", { name: "Rejected" }));
    await screen.findByText("1.200");
    expect(String(fn.mock.calls.at(-1)![0])).toContain("decision=reject");
    expect(String(fn.mock.calls.at(-1)![0])).not.toContain("unreviewed");
  });

  it("does not render the class folder of a real-shaped id", async () => {
    mockApi({ "GET /api/inspections": [200, body([row(3, { image_name: "000.JPG" })])] });
    const { container } = render(<MemoryRouter><Inspection /></MemoryRouter>);
    await screen.findByText("#3 cashew 000.JPG");
    expect(container.textContent).not.toMatch(/Anomaly|Normal/);
  });

  it("keeps the filter buttons focusable", async () => {
    mockApi({ "GET /api/inspections": [200, body([row(3)])] });
    render(<MemoryRouter><Inspection /></MemoryRouter>);
    await screen.findByText("#3 cashew 3");
    expect(screen.getByRole("button", { name: "Needs review" })).not.toBeDisabled();
  });

  it("says when nothing matches", async () => {
    mockApi({ "GET /api/inspections": [200, body([])] });
    render(<MemoryRouter><Inspection /></MemoryRouter>);
    expect(await screen.findByText("No inspections match this filter.")).toBeInTheDocument();
  });

  it("renders the insufficient evidence notice", async () => {
    mockApi({ "GET /api/inspections": [200, { ...env, status: "insufficient_evidence", data: null, missing: "no inspections are stored", assumptions: [] }] });
    render(<MemoryRouter><Inspection /></MemoryRouter>);
    expect(await screen.findByText(/no inspections are stored/)).toBeInTheDocument();
  });
});
