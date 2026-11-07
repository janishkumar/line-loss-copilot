import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Shortages, { followUpLink } from "./Shortages";
import { env, mockFetch } from "./testkit";

afterEach(() => vi.unstubAllGlobals());

const row = (material_id: string, order_id: string, level: number, at: string) => ({
  material_id, material_name: `Mat ${material_id}`, order_id, short_qty: 12.5, first_short_at: at,
  bom_level: level, product_id: "P1", due_at: "2021-07-09T00:00:00Z",
});
const shortages = {
  ...env, status: "ok", assumptions: ["Synthetic data: generation 1, seed 7."],
  data: {
    label: "synthetic orders on real capacity", is_synthetic: true, generation_id: 1, seed: 7, total: 3,
    by_material: [{ material_id: "R1", material_name: "Mat R1", orders: 2, short_qty: 25 },
      { material_id: "R2", material_name: "Mat R2", orders: 1, short_qty: 12.5 }],
    rows: [row("R1", "O-1", 1, "2021-07-02T00:00:00Z"), row("R1", "O-2", 2, "2021-07-03T00:00:00Z"),
      row("R2", "O-3", 1, "2021-07-04T00:00:00Z")],
  },
};

describe("followUpLink", () => {
  it("names the follow-up action and the orders, deduplicated", () => {
    expect(followUpLink(["O-2", "O-1", "O-2"])).toBe("/actions/new?action=follow_up&orders=O-1%2CO-2");
  });
});

describe("Shortages", () => {
  it("lists traced orders with links and a prefilled follow-up draft per material", async () => {
    mockFetch({ "/shortages": shortages });
    render(<MemoryRouter><Shortages /></MemoryRouter>);
    expect(await screen.findByText("Synthetic orders on real capacity")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "O-1" })).toHaveAttribute("href", "/orders/O-1");
    expect(screen.getByRole("link", { name: "O-3" })).toHaveAttribute("href", "/orders/O-3");
    const drafts = screen.getAllByRole("link", { name: "Draft follow-up" });
    expect(drafts[0]).toHaveAttribute("href", "/actions/new?action=follow_up&orders=O-1%2CO-2");
    expect(drafts[1]).toHaveAttribute("href", "/actions/new?action=follow_up&orders=O-3");
    expect(screen.getByText("level 2")).toBeInTheDocument();
  });

  it("shows the missing text when nothing is stored", async () => {
    mockFetch({ "/shortages": { ...env, status: "insufficient_evidence", data: null,
      missing: "no synthetic data is loaded: run `make synth` first" } });
    render(<MemoryRouter><Shortages /></MemoryRouter>);
    expect(await screen.findByText(/run `make synth` first/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
