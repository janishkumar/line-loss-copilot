import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { approveProposal, getAudit, getProposal, rejectProposal, type Outcome, type ProposalDetail } from "../api";
import { CheckList, OutcomeNotice } from "../components/Checks";
import { Loading } from "../components/Common";
import { duration } from "../format";
import { useResultPlain } from "../hooks";
import { useSession } from "../UserSwitcher";

// Mirrors [approve] in config/policy.toml for the disabled-button reason only; the server
// decides, and refuses with its own message if this ever drifts.
const APPROVE_ROLES: Record<string, string[]> = {
  work_order: ["shift_supervisor", "plant_manager"],
  quality_hold: ["quality_lead", "plant_manager"],
  follow_up: ["shift_supervisor"],
};

export function blockReason(p: ProposalDetail, user: { user_id: string; role: string } | null): string | null {
  if (p.status !== "pending") return `This proposal is already ${p.status}.`;
  if (!user) return "Pick a demo user to decide.";
  if (user.user_id === p.on_behalf_of) return "You cannot decide a proposal made on your behalf (or one you proposed).";
  if (user.user_id === p.principal) return "You cannot decide a proposal you proposed.";
  if (!APPROVE_ROLES[p.action]?.includes(user.role)) return `${user.role} may not approve a ${p.action}.`;
  return null;
}

export default function ApprovalDetail() {
  const { id = "" } = useParams();
  const { user } = useSession();
  const [tick, setTick] = useState(0);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const prop = useResultPlain(() => getProposal(id), [id, tick]);
  const audit = useResultPlain(() => getAudit(Number(id)), [id, tick]);

  async function decide(fn: typeof approveProposal) {
    setBusy(true);
    try {
      setOutcome(await fn(Number(id), note));
    } catch (e) {
      setOutcome({ outcome: "error", message: (e as Error).message, checks: [], proposal_id: null, target_id: null });
    } finally {
      setBusy(false);
      setTick((t) => t + 1);
    }
  }

  if (prop.error) return <Loading error={prop.error} />;
  const p = prop.data;
  if (!p) return <Loading error={null} />;
  const reason = blockReason(p, user);
  return (
    <>
      <h2>{p.summary}</h2>
      <p data-testid="origin">
        Proposed by {p.principal}, on behalf of {p.on_behalf_of}, channel {p.channel}.{" "}
        <span className="muted">Status: {p.status}</span>
      </p>

      {p.warnings.length > 0 && (
        <section className="notice" aria-label="Warnings">
          <strong>Read before deciding.</strong> Text that looks like an instruction was found. It is
          shown as data only; it changed nothing.
          {p.warnings.map((w, i) => <blockquote key={i}>{w.message}</blockquote>)}
        </section>
      )}

      <h3>Arguments</h3>
      <dl className="args">
        {Object.entries(p.args).map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{Array.isArray(v) ? v.join(", ") : String(v)}</dd></div>
        ))}
      </dl>

      <h3>Checks at proposal time</h3>
      <CheckList checks={p.checks} />

      <h3>Evidence</h3>
      {p.evidence.length === 0 ? <p className="muted">No linked events.</p> : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Event</th><th>Asset</th><th>Start</th><th className="num">Duration</th><th>Type</th><th>Reason</th><th>Alarm</th></tr></thead>
            <tbody>
              {p.evidence.map((e) => (
                <tr key={e.event_key}>
                  <td>
                    {e.present && e.current_event_id !== null
                      ? <Link to={`/evidence/${e.current_event_id}`}>event {e.current_event_id}</Link>
                      : <span className="block-text">event {e.event_id_at_link} is no longer present ({e.event_key})</span>}
                  </td>
                  <td>{e.machine_id ?? e.line_id ?? ""}</td>
                  <td>{e.start_ts?.slice(0, 16).replace("T", " ") ?? ""}</td>
                  <td className="num">{e.present ? duration(e.duration_s) : ""}</td>
                  <td>{e.event_type ?? ""}</td>
                  <td>{e.reason_code ?? ""}</td>
                  <td>{e.alarm_code ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {p.notes.length > 0 && (
        <>
          <h3>Linked operator notes</h3>
          <ul className="notes">
            {p.notes.map((n, i) => (
              <li key={i}>
                {n.source === "demo.injected_note" && (
                  <span className="badge" title="Planted for the injection demo; not an operator's note">Synthetic demo note</span>
                )}
                <div className="note-text">{n.text}</div>
                {n.translation ? (
                  <div className="muted">
                    <span className="note-text">{n.translation}</span>{" "}
                    <span className="badge">machine-translated · {n.translation_model}</span>
                  </div>
                ) : (
                  n.source === "core.note" && <div className="muted">No translation</div>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      <h3>Decision</h3>
      {outcome && <OutcomeNotice outcome={outcome} />}
      {p.status === "pending" ? (
        <>
          <div className="controls">
            <label>Note (required to reject)<input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} /></label>
            <button type="button" disabled={!!reason || busy} onClick={() => decide(approveProposal)}>Approve</button>
            <button type="button" disabled={!!reason || busy || !note.trim()} onClick={() => decide(rejectProposal)}>Reject</button>
          </div>
          {reason && <p className="muted">{reason} The server enforces this too.</p>}
        </>
      ) : (
        <p>
          {p.status} by {p.decided_by} on {p.decided_at?.slice(0, 16).replace("T", " ")}
          {p.decision_note ? `: ${p.decision_note}` : ""}
          {p.target_id !== null && <>. Created {p.action} <Link to="/actions">#{p.target_id}</Link>.</>}
        </p>
      )}

      <h3>History</h3>
      {audit.data && audit.data.length === 0 && <p className="muted">No audit rows.</p>}
      {audit.data && audit.data.length > 0 && (
        <ul>
          {audit.data.map((a) => (
            <li key={a.audit_id}>{a.at.slice(0, 19).replace("T", " ")} {a.event}: {a.outcome} ({a.principal}){a.detail ? `, ${a.detail}` : ""}</li>
          ))}
        </ul>
      )}
    </>
  );
}
