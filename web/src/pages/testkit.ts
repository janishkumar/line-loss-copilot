import { vi } from "vitest";

export const env = { citations: [], citation_count: 0, window: null, missing: null, assumptions: [] };
export const assets = {
  ...env, status: "ok",
  data: {
    machines: [],
    lines: ["brick", "s_1", "s_2"].map((line_id) => ({
      line_id, source_system: line_id === "brick" ? "brick" : "piade", source_timezone: "UTC",
      first_ts: "2020-01-01T00:00:00Z", last_ts: "2020-01-02T00:00:00Z", event_count: 1, machines: [],
    })),
  },
};
export const cite = (event_id: number) => ({
  raw_table: "brick_stops_raw", source_file: "brick/x.csv", raw_row_id: event_id, event_id, field: null,
});

export class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

/** Stubs fetch: `/assets` is served, other URLs go through `routes` (substring match, first wins). */
export function mockFetch(routes: Record<string, unknown>) {
  vi.stubGlobal("ResizeObserver", NoopResizeObserver);
  const fn = vi.fn(async (url: string) => {
    const u = String(url);
    const hit = u.includes("/assets") ? assets : Object.entries(routes).find(([k]) => u.includes(k))?.[1];
    return { ok: !!hit, status: hit ? 200 : 404, statusText: "", json: async () => hit };
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

export type ApiReply = [number, unknown];

/** Stubs fetch for the approvals pages: `routes` maps "METHOD /path-substring" to a reply (or a
 * function of the parsed body). Returns the mock so tests can inspect calls. */
export function mockApi(routes: Record<string, ApiReply | ((body: unknown) => ApiReply)>) {
  const fn = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const key = Object.keys(routes).find((k) => {
      const [m, ...rest] = k.split(" ");
      return m === method && String(url).includes(rest.join(" "));
    });
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    const hit = key ? routes[key] : undefined;
    const [status, data] = typeof hit === "function" ? hit(body) : (hit ?? [404, { detail: "no route" }]);
    return { ok: status < 300, status, statusText: "", json: async () => data };
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

export const demoUsers = [
  { user_id: "sup.a", display_name: "Supervisor A", role: "shift_supervisor", source: "synthetic" },
  { user_id: "sup.b", display_name: "Supervisor B", role: "shift_supervisor", source: "synthetic" },
  { user_id: "pm.a", display_name: "Plant manager A", role: "plant_manager", source: "synthetic" },
];
