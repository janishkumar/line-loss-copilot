import { useState } from "react";
import { Link } from "react-router-dom";
import { changeStatus, getActions, type ActionKind, type Outcome } from "../api";
import { OutcomeNotice } from "../components/Checks";
import { Loading } from "../components/Common";
import { useResultPlain } from "../hooks";

type Row = Record<string, unknown>;
const text = (v: unknown) => (v === null || v === undefined ? "" : String(v).replace("T", " ").slice(0, 16));

const KINDS: { kind: ActionKind; title: string; idKey: string; verb: "close" | "release" | "complete";
  label: string; openStatus: string; cols: [string, string][] }[] = [
  { kind: "work_orders", title: "Work orders", idKey: "work_order_id", verb: "close", label: "Close", openStatus: "open",
    cols: [["asset_id", "Asset"], ["failure_mode", "Failure mode"], ["priority", "Priority"], ["status", "Status"], ["created_by", "Created by"], ["created_at", "Created"]] },
  { kind: "quality_holds", title: "Quality holds", idKey: "hold_id", verb: "release", label: "Release", openStatus: "active",
    cols: [["asset_id", "Asset"], ["product", "Product"], ["window_start", "From"], ["window_end", "To"], ["status", "Status"], ["created_by", "Created by"]] },
  { kind: "follow_ups", title: "Follow-ups", idKey: "follow_up_id", verb: "complete", label: "Complete", openStatus: "open",
    cols: [["assignee_role", "Assignee role"], ["due_date", "Due"], ["description", "Description"], ["status", "Status"], ["created_by", "Created by"]] },
];

function Section({ spec, onOutcome }: { spec: (typeof KINDS)[number]; onOutcome: (o: Outcome) => void }) {
  const [tick, setTick] = useState(0);
  const rows = useResultPlain(() => getActions(spec.kind), [tick]);
  return (
    <>
      <h3>{spec.title}</h3>
      {rows.error && <Loading error={rows.error} />}
      {rows.data && rows.data.length === 0 && <p className="muted">None yet. They appear here after a person approves a proposal.</p>}
      {rows.data && rows.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th>{spec.cols.map(([, h]) => <th key={h}>{h}</th>)}<th>Proposal</th><th /></tr></thead>
            <tbody>
              {rows.data.map((r: Row) => (
                <tr key={String(r[spec.idKey])}>
                  <td>{String(r[spec.idKey])}</td>
                  {spec.cols.map(([k]) => <td key={k} className="text">{text(r[k])}</td>)}
                  <td><Link to={`/approvals/${r.proposal_id}`}>#{String(r.proposal_id)}</Link></td>
                  <td>
                    {r.status === spec.openStatus && (
                      <button type="button" onClick={async () => {
                        onOutcome(await changeStatus(spec.kind, Number(r[spec.idKey]), spec.verb));
                        setTick((t) => t + 1);
                      }}>{spec.label}</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default function Actions() {
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  return (
    <>
      <h2>Approved actions</h2>
      <p className="muted">
        Rows here were written after a person approved a proposal. Closing, releasing or completing
        needs a signed-in person with the right role; the server decides.
      </p>
      {outcome && <OutcomeNotice outcome={outcome} />}
      {KINDS.map((k) => <Section key={k.kind} spec={k} onOutcome={setOutcome} />)}
    </>
  );
}
