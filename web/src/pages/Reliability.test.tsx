import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Reliability from "./Reliability";
import { assets, cite, env, mockFetch } from "./testkit";

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
    expect(screen.queryByLabelText("MTTR (min) by month")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("ignores an older response that resolves after a newer one", async () => {
    const mk = (period: string) => ({ ...env, status: "ok", data: { source_system: "x", group: "month", rows: [
      { period, failure_count: 1, stop_count: 1, failure_s: 60, run_s: 3600, mttr_s: 60, mtbf_s: 3600,
        citations: [], citation_count: 0 }] } });
    mockFetch({});
    let releaseOld: (v: unknown) => void = () => {};
    const old = new Promise((r) => { releaseOld = r; });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const u = String(url);
      if (u.includes("/assets")) return { ok: true, json: async () => assets };
      if (u.includes("line_id=brick")) return { ok: true, json: async () => old };
      return { ok: true, json: async () => mk("NEW-PERIOD") };
    }));
    render(<MemoryRouter><Reliability /></MemoryRouter>);
    const select = await screen.findByLabelText("Line or machine");
    await screen.findByRole("option", { name: "s_1 (PIADE machine)" });
    fireEvent.change(select, { target: { value: "s_1" } });
    expect(await screen.findByText("NEW-PERIOD")).toBeInTheDocument();
    releaseOld(mk("OLD-PERIOD"));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText("OLD-PERIOD")).toBeNull();
    expect(screen.getByText("NEW-PERIOD")).toBeInTheDocument();
  });
});
