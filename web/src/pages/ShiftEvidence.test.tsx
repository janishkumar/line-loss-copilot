import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import ShiftEvidence from "./ShiftEvidence";

const row = (event_id: number, raw_table: string, source_row: number) => ({
  event_id, raw_table, source_file: `brick/${raw_table}.csv`, source_row,
  raw: { source_row, note: "grasarisma" },
});

afterEach(() => vi.unstubAllGlobals());

describe("ShiftEvidence", () => {
  it("groups rows by raw table and file", async () => {
    const fetchMock = vi.fn(async (_url: string) => ({
      ok: true,
      json: async () => ({
        status: "ok", citations: [], citation_count: 3, window: null, missing: null,
        assumptions: ["rows as loaded"],
        data: {
          shift_id: "brick:2025-10-16", source_system: "brick", event_count: 3, truncated: false,
          rows: [row(1, "brick_oee", 5), row(2, "brick_downtime", 7), row(3, "brick_downtime", 9)],
        },
      }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter initialEntries={["/evidence/shift/brick:2025-10-16"]}>
        <Routes><Route path="/evidence/shift/:shiftId" element={<ShiftEvidence />} /></Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText(/3 events behind/)).toBeInTheDocument();
    expect(screen.getAllByRole("table")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "2" })).toHaveAttribute("href", "/evidence/2");
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/shifts/brick%3A2025-10-16/evidence");
  });
});
