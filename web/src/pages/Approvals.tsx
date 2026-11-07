import { useState } from "react";
import { Link } from "react-router-dom";
import { getProposals } from "../api";
import { Loading } from "../components/Common";
import { useResultPlain } from "../hooks";

const STATUSES = ["pending", "approved", "rejected", "all"] as const;

export default function Approvals() {
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("pending");
  const list = useResultPlain(() => getProposals(status === "all" ? undefined : status), [status]);
  return (
    <>
      <h2>Approvals inbox</h2>
      <p className="muted">
        The copilot and the form only propose. A person with the right role, who did not propose it,
        approves here.
      </p>
      <div className="controls">
        <label>
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
            {STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <Link to="/actions/new">New action</Link>
      </div>
      {list.error && <Loading error={list.error} />}
      {!list.data && !list.error && <Loading error={null} />}
      {list.data && list.data.length === 0 && <p className="muted">No {status === "all" ? "" : status} proposals.</p>}
      {list.data && list.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Proposal</th><th>Type</th><th>Status</th><th>Proposed by</th><th>On behalf of</th><th>Channel</th><th>Created</th></tr>
            </thead>
            <tbody>
              {list.data.map((p) => (
                <tr key={p.proposal_id}>
                  <td><Link to={`/approvals/${p.proposal_id}`}>{p.summary}</Link></td>
                  <td>{p.action}</td>
                  <td>{p.status}</td>
                  <td>{p.principal}</td>
                  <td>{p.on_behalf_of}</td>
                  <td>{p.channel}</td>
                  <td>{p.created_at.slice(0, 16).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
