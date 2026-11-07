import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Losses from "./Losses";
import { cite, env, mockFetch } from "./testkit";

afterEach(() => vi.unstubAllGlobals());

const pareto = {
  ...env, status: "ok",
  data: {
    source_system: "brick", by: "reason", total_lost_s: 36000, total_stop_count: 7,
    other_lost_s: 0, other_stop_count: 0, other_categories: 0,
    rows: [{ category: "FAILURE", lost_s: 18000, stop_count: 4, share: 0.5, cumulative_share: 0.5,
      citations: [cite(11)], citation_count: 1 }],
  },
};
const breakdown = {
  ...env, status: "ok",
  data: { source_system: "brick", rows: "reason", cols: "month", row_keys: ["FAILURE"], col_keys: ["2025-09"],
    cells: [{ row: "FAILURE", col: "2025-09", lost_s: 7200, stop_count: 2 }], total_lost_s: 7200, total_stop_count: 2 },
};
const repeats = {
  ...env, status: "ok",
  data: { source_system: "brick", key: "reason", within_hours: 24, min_repeats: 3, chain_count: 1, chains_truncated: false,
    failure_count: 9,
    chains: [{ machine_id: null, line_id: "brick", key: "FAILURE", count: 3, first_start: "2025-09-01T00:00:00Z",
      last_end: "2025-09-02T00:00:00Z", lost_s: 5400, episode_ids: [1, 2, 3],
      citations: [cite(1), cite(2)], citation_count: 3 }] },
};

describe("Losses", () => {
  it("renders pareto, breakdown and repeat rows with citation links", async () => {
    mockFetch({ "/losses/pareto": pareto, "/losses/breakdown": breakdown, "/losses/repeats": repeats });
    render(<MemoryRouter><Losses /></MemoryRouter>);
    expect(await screen.findByText("5.0 h")).toBeInTheDocument();
    const one = await screen.findByRole("link", { name: "1 row" });
    expect(one).toHaveAttribute("href", "/evidence/11");
    expect(await screen.findByText("3 rows")).toBeInTheDocument();
    expect(screen.getByText("showing 2 of 3")).toBeInTheDocument();
    expect(screen.getByTitle("2 stops")).toHaveTextContent("2.0 h");
  });

  it("shows the other remainder with its category count", async () => {
    const withOther = { ...pareto, data: { ...pareto.data, other_lost_s: 1800, other_stop_count: 5, other_categories: 12 } };
    mockFetch({ "/losses/pareto": withOther, "/losses/breakdown": breakdown, "/losses/repeats": repeats });
    render(<MemoryRouter><Losses /></MemoryRouter>);
    expect(await screen.findByText("other (12 categories)")).toBeInTheDocument();
    expect(screen.getByText("30.0 min")).toBeInTheDocument();
  });

  it("shows the missing text instead of an empty chart", async () => {
    const gap = { ...env, status: "insufficient_evidence", data: null, missing: "No stops in this window." };
    mockFetch({ "/losses/pareto": gap, "/losses/breakdown": gap, "/losses/repeats": gap });
    render(<MemoryRouter><Losses /></MemoryRouter>);
    expect(await screen.findAllByText(/No stops in this window\./)).toHaveLength(3);
    expect(screen.queryByRole("table")).toBeNull();
    expect(document.querySelector(".chart")).toBeNull();
  });
});
