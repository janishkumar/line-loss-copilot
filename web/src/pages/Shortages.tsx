import { Link } from "react-router-dom";
import { getShortages } from "../api";
import { Assumptions, Loading, Notice, SyntheticBadge } from "../components/Common";
import { day } from "../format";
import { useResult } from "../hooks";

const MAX_ORDERS = 20; // a follow-up links at most 20 orders

export function followUpLink(orderIds: string[]): string {
  const ids = [...new Set(orderIds)].sort().slice(0, MAX_ORDERS);
  return `/actions/new?${new URLSearchParams({ action: "follow_up", role: "planner", orders: ids.join(",") })}`;
}

export default function Shortages() {
  const { result, error } = useResult(getShortages, []);
  const data = result?.data;
  return (
    <>
      <h2>Shortages <SyntheticBadge /></h2>
      <p className="muted">
        Raw materials that run out before an order needs them, traced to the exact orders they hit.
        Orders, BOMs, stock and receipts are generated; no number here is a real production result.
      </p>
      {!result && <Loading error={error} />}
      {result && <Notice result={result} />}
      {data && (
        <>
          <p>{data.total} shortfall(s) found{data.rows.length < data.total ? `, showing ${data.rows.length}` : ""}.</p>
          {data.by_material.map((m) => {
            const rows = data.rows.filter((r) => r.material_id === m.material_id);
            return (
              <section key={m.material_id} aria-label={`Shortage of ${m.material_id}`}>
                <h3>
                  {m.material_name ?? m.material_id} <span className="muted">({m.material_id})</span>
                </h3>
                <p className="muted">
                  {m.orders} order(s), {m.short_qty} short in total.{" "}
                  <Link to={followUpLink(rows.map((r) => r.order_id))}>Draft follow-up</Link>
                  {rows.length > MAX_ORDERS && ` (first ${MAX_ORDERS} of ${rows.length} orders)`}
                </p>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th>Order</th><th>Product</th><th>Short qty</th><th>First short</th><th>Due</th><th>BOM</th></tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.order_id}>
                          <td><Link to={`/orders/${encodeURIComponent(r.order_id)}`}>{r.order_id}</Link></td>
                          <td>{r.product_id ?? ""}</td>
                          <td>{r.short_qty}</td>
                          <td>{day(r.first_short_at)}</td>
                          <td>{day(r.due_at)}</td>
                          <td>{r.bom_level > 1 ? `level ${r.bom_level}` : "direct"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            );
          })}
        </>
      )}
      {result && <Assumptions items={result.assumptions} />}
    </>
  );
}
