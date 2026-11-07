import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Overview from "./Overview";

const env = { citations: [], citation_count: 0, window: null, missing: null, assumptions: [] };
const assets = {
  ...env, status: "ok",
  data: {
    machines: [],
    lines: ["brick", "s_1"].map((line_id) => ({
      line_id, source_system: line_id === "brick" ? "brick" : "piade", source_timezone: "UTC",
      first_ts: "2020-01-01T00:00:00Z", last_ts: "2020-01-02T00:00:00Z", event_count: 1, machines: [],
    })),
  },
};
const shiftRow = (key: string, start: string) => ({
  key, start, metrics: { availability: 0.9, oee: 0.5 }, details: {}, citations: [], citation_count: 2,
});
const oee = (rows: ReturnType<typeof shiftRow>[]) => ({
  ...env, status: "ok",
  data: { source_system: "piade", group: "shift", rows, row_count: rows.length, rows_truncated: false },
});

class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

afterEach(() => vi.unstubAllGlobals());

describe("Overview", () => {
  it("labels PIADE shifts by start time and links each to its evidence", async () => {
    const rows = [
      shiftRow("piade:s_1:2020-01-01T06", "2020-01-01T06:00:00Z"),
      shiftRow("piade:s_1:2020-01-01T14", "2020-01-01T14:00:00Z"),
      shiftRow("piade:s_1:2020-01-01T22", "2020-01-01T22:00:00Z"),
    ];
    vi.stubGlobal("ResizeObserver", NoopResizeObserver);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
      ok: true,
      json: async () => (String(url).includes("/assets") ? assets : oee(rows)),
    })));
    render(<MemoryRouter><Overview /></MemoryRouter>);
    await screen.findByText("OEE overview");
    fireEvent.change(screen.getByLabelText("Line or machine"), { target: { value: "s_1" } });
    fireEvent.change(screen.getByLabelText("Group by"), { target: { value: "shift" } });
    const link = await screen.findByRole("link", { name: "2020-01-01 14:00" });
    expect(link).toHaveAttribute("href", "/evidence/shift/piade:s_1:2020-01-01T14");
    expect(within(link.closest("table")!).getAllByRole("link")).toHaveLength(3);
  });
});
