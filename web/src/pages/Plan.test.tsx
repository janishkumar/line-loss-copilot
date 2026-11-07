import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Plan, { barStyle } from "./Plan";
import { env, mockFetch } from "./testkit";

afterEach(() => vi.unstubAllGlobals());

const rng = (median: number) => ({ median, min: median - 1, max: median + 5 });
const plan = (algorithm: string, late: number) => ({
  algorithm, plan_run_id: 1, status: "ok", solver_status: algorithm === "cpsat" ? "FEASIBLE" : null,
  stop_reason: null, objective: 100, bound: 90, created_at: "2021-07-01T00:00:00Z",
  kpis_nominal: { late_orders: late, total_tardiness_min: late * 100, changeover_min: 50 },
  kpis_replayed: { windows: 8, late_orders: rng(late + 1), total_tardiness_min: rng(late * 200), changeover_min: rng(60) },
  replay_windows: [],
  sequences: { s_1: [
    { order_id: "O-1", start_at: "2021-07-01T00:00:00Z", end_at: "2021-07-01T10:00:00Z", setup_min: 0 },
    { order_id: "O-2", start_at: "2021-07-01T12:00:00Z", end_at: "2021-07-01T22:00:00Z", setup_min: 30 } ] },
  sequence_lengths: { s_1: 2 },
  blocked: algorithm === "cpsat" ? [{ order_id: "O-9", reason: "no eligible machine" }] : [],
  blocked_count: algorithm === "cpsat" ? 1 : 0,
});
const body = {
  ...env, status: "ok", assumptions: ["Synthetic data: generation 1, seed 7."],
  data: { label: "synthetic orders on real capacity", is_synthetic: true, generation_id: 1, seed: 7, stale: false,
    plans: [plan("cpsat", 2), plan("fifo", 8), plan("edd", 7), plan("edd_batch", 11)] },
};

describe("barStyle", () => {
  it("places a bar as percentages of the span", () => {
    const s = barStyle("2021-07-01T12:00:00Z", "2021-07-01T18:00:00Z", Date.parse("2021-07-01T00:00:00Z"), Date.parse("2021-07-02T00:00:00Z"));
    expect(s).toEqual({ left: "50%", width: "25%" });
  });
});

describe("Plan", () => {
  it("shows the synthetic badge, KPI rows per algorithm, a timeline and blocked orders", async () => {
    mockFetch({ "/plan": body });
    render(<MemoryRouter><Plan /></MemoryRouter>);
    expect(await screen.findByText("Synthetic orders on real capacity")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Plan KPIs" });
    for (const a of ["cpsat", "fifo", "edd", "edd_batch"]) expect(within(table).getByText(a)).toBeInTheDocument();
    const cpsat = within(table).getByText("cpsat").closest("tr")!;
    expect(within(cpsat).getByText("400 min")).toBeInTheDocument();
    expect(within(cpsat).getByText("399 to 405 min")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "O-1" })).toHaveAttribute("href", "/orders/O-1");
    expect(screen.getByText("s_1")).toBeInTheDocument();
    expect(screen.getByText("no eligible machine")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "O-9" })).toHaveAttribute("href", "/orders/O-9");
  });

  it("flags a stale plan and shows the missing text when there is none", async () => {
    mockFetch({ "/plan": { ...body, data: { ...body.data, stale: true } } });
    const { unmount } = render(<MemoryRouter><Plan /></MemoryRouter>);
    expect(await screen.findByText(/older generation/i)).toBeInTheDocument();
    unmount();
    mockFetch({ "/plan": { ...env, status: "insufficient_evidence", data: null, missing: "no plan has been stored" } });
    render(<MemoryRouter><Plan /></MemoryRouter>);
    expect(await screen.findByText(/no plan has been stored/)).toBeInTheDocument();
  });
});
