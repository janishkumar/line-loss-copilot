import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import StopRisk from "./StopRisk";
import { cite, env, mockFetch } from "./testkit";

afterEach(() => vi.unstubAllGlobals());

const m = (target: string, model_name: string, metric: string, value: number, machine_id: string | null = null) =>
  ({ target, model_name, split: "test", metric, value, machine_id, created_at: "2026-01-01T00:00:00Z" });
const metricRows = [
  m("long", "data", "base_rate", 0.055),
  m("long", "hist_gb", "pr_auc", 0.181), m("long", "hist_gb", "precision_top3", 0.067),
  m("long", "persistence", "pr_auc", 0.113),
  m("long", "hist_gb", "pr_auc", 0.99, "s_1"),
  m("any", "hist_gb", "pr_auc", 0.87),
];
const risk = {
  ...env, status: "ok",
  data: { target: "long", definition: "a stop of 600 s or more starts in the next hour", rows: [
    { machine_id: "s_1", t: "2021-12-31T17:00:00Z", covers_at: false, score: 0.0076, model_name: "hist_gb",
      split: "test", base_rate: 0.086, alert_threshold: 0.0999, alert: false,
      top_features: [{ feature: "running_s_1h", contribution: -0.58, value: 0 }],
      citations: [cite(7)], citation_count: 1 },
  ] },
};

describe("StopRisk", () => {
  it("shows per-machine scores and a metrics table with a weak-signal sentence from the numbers", async () => {
    const f = mockFetch({
      "/risk/metrics": { ...env, status: "ok", data: { rows: metricRows } },
      "/risk": risk,
    });
    render(<MemoryRouter><StopRisk /></MemoryRouter>);
    expect(await screen.findByText("0.008")).toBeInTheDocument();
    expect(screen.getByText(/running_s_1h \(-0\.58\)/)).toBeInTheDocument();
    const sentence = await screen.findByText(/long-stop signal is weak/);
    expect(sentence).toHaveTextContent("hist_gb");
    expect(sentence).toHaveTextContent("PR-AUC 0.181, 1.6x persistence (0.113) and 3.3x the base rate (5.5%)");
    expect(sentence).toHaveTextContent("precision at top-3 volume is 6.7%");
    expect(sentence).not.toHaveTextContent("0.99");
    expect(screen.getByText("persistence (baseline)")).toBeInTheDocument();
    // default is the latest scored hour: no `at` parameter
    expect(f.mock.calls.some(([u]) => String(u).startsWith("/api/risk?") && !String(u).includes("at="))).toBe(true);
  });

  it("does not call the signal weak when lift is large", async () => {
    const rows = [
      m("long", "data", "base_rate", 0.05),
      m("long", "hist_gb", "pr_auc", 0.5), m("long", "hist_gb", "precision_top3", 0.4),
      m("long", "persistence", "pr_auc", 0.1),
    ];
    mockFetch({ "/risk/metrics": { ...env, status: "ok", data: { rows } }, "/risk": risk });
    render(<MemoryRouter><StopRisk /></MemoryRouter>);
    const sentence = await screen.findByText(/long-stop signal shows lift/);
    expect(sentence).toHaveTextContent("5.0x persistence");
    expect(sentence).toHaveTextContent("10.0x the base rate");
    expect(screen.queryByText(/signal is weak/)).toBeNull();
  });

  it("shows precision, recall and base rate as percentages", async () => {
    mockFetch({ "/risk/metrics": { ...env, status: "ok", data: { rows: metricRows } }, "/risk": risk });
    render(<MemoryRouter><StopRisk /></MemoryRouter>);
    expect(await screen.findByText("6.7%", { selector: "td" })).toBeInTheDocument();
    expect(screen.getByText("0.181", { selector: "td" })).toBeInTheDocument();
  });

  it("shows the missing text", async () => {
    mockFetch({
      "/risk/metrics": { ...env, status: "insufficient_evidence", data: null, missing: "No model metrics stored." },
      "/risk": { ...env, status: "insufficient_evidence", data: null, missing: "No scores stored." },
    });
    render(<MemoryRouter><StopRisk /></MemoryRouter>);
    expect(await screen.findByText(/No scores stored\./)).toBeInTheDocument();
    expect(await screen.findByText(/No model metrics stored\./)).toBeInTheDocument();
  });
});
