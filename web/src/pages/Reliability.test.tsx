import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Reliability from "./Reliability";
import { cite, env, mockFetch } from "./testkit";

afterEach(() => vi.unstubAllGlobals());

describe("Reliability", () => {
  it("renders MTTR and MTBF per month", async () => {
    mockFetch({
      "/reliability": { ...env, status: "ok", data: { source_system: "brick", group: "month", rows: [
        { period: "2025-09", failure_count: 5, stop_count: 9, failure_s: 7200, run_s: 360000,
          mttr_s: 1440, mtbf_s: 72000, citations: [cite(5)], citation_count: 1 },
      ] } },
    });
    render(<MemoryRouter><Reliability /></MemoryRouter>);
    expect(await screen.findByText("2025-09")).toBeInTheDocument();
    expect(screen.getByText("24.0 min")).toBeInTheDocument();
    expect(screen.getByText("20.0 h")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "1 row" })).toHaveAttribute("href", "/evidence/5");
  });

  it("shows the missing text", async () => {
    mockFetch({ "/reliability": { ...env, status: "insufficient_evidence", data: null, missing: "No failures recorded." } });
    render(<MemoryRouter><Reliability /></MemoryRouter>);
    expect(await screen.findByText(/No failures recorded\./)).toBeInTheDocument();
  });
});
