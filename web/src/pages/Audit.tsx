import { Link } from "react-router-dom";
import { getAudit } from "../api";
import { Loading } from "../components/Common";
import { useResultPlain } from "../hooks";

export default function Audit() {
  const audit = useResultPlain(() => getAudit(), []);
  return (
    <>
      <h2>Audit log</h2>
      <p className="muted">
        Every step is recorded, including previews, refusals and blocked approvals. Rows cannot be
        changed or deleted. Newest first.
      </p>
      {audit.error && <Loading error={audit.error} />}
      {!audit.data && !audit.error && <Loading error={null} />}
      {audit.data && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>When (UTC)</th><th>Event</th><th>Outcome</th><th>Action</th><th>Proposal</th><th>Principal</th><th>On behalf of</th><th>Channel</th><th>Detail</th></tr>
            </thead>
            <tbody>
              {audit.data.map((a) => (
                <tr key={a.audit_id}>
                  <td>{a.at.slice(0, 19).replace("T", " ")}</td>
                  <td>{a.event}</td>
                  <td>{a.outcome}</td>
                  <td>{a.action ?? ""}</td>
                  <td>{a.proposal_id !== null && <Link to={`/approvals/${a.proposal_id}`}>#{a.proposal_id}</Link>}</td>
                  <td>{a.principal}</td>
                  <td>{a.on_behalf_of ?? ""}</td>
                  <td>{a.channel ?? ""}</td>
                  <td className="text">{a.detail ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
