import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { getBreakdown, getPareto, getRepeats } from "../api";
import AssetPicker, { scopeOf, type Selection } from "../components/AssetPicker";
import Citations from "../components/Citations";
import { Assumptions, Loading, Notice, RealBadge } from "../components/Common";
import { day, duration, pct } from "../format";
import { useResult } from "../hooks";

const PARETO_BY: Record<string, string[]> = {
  brick: ["reason", "reason_detail", "location", "product", "shift"],
  piade: ["reason", "alarm", "shift"],
};
const BREAK_DIMS: Record<string, string[]> = {
  brick: ["reason", "reason_detail", "location", "product", "weekday", "month"],
  piade: ["reason", "alarm", "shift_slot", "weekday", "month"],
};
const REPEAT_KEYS: Record<string, string[]> = {
  brick: ["reason", "reason_detail"],
  piade: ["reason", "alarm"],
};

type Chain = { machine_id: string | null; line_id: string; citations: { event_id: number | null }[] };

// The draft link names the events only when the chain's citations carry some.
export function newActionLink(c: Chain): string {
  const params = new URLSearchParams({ asset: c.machine_id ?? c.line_id });
  const ids = [...new Set(c.citations.map((x) => x.event_id).filter((x) => x !== null))];
  if (ids.length > 0) params.set("events", ids.join(","));
  return `/actions/new?${params}`;
}

