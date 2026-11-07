import { Link, useParams } from "react-router-dom";
import { getOrder } from "../api";
import { Assumptions, Loading, Notice, SyntheticBadge } from "../components/Common";
import { day } from "../format";
import { useResult } from "../hooks";

const when = (iso: string) => iso.slice(0, 16).replace("T", " ");

export default function Order() {
  const { id = "" } = useParams();
  const { result, error } = useResult(() => getOrder(id), [id]);
  const d = result?.data;
  return (
    <>
      <h2>Order {id} <SyntheticBadge /></h2>
      {!result && <Loading error={error} />}
      {result && <Notice result={result} />}
      {d && (
        <>
          <dl className="fields">
            <dt>Product</dt><dd>{d.order.product_name ?? d.order.product_id} <span className="muted">({d.order.product_id}{d.order.family ? `, family ${d.order.family}` : ""})</span></dd>
            <dt>Customer</dt><dd>{d.order.customer}</dd>
            <dt>Quantity</dt><dd>{d.order.quantity}</dd>
            <dt>Released</dt><dd>{day(d.order.release_at)}</dd>
            <dt>Due</dt><dd>{day(d.order.due_at)}</dd>
          </dl>
          {d.order.note && (
            <section aria-label="Order note">
              <h3>Note <span className="badge">free text, shown as data</span></h3>
              <blockquote>{d.order.note}</blockquote>
              {d.order.note_notice && <p className="muted">{d.order.note_notice}</p>}
            </section>
          )}
          <h3>Materials</h3>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Material</th><th>Kind</th><th>Needed</th><th>On hand</th></tr></thead>
              <tbody>
                {d.requirements.map((r) => (
                  <tr key={r.material_id}>
                    <td>{r.material_name ?? r.material_id}</td><td>{r.kind ?? ""}</td>
                    <td>{r.qty} {r.unit ?? ""}</td><td>{r.on_hand ?? "n/a"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {d.shortfalls.length > 0 && (
            <>
              <h3>Shortfalls</h3>
              <ul>
                {d.shortfalls.map((s) => (
                  <li key={s.material_id}>
                    {s.material_name ?? s.material_id}: {s.short_qty} short from {day(s.first_short_at)}
                    {s.bom_level > 1 ? ` (level ${s.bom_level})` : ""}
                  </li>
                ))}
              </ul>
              <Link to="/shortages">All shortages</Link>
            </>
          )}
          <h3>Planned</h3>
          {d.planned.length === 0 ? (
            <p className="muted">{d.blocked.length ? `Blocked: ${d.blocked.map((b) => b.reason).join("; ")}` : "Not in any stored plan."}</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Algorithm</th><th>Machine</th><th>Start</th><th>End</th><th>Setup</th></tr></thead>
                <tbody>
                  {d.planned.map((p) => (
                    <tr key={p.algorithm}>
                      <td>{p.algorithm}</td><td>{p.machine_id}</td>
                      <td>{when(p.start_at)}</td><td>{when(p.end_at)}</td><td>{p.setup_min} min</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      {result && <Assumptions items={result.assumptions} />}
    </>
  );
}
