import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { previewAction, proposeAction, type ActionName, type Outcome, type Preview } from "../api";
import { CheckList, OutcomeNotice } from "../components/Checks";
import { useSession } from "../UserSwitcher";

const ROLES = ["operator", "shift_supervisor", "planner", "quality_lead", "plant_manager"];

type Form = Record<string, string>;

export function parseIds(raw: string): number[] {
  const parts = raw.split(/[,\s]+/).filter(Boolean);
  const ids = parts.map((p) => (/^\d+$/.test(p) ? Number(p) : NaN));
  if (ids.some(Number.isNaN)) throw new Error("Evidence event ids must be whole numbers separated by commas.");
  return ids;
}

function buildArgs(action: ActionName, f: Form): Record<string, unknown> {
  const evidence_event_ids = parseIds(f.events ?? "");
  if (action === "work_order")
    return { asset_id: f.asset, failure_mode: f.failure_mode, priority: f.priority, description: f.description, evidence_event_ids };
  if (action === "quality_hold") {
    const iso = (v: string) => (v ? new Date(v).toISOString() : v);
    return { asset_id: f.asset, product: f.product || null, window_start: iso(f.window_start), window_end: iso(f.window_end), reason: f.reason, evidence_event_ids };
  }
  return {
    assignee_role: f.assignee_role, due_date: f.due_date, description: f.description, evidence_event_ids,
    order_ids: (f.orders ?? "").split(/[,\s]+/).filter(Boolean),
  };
}

export default function NewAction() {
  const { user } = useSession();
  const [params] = useSearchParams();
  const [action, setAction] = useState<ActionName>(initialAction(params.get("action")));
  const [form, setForm] = useState<Form>({
    asset: params.get("asset") ?? "",
    events: parseSafe(params.get("events") ?? ""),
    orders: parseSafe(params.get("orders") ?? ""),
    priority: "low",
    assignee_role: ROLES.includes(params.get("role") ?? "") ? params.get("role")! : "shift_supervisor",
  });
  // The code stays in state only: it is bound to these exact arguments and is not for copying.
  const [pv, setPv] = useState<Preview | null>(null);
  const [out, setOut] = useState<Outcome | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reset = () => { setPv(null); setOut(null); setError(null); };
  const set = (k: string) => (e: { target: { value: string } }) => { setForm((f) => ({ ...f, [k]: e.target.value })); reset(); };
  const field = (k: string, label: string, props: Record<string, unknown> = {}) => (
    <label>{label}<input value={form[k] ?? ""} onChange={set(k)} {...props} /></label>
  );
  const area = (k: string, label: string) => (
    <label>{label}<textarea value={form[k] ?? ""} onChange={set(k)} rows={3} maxLength={2000} /></label>
  );

  async function doPreview() {
    reset();
    setBusy(true);
    try {
      setPv(await previewAction(action, buildArgs(action, form)));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function doPropose() {
    if (!pv) return;
    setBusy(true);
    try {
      setOut(await proposeAction(action, pv.args, pv.code));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const proposed = out?.outcome === "proposed" && out.proposal_id !== null;
  return (
    <>
      <h2>New action</h2>
      <p className="muted">
        Preview runs every check and changes nothing. Propose puts it in the approvals inbox; a
        different person approves it.
      </p>
      {!user && <p className="notice">Pick a demo user first (top right).</p>}
      <form className="action-form" onSubmit={(e) => { e.preventDefault(); doPreview(); }}>
        <label>Action type
          <select value={action} onChange={(e) => { setAction(e.target.value as ActionName); reset(); }}>
            <option value="work_order">Work order</option>
            <option value="quality_hold">Quality hold</option>
            <option value="follow_up">Follow-up</option>
          </select>
        </label>
        {action !== "follow_up" && field("asset", "Asset", { placeholder: "s_3 or brick" })}
        {action === "work_order" && (<>
          {field("failure_mode", "Failure mode")}
          <label>Priority
            <select value={form.priority} onChange={set("priority")}>
              {["low", "medium", "high", "critical"].map((p) => <option key={p}>{p}</option>)}
            </select>
          </label>
          {area("description", "Description")}
        </>)}
        {action === "quality_hold" && (<>
          {field("product", "Product (optional)")}
          {field("window_start", "Window start", { type: "datetime-local" })}
          {field("window_end", "Window end", { type: "datetime-local" })}
          {area("reason", "Reason")}
        </>)}
        {action === "follow_up" && (<>
          <label>Assignee role
            <select value={form.assignee_role} onChange={set("assignee_role")}>
              {ROLES.map((r) => <option key={r}>{r}</option>)}
            </select>
          </label>
          {field("due_date", "Due date", { type: "date" })}
          {area("description", "Description")}
          {field("orders", "Order ids", { placeholder: "SO-1001, SO-1002" })}
        </>)}
        {field("events", "Evidence event ids", { placeholder: "11, 12, 13" })}
        <button type="submit" disabled={!user || busy}>Preview</button>
      </form>

      {error && <div className="notice" role="alert">{error}</div>}
      {pv && (
        <section aria-label="Preview">
          <h3>Preview</h3>
          <p>{pv.summary}</p>
          <CheckList checks={pv.checks} />
          {pv.blocked || !pv.code
            ? <p className="muted">A check blocks this, so it cannot be proposed. Change the details and preview again.</p>
            : !proposed && <button type="button" disabled={busy} onClick={doPropose}>Propose</button>}
        </section>
      )}
      {out && !proposed && <OutcomeNotice outcome={out} />}
      {proposed && (
        <div className="notice ok" role="status">
          Proposal {out!.proposal_id} is waiting for approval. <Link to={`/approvals/${out!.proposal_id}`}>Open in the inbox</Link>
        </div>
      )}
    </>
  );
}

function initialAction(raw: string | null): ActionName {
  return raw === "follow_up" || raw === "quality_hold" ? raw : "work_order";
}

function parseSafe(raw: string): string {
  return raw.split(/[,\s]+/).filter(Boolean).join(", ");
}
