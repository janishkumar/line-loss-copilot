import { useState } from "react";
import { Link } from "react-router-dom";
import { getPlan, type PlanOut, type Range } from "../api";
import { Assumptions, Loading, Notice, SyntheticBadge } from "../components/Common";
import { useResult } from "../hooks";

const ORDER = ["cpsat", "edd_batch", "edd", "fifo"];
const min = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : `${Math.round(v)} min`);
const iqr = (r: Range, unit = " min") =>
  r.q1 === null || r.q3 === null ? "n/a" : `${Math.round(r.q1)} to ${Math.round(r.q3)}${unit}`;

/** Left offset and width of a bar as percentages of the timeline span (epoch milliseconds). */
export function barStyle(startIso: string, endIso: string, t0: number, t1: number) {
  const span = Math.max(1, t1 - t0);
  const pct = (v: number) => `${Math.round((v / span) * 10000) / 100}%`;
  return { left: pct(Date.parse(startIso) - t0), width: pct(Date.parse(endIso) - Date.parse(startIso)) };
}

function Timeline({ plan }: { plan: PlanOut }) {
  const all = Object.values(plan.sequences).flat();
  if (!all.length) return <p className="muted">No assignments in this plan.</p>;
  const t0 = Math.min(...all.map((a) => Date.parse(a.start_at)));
  const t1 = Math.max(...all.map((a) => Date.parse(a.end_at)));
  return (
    <div className="timeline">
      {Object.entries(plan.sequences).sort().map(([machine, seq]) => (
        <div className="lane" key={machine}>
          <span className="lane-label">{machine}</span>
          <div className="lane-track">
            {seq.map((a) => (
              <Link
                key={a.order_id}
                className="bar"
                style={barStyle(a.start_at, a.end_at, t0, t1)}
                to={`/orders/${encodeURIComponent(a.order_id)}`}
                title={`${a.order_id}: ${a.start_at.slice(0, 16)} to ${a.end_at.slice(0, 16)}, setup ${a.setup_min} min`}
              >
                {a.order_id}
              </Link>
            ))}
          </div>
          {plan.sequence_lengths[machine] > seq.length && (
            <span className="muted"> first {seq.length} of {plan.sequence_lengths[machine]}</span>
          )}
        </div>
      ))}
    </div>
  );
}

export default function Plan() {
  const { result, error } = useResult(getPlan, []);
  const [pick, setPick] = useState("cpsat");
  const data = result?.data;
  const plans = data ? [...data.plans].sort((a, b) => ORDER.indexOf(a.algorithm) - ORDER.indexOf(b.algorithm)) : [];
  const shown = plans.find((p) => p.algorithm === pick) ?? plans[0];
  return (
    <>
      <h2>Plan <SyntheticBadge /></h2>
      <p className="muted">
        The schedule for synthetic customer orders on real machine rates, availability and
        changeover times, and how it holds up when real PIADE stops from a later period are replayed
        against it.
      </p>
      {!result && <Loading error={error} />}
      {result && <Notice result={result} />}
      {data?.stale && (
        <div className="notice" role="alert">
          This plan was made from an older generation than the live synthetic data. Run `make plan`.
        </div>
      )}
      {data && (
        <>
          <h3>Results by algorithm</h3>
          <div className="table-wrap">
            <table aria-label="Plan KPIs">
              <thead>
                <tr>
                  <th rowSpan={2}>Algorithm</th>
                  <th colSpan={3}>Nominal</th>
                  <th colSpan={3}>Replayed on real stops (median and interquartile range over this plan's windows)</th>
                </tr>
                <tr>
                  <th>Late orders</th><th>Tardiness</th><th>Changeover</th>
                  <th>Late orders</th><th>Tardiness</th><th>Changeover</th>
                </tr>
              </thead>
              <tbody>
                {plans.map((p) => (
                  <tr key={p.algorithm}>
                    <td>{p.algorithm}</td>
                    <td>{p.kpis_nominal.late_orders}</td>
                    <td>{min(p.kpis_nominal.total_tardiness_min)}</td>
                    <td>{min(p.kpis_nominal.changeover_min)}</td>
                    <td>{p.kpis_replayed.late_orders.median ?? "n/a"}<br /><span className="muted">{iqr(p.kpis_replayed.late_orders, "")}</span></td>
                    <td>{min(p.kpis_replayed.total_tardiness_min.median)}<br /><span className="muted">{iqr(p.kpis_replayed.total_tardiness_min)}</span></td>
                    <td>{min(p.kpis_replayed.changeover_min.median)}<br /><span className="muted">{iqr(p.kpis_replayed.changeover_min)}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">
            Synthetic orders on real capacity and real stops: a software test, not a production result.
            Replay windows: {plans[0]?.kpis_replayed.windows}.
          </p>
          <p className="muted">
            Dates: the synthetic horizon is a made-up two weeks starting 2026-01-05. Real stops from
            the 2021 replay windows are mapped onto it by offset from each window start, so a 2026
            date here stands for a day in a 2021 window.
          </p>
          {shown && (
            <>
              <h3>Timeline</h3>
              <label>Algorithm{" "}
                <select value={shown.algorithm} onChange={(e) => setPick(e.target.value)}>
                  {plans.map((p) => <option key={p.algorithm}>{p.algorithm}</option>)}
                </select>
              </label>
              {shown.solver_status && (
                <p className="muted">Solver status {shown.solver_status}{shown.stop_reason ? `, stopped by ${shown.stop_reason}` : ""}.</p>
              )}
              <Timeline plan={shown} />
              <h3>Blocked orders</h3>
              {shown.blocked_count === 0 ? (
                <p className="muted">None.</p>
              ) : (
                <>
                  <p className="muted">Excluded from tardiness: {shown.blocked_count} order(s) cannot be scheduled.</p>
                  <ul>
                    {shown.blocked.map((b) => (
                      <li key={b.order_id}>
                        <Link to={`/orders/${encodeURIComponent(b.order_id)}`}>{b.order_id}</Link>{" "}
                        <span>{b.reason}</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </>
      )}
      {result && <Assumptions items={result.assumptions} />}
    </>
  );
}
