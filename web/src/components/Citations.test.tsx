import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Citations from "./Citations";
import { cite } from "../pages/testkit";

const r = (count: number, ids: number[]) =>
  render(<MemoryRouter><Citations count={count} citations={ids.map(cite)} /></MemoryRouter>);

describe("Citations", () => {
  it("links directly only for one row and one event", () => {
    r(1, [5]);
    expect(screen.getByRole("link", { name: "1 row" })).toHaveAttribute("href", "/evidence/5");
  });

  it("uses the list when several rows sit behind one returned event", () => {
    r(4, [5]);
    expect(screen.queryByRole("link", { name: "4 rows" })).toBeNull();
    expect(screen.getByText("4 rows")).toBeInTheDocument();
    expect(screen.getByText("showing 1 of 4")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "event 5" })).toHaveAttribute("href", "/evidence/5");
  });
});
