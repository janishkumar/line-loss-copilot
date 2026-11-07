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
