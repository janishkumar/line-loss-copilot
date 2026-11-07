import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Chat, { visibleAnswer } from "./Chat";
import { cite } from "./testkit";

afterEach(() => vi.unstubAllGlobals());

const result = (over: Record<string, unknown> = {}) => ({
  answer: "Top loss was A_065 [event:11], see also [event:99].\nANSWER: A_065",
  citations: [cite(11), cite(12)],
  citation_count: 2,
  cited_event_ids: [11, 99],
  unsupported_cited_ids: [99],
  tool_calls: [{ name: "loss_pareto", args: { machine_id: "s_1", by: "reason" }, status: "ok", missing: null }],
  model: "qwen2.5:7b-instruct",
  rounds: 2,
  ...over,
});

/** Stubs fetch with a queue of [status, body] replies; returns the mock to inspect calls. */
function stubChat(...replies: [number, unknown][]) {
  const pending: Array<() => void> = [];
  const fn = vi.fn(async (_url: string, _init?: RequestInit) => {
    const [status, body] = replies.shift() ?? [500, null];
    await new Promise<void>((r) => pending.push(r));
    return { ok: status < 300, status, statusText: "", json: async () => body };
  });
  vi.stubGlobal("fetch", fn);
  return { fn, release: () => pending.splice(0).forEach((r) => r()) };
}

const ask = (text: string) => {
  fireEvent.change(screen.getByLabelText("Question"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
};

describe("Chat", () => {
  it("shows thinking, then the answer with event links, trace, model and warning", async () => {
    const { fn, release } = stubChat([200, result()]);
    render(<MemoryRouter><Chat /></MemoryRouter>);
    ask("top loss on s_1 in March 2021?");
    expect(screen.getByRole("status")).toHaveTextContent(/Thinking/);
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await act(async () => release());
    expect(await screen.findByText(/Top loss was A_065/)).toBeInTheDocument();
    expect(screen.queryByText(/ANSWER:/)).toBeNull();
    expect(screen.getAllByRole("link", { name: "event 11" })[0]).toHaveAttribute("href", "/evidence/11");
    expect(screen.getByText(/machine-generated · qwen2.5:7b-instruct/)).toBeInTheDocument();
    expect(screen.getByText("2 rows")).toBeInTheDocument();
    expect(screen.getByText(/Tool trace \(1 call, 2 rounds\)/)).toBeInTheDocument();
    expect(screen.getByText("loss_pareto")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/event 99 did not appear/);
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/chat");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      messages: [{ role: "user", content: "top loss on s_1 in March 2021?" }],
    });
  });

  it("sends the history as user and assistant turns only", async () => {
    const { fn, release } = stubChat(
      [200, result({ unsupported_cited_ids: [] })],
      [200, result({ answer: "Second.\nANSWER: 2", unsupported_cited_ids: [] })],
    );
    render(<MemoryRouter><Chat /></MemoryRouter>);
    ask("first");
    await act(async () => release());
    await screen.findByText(/Top loss was/);
    ask("second");
    await act(async () => release());
    await screen.findByText("Second.");
    const sent = JSON.parse(String(fn.mock.calls[1][1]?.body)).messages;
    expect(sent.map((m: { role: string }) => m.role)).toEqual(["user", "assistant", "user"]);
    expect(sent[1].content).not.toContain("ANSWER:");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows the server's message when the local model is not reachable", async () => {
    const { release } = stubChat([503, {
      status: "out_of_scope", data: null, citations: [], citation_count: 0, window: null,
      assumptions: [], missing: "local model not reachable at http://localhost:11434",
    }]);
    render(<MemoryRouter><Chat /></MemoryRouter>);
    ask("hello");
    await act(async () => release());
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "local model not reachable at http://localhost:11434",
    );
  });

  it("renders model text as text, not markup", async () => {
    const { release } = stubChat([200, result({ answer: "<img src=x onerror=alert(1)> hi\nANSWER: x", unsupported_cited_ids: [] })]);
    const { container } = render(<MemoryRouter><Chat /></MemoryRouter>);
    ask("x");
    await act(async () => release());
    expect(await screen.findByText(/hi$/)).toHaveTextContent("<img src=x");
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("event links", () => {
  it("links every id in a grouped citation", async () => {
    const { release } = stubChat([200, result({ answer: "Lost [event:5, event:6] and [event:7, 8].\nANSWER: x", unsupported_cited_ids: [], citation_count: 0 })]);
    render(<MemoryRouter><Chat /></MemoryRouter>);
    ask("x");
    await act(async () => release());
    for (const id of [5, 6, 7, 8])
      expect(await screen.findByRole("link", { name: `event ${id}` })).toHaveAttribute("href", `/evidence/${id}`);
  });
});

describe("visibleAnswer", () => {
  it("drops the ANSWER line, trailing or on its own line", () => {
    expect(visibleAnswer("Body.\nANSWER: x")).toBe("Body.");
    expect(visibleAnswer("Body. ANSWER: x")).toBe("Body.");
    expect(visibleAnswer("ANSWER: only this")).toBe("only this");
    expect(visibleAnswer("No line")).toBe("No line");
  });
});
