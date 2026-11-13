import "@testing-library/jest-dom/vitest";

// jsdom has no ResizeObserver. Recharts' ResponsiveContainer creates one in an effect, which
// only runs before a test ends on a slow machine, so CI failed now and then. A no-op stand-in
// in setup (not stubGlobal, which afterEach(vi.unstubAllGlobals) would remove) keeps it stable.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (!("ResizeObserver" in globalThis)) {
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}
