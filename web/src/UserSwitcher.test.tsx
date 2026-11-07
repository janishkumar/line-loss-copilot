import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import UserSwitcher, { SessionProvider } from "./UserSwitcher";
import { demoUsers, mockApi } from "./pages/testkit";

afterEach(() => vi.unstubAllGlobals());

describe("UserSwitcher", () => {
  it("starts a session for the chosen demo user and shows the synthetic badge", async () => {
    const fn = mockApi({
      "GET /api/users": [200, demoUsers],
      "GET /api/session": [200, { user: null }],
      "POST /api/session": (b) => [200, { user: { ...demoUsers[0], ...(b as object) } }],
    });
    render(<SessionProvider><UserSwitcher /></SessionProvider>);
    expect(await screen.findByText("Not signed in")).toBeInTheDocument();
    expect(screen.queryByText("Synthetic demo user")).toBeNull();
    fireEvent.change(await screen.findByLabelText("Demo user"), { target: { value: "sup.a" } });
    expect(await screen.findByText("Synthetic demo user")).toBeInTheDocument();
    const post = fn.mock.calls.find(([, i]) => i?.method === "POST")!;
    expect(JSON.parse(String(post[1]!.body))).toEqual({ user_id: "sup.a" });
    expect(post[1]!.credentials).toBe("same-origin");
    expect(screen.getByText(/shift_supervisor/)).toBeInTheDocument();
  });

  it("signs out", async () => {
    mockApi({
      "GET /api/users": [200, demoUsers],
      "GET /api/session": [200, { user: demoUsers[0] }],
      "DELETE /api/session": [200, { user: null }],
    });
    render(<SessionProvider><UserSwitcher /></SessionProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByText("Not signed in")).toBeInTheDocument();
  });
});
