import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Validation from "./Validation";

const stats = (m: number) => ({
  n: 2, mean_abs: m, median_abs: m, max_abs: m,
  share_within_2pts: 0.5, share_within_5pts: 1, mean_signed: 0,
});
const period = {
  n_published: 2, n_matched: 2, n_no_stops: 0, n_no_published: 0,
  availability: stats(0.0123), oee: stats(0.02),
};
const cite = (event_id: number, raw_table: string) => ({
  raw_table, source_file: "brick/x.csv", raw_row_id: event_id, event_id, field: null,
});
const shift = (id: string, gap: number, cites: unknown[]) => ({
  shift_id: id, shift_date: id.slice(-10), period: "before", planned_s_published: 28000,
  availability_calc: 0.9, availability_pub: 0.9 - gap, availability_gap: gap,
  oee_calc_with_pub_pq: 0.8, oee_pub: 0.78, oee_gap: 0.02, match_status: "matched",
  _cites: cites,
});

const validation = {
  status: "ok", citations: [], citation_count: 0, assumptions: ["planned time is published"],
  missing: null, window: null,
  data: {
    windows: { before: { first: "2025-09-22", last: "2025-12-18" }, after: { first: "2026-01-30", last: "2026-04-03" } },
    periods: { before: period, after: period },
    shifts: [shift("brick:2025-09-22", 0.0234, []), shift("brick:2025-09-23", -0.05, [])],
  },
};
const row = (s: ReturnType<typeof shift>, ev: number) => ({
  key: s.shift_id, start: null, metrics: {}, details: {}, citation_count: 3,
  citations: [cite(ev + 1, "brick_downtime"), cite(ev, "brick_oee")],
});
const oee = {
  status: "ok", citations: [], citation_count: 0, assumptions: [], missing: null, window: null,
  data: {
    source_system: "brick", group: "shift", row_count: 2, rows_truncated: false,
    rows: [row(validation.data.shifts[0], 1219), row(validation.data.shifts[1], 1220)],
  },
};

afterEach(() => vi.unstubAllGlobals());

describe("Validation", () => {
  it("shows gap cells and links each row to its production_count evidence", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
      ok: true,
      json: async () => (String(url).includes("/oee/validation") ? validation : oee),
    })));
    render(<MemoryRouter><Validation /></MemoryRouter>);
    const r1 = (await screen.findByText("2025-09-22")).closest("tr")!;
    expect(within(r1).getByText("+2.3 pts")).toBeInTheDocument();
    expect(within(r1).getByRole("link", { name: /3 rows/ })).toHaveAttribute("href", "/evidence/1219");
    const r2 = screen.getByText("2025-09-23").closest("tr")!;
    expect(within(r2).getByText("-5.0 pts")).toBeInTheDocument();
    expect(within(r2).getByRole("link", { name: /3 rows/ })).toHaveAttribute("href", "/evidence/1220");
    expect(screen.getAllByText(/published/i).length).toBeGreaterThan(0);
  });
});
