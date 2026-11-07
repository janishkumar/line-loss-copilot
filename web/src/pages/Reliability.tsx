import { useState } from "react";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { getReliability } from "../api";
import AssetPicker, { scopeOf, type Selection } from "../components/AssetPicker";
import Citations from "../components/Citations";
import { Assumptions, Loading, Notice, RealBadge } from "../components/Common";
import { duration } from "../format";
import { useResult } from "../hooks";

export default function Reliability() {
  const [sel, setSel] = useState<Selection>({ lineId: "brick", start: "", end: "" });
  const { result, error } = useResult(() => getReliability({ ...scopeOf(sel), group: "month" }), [sel]);
  const rows = result?.data?.rows ?? [];
  const data = rows.map((r) => ({
    name: r.period,
    "MTTR (min)": r.mttr_s === null ? null : +(r.mttr_s / 60).toFixed(1),
    "MTBF (h)": r.mtbf_s === null ? null : +(r.mtbf_s / 3600).toFixed(1),
  }));
  const mini = (key: string, color: string) => (
    <div className="chart small" aria-label={`${key} by month`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.2} />
          <XAxis dataKey="name" tick={{ fill: "currentColor", fontSize: 11 }} />
          <YAxis tick={{ fill: "currentColor", fontSize: 11 }} />
          <Tooltip contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)" }} />
          <Line dataKey={key} stroke={color} strokeWidth={2} connectNulls={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
  return (
    <>
      <h2>Reliability <RealBadge /></h2>
      <AssetPicker value={sel} onChange={setSel} />
      {error && <Loading error={error} />}
      {!result && !error && <Loading error={null} />}
      {result && <Notice result={result} />}
      {result?.status === "ok" && result.data && (
        <>
          <div className="pair">
            <div><h3>MTTR by month</h3>{mini("MTTR (min)", "#2a7de1")}</div>
            <div><h3>MTBF by month</h3>{mini("MTBF (h)", "#2f9e6f")}</div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Month</th><th className="num">Failures</th><th className="num">Stops</th>
                  <th className="num">Failure time</th><th className="num">Run time</th>
                  <th className="num">MTTR</th><th className="num">MTBF</th><th>Source</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.period}>
                    <td>{r.period}</td>
                    <td className="num">{r.failure_count}</td>
                    <td className="num">{r.stop_count}</td>
                    <td className="num">{duration(r.failure_s)}</td>
                    <td className="num">{duration(r.run_s)}</td>
                    <td className="num">{duration(r.mttr_s)}</td>
                    <td className="num">{duration(r.mtbf_s)}</td>
                    <td><Citations count={r.citation_count} citations={r.citations} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Assumptions items={result.assumptions} />
        </>
      )}
    </>
  );
}