export default function Losses() {
  const [sel, setSel] = useState<Selection>({ lineId: "brick", start: "", end: "" });
  const [by, setBy] = useState("reason");
  const [rowsDim, setRowsDim] = useState("reason");
  const [colsDim, setColsDim] = useState("month");
  const [key, setKey] = useState("reason");
  const sys = sel.lineId === "brick" ? "brick" : "piade";
  const scope = scopeOf(sel);

  const pick = (dims: string[], v: string, fallback: string) => (dims.includes(v) ? v : fallback);
  const byV = pick(PARETO_BY[sys], by, "reason");
  const rowsV = pick(BREAK_DIMS[sys], rowsDim, "reason");
  const colsV = pick(BREAK_DIMS[sys], colsDim, "month");
  const keyV = pick(REPEAT_KEYS[sys], key, "reason");

  const pareto = useResult(() => getPareto({ ...scope, by: byV }), [sel, byV]);
  const breakdown = useResult(() => getBreakdown({ ...scope, rows: rowsV, cols: colsV }), [sel, rowsV, colsV]);
  const repeats = useResult(() => getRepeats({ ...scope, key: keyV }), [sel, keyV]);

  const select = (label: string, v: string, dims: string[], set: (s: string) => void) => (
    <label>
      {label}
      <select value={v} onChange={(e) => set(e.target.value)}>
        {dims.map((d) => <option key={d} value={d}>{d}</option>)}
      </select>
    </label>
  );

  const p = pareto.result;
  const chart = (p?.data?.rows ?? []).map((r) => ({
    name: r.category, "Lost time (h)": +(r.lost_s / 3600).toFixed(2), "Cumulative share": r.cumulative_share,
  }));
  const b = breakdown.result;
  const cellMap = new Map((b?.data?.cells ?? []).map((c) => [`${c.row}\u0000${c.col}`, c]));
  const maxCell = Math.max(1, ...(b?.data?.cells ?? []).map((c) => c.lost_s));
  const r = repeats.result;

  return (
    <>
      <h2>Losses <RealBadge /></h2>
      <AssetPicker value={sel} onChange={setSel} />

      <h3>Pareto of lost time</h3>
      <div className="controls">{select("Rank by", byV, PARETO_BY[sys], setBy)}</div>
      {pareto.error && <Loading error={pareto.error} />}
      {!p && !pareto.error && <Loading error={null} />}
      {p && <Notice result={p} />}
      {p?.status === "ok" && p.data && (
        <>
          <p className="muted">
            {duration(p.data.total_lost_s)} lost over {p.data.total_stop_count} stops
            {p.data.other_categories ? `; ${p.data.other_categories} smaller categories are grouped as other` : ""}.
          </p>
          <div className="chart">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chart}>
                <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.2} />
                <XAxis dataKey="name" interval={0} tick={{ fill: "currentColor", fontSize: 11 }} />
                <YAxis yAxisId="h" tick={{ fill: "currentColor", fontSize: 12 }} />
                <YAxis yAxisId="c" orientation="right" domain={[0, 1]}
                       tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
                       tick={{ fill: "currentColor", fontSize: 12 }} />
                <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)" }} />
                <Legend />
                <Bar yAxisId="h" dataKey="Lost time (h)" fill="#2a7de1" />
                <Line yAxisId="c" dataKey="Cumulative share" stroke="#d9822b" strokeWidth={2} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>{p.data.by}</th><th className="num">Lost</th><th className="num">Stops</th>
                  <th className="num">Share</th><th className="num">Cumulative</th><th>Source</th></tr>
              </thead>
              <tbody>
                {p.data.rows.map((row) => (
                  <tr key={row.category}>
                    <td>{row.category}</td>
                    <td className="num">{duration(row.lost_s)}</td>
                    <td className="num">{row.stop_count}</td>
                    <td className="num">{pct(row.share)}</td>
                    <td className="num">{pct(row.cumulative_share)}</td>
                    <td><Citations count={row.citation_count} citations={row.citations} /></td>
                  </tr>
                ))}
                {p.data.other_categories > 0 && (
                  <tr>
                    <td>other ({p.data.other_categories} categories)</td>
                    <td className="num">{duration(p.data.other_lost_s)}</td>
                    <td className="num">{p.data.other_stop_count}</td>
                    <td className="num">{pct(p.data.total_lost_s ? p.data.other_lost_s / p.data.total_lost_s : null)}</td>
                    <td className="num"></td>
                    <td></td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Assumptions items={p.assumptions} />
        </>
      )}

      <h3>Breakdown</h3>
      <div className="controls">
        {select("Rows", rowsV, BREAK_DIMS[sys], setRowsDim)}
        {select("Columns", colsV, BREAK_DIMS[sys], setColsDim)}
      </div>
      {breakdown.error && <Loading error={breakdown.error} />}
      {!b && !breakdown.error && <Loading error={null} />}
      {b && <Notice result={b} />}
      {b?.status === "ok" && b.data && (
        <div className="table-wrap">
          <table className="heat">
            <thead>
              <tr><th>{b.data.rows} \ {b.data.cols}</th>{b.data.col_keys.map((c) => <th key={c} className="num">{c}</th>)}</tr>
            </thead>
            <tbody>
              {b.data.row_keys.map((rk) => (
                <tr key={rk}>
                  <td>{rk}</td>
                  {b.data!.col_keys.map((ck) => {
                    const cell = cellMap.get(`${rk}\u0000${ck}`);
                    const a = cell ? 0.55 * (cell.lost_s / maxCell) : 0;
                    return (
                      <td key={ck} className="num" style={{ background: `rgba(42,125,225,${a})` }}
                          title={cell ? `${cell.stop_count} stops` : "no stops"}>
                        {cell ? duration(cell.lost_s) : ""}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3>Repeat failure chains</h3>
      <div className="controls">{select("Chain by", keyV, REPEAT_KEYS[sys], setKey)}</div>
      {repeats.error && <Loading error={repeats.error} />}
      {!r && !repeats.error && <Loading error={null} />}
      {r && <Notice result={r} />}
      {r?.status === "ok" && r.data && (
        <>
          <p className="muted">
            {r.data.chain_count} chains of {r.data.min_repeats} or more failures, each within{" "}
            {r.data.within_hours} h of the last; {r.data.failure_count} failures in the window.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Machine</th><th>{r.data.key}</th><th className="num">Failures</th><th>From</th><th>To</th>
                  <th className="num">Lost</th><th>Source</th><th /></tr>
              </thead>
              <tbody>
                {r.data.chains.map((c, i) => (
                  <tr key={i}>
                    <td>{c.machine_id ?? c.line_id}</td>
                    <td>{c.key}</td>
                    <td className="num">{c.count}</td>
                    <td>{day(c.first_start)}</td>
                    <td>{day(c.last_end)}</td>
                    <td className="num">{duration(c.lost_s)}</td>
                    <td><Citations count={c.citation_count} citations={c.citations} /></td>
                    <td>
                      <Link
                        to={newActionLink(c)}
                      >
                        Draft work order
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Assumptions items={r.assumptions} />
        </>
      )}
    </>
  );
}
