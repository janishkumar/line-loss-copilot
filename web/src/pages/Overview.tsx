import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { getAssets, getOee, type AssetsData, type OeeData, type Result } from "../api";
import { Assumptions, Loading, Notice, RealBadge } from "../components/Common";
import { day, pct } from "../format";

type Group = "shift" | "day" | "month";

const SERIES: Record<string, { label: string; keys: string[] }[]> = {
  brick: [
    { label: "Availability", keys: ["availability_calc"] },
    { label: "Performance (published)", keys: ["performance_pub"] },
    { label: "Quality (published)", keys: ["quality_pub"] },
    { label: "OEE", keys: ["oee_calc_with_pub_pq"] },
  ],
  piade: [
    { label: "Availability", keys: ["availability"] },
    { label: "Performance", keys: ["performance_count_p95"] },
    { label: "Quality", keys: ["quality"] },
    { label: "OEE", keys: ["oee"] },
  ],
};
const COLORS = ["#2a7de1", "#d9822b", "#2f9e6f", "#b0488f"];

/** PIADE has three shifts a day, so its label carries the shift start (UTC); brick has one a day. */
function shiftLabel(start: string | null, system: string): string {
  if (system !== "piade" || !start) return day(start);
  return `${day(start)} ${start.slice(11, 16)}`;
}

const TICKS = [0, 0.25, 0.5, 0.75, 1];

export default function Overview() {
  const [assets, setAssets] = useState<Result<AssetsData> | null>(null);
  const [lineId, setLineId] = useState("brick");
  const [group, setGroup] = useState<Group>("month");
  const [oee, setOee] = useState<Result<OeeData> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAssets().then(setAssets).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    // A response only counts if its request is still the current one; the error is cleared
    // when the selection changes.
    let current = true;
    setOee(null);
    setError(null);
    getOee({ line_id: lineId, group, limit: 2000 })
      .then((r) => current && setOee(r))
      .catch((e: Error) => current && setError(e.message));
    return () => {
      current = false;
    };
  }, [lineId, group]);

  const lines = assets?.data?.lines ?? [];
  const system = oee?.data?.source_system ?? lines.find((l) => l.line_id === lineId)?.source_system ?? "brick";
  const series = SERIES[system] ?? SERIES.piade;
  const rows = useMemo(
    () =>
      (oee?.data?.rows ?? []).map((r) => {
        const out: Record<string, string | number | null> = {
          name: group === "shift" ? shiftLabel(r.start, system) : r.key.slice(0, group === "month" ? 7 : 10),
          shiftId: group === "shift" ? r.key : null,
        };
        for (const s of series) out[s.label] = s.keys.map((k) => r.metrics[k]).find((v) => v !== undefined) ?? null;
        return out;
      }),
    [oee, group, series, system],
  );

  if (error) return <Loading error={error} />;
  const w = oee?.window;

  return (
    <>
      <h2>OEE overview <RealBadge /></h2>
      <div className="controls">
        <label>
          Line or machine
          <select value={lineId} onChange={(e) => setLineId(e.target.value)}>
            {lines.map((l) => (
              <option key={l.line_id} value={l.line_id}>
                {l.line_id === "brick" ? "brick (heavy clay brick line)" : `${l.line_id} (PIADE machine)`}
              </option>
            ))}
          </select>
        </label>
        <label>
          Group by
          <select value={group} onChange={(e) => setGroup(e.target.value as Group)}>
            <option value="shift">shift</option>
            <option value="day">day</option>
            <option value="month">month</option>
          </select>
        </label>
      </div>
      {!oee && <Loading error={null} />}
      {oee && <Notice result={oee} />}
      {oee?.status === "ok" && oee.data && (
        <>
          {w && (
            <p className="muted">
              Window: {day(w.start)} to {day(w.end)} (end exclusive). {oee.data.row_count} {group} rows
              {oee.data.rows_truncated ? ", truncated" : ""}.
            </p>
          )}
          <div className="chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows}>
                <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.2} />
                <XAxis dataKey="name" minTickGap={30} tick={{ fill: "currentColor", fontSize: 12 }} />
                <YAxis
                  domain={[0, (dataMax: number) => Math.max(1, dataMax)]}
                  ticks={TICKS}
                  tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
                  tick={{ fill: "currentColor", fontSize: 12 }}
                />
                <Tooltip
                  formatter={(v: number) => pct(v)}
                  contentStyle={{ background: "var(--panel)", border: "1px solid var(--line)" }}
                />
                <Legend />
                {series.map((s, i) => (
                  <Line key={s.label} type="monotone" dataKey={s.label} stroke={COLORS[i]}
                        dot={rows.length < 60} connectNulls={false} strokeWidth={2} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{group}</th>
                  {series.map((s) => <th key={s.label} className="num">{s.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td>
                      {r.shiftId ? (
                        <Link to={`/evidence/shift/${r.shiftId}`} title="All raw rows behind this shift">
                          {r.name}
                        </Link>
                      ) : (
                        r.name
                      )}
                    </td>
                    {series.map((s) => <td key={s.label} className="num">{pct(r[s.label] as number | null)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Assumptions items={oee.assumptions} />
        </>
      )}
    </>
  );
}
