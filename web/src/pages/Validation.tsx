import { useEffect, useState } from "react";
import {
  getOee, getValidation,
  type Citation, type GapStats, type OeeRow, type Result, type ValidationData,
} from "../api";
import Cite from "../components/Cite";
import { Assumptions, Loading, Notice, RealBadge } from "../components/Common";
import { day, gapPts, pct } from "../format";

type Period = "before" | "after";

/** The production_count event (brick_oee row) is the shift's evidence anchor; else the first citation. */
export function evidenceCitation(row: OeeRow | undefined): Citation | undefined {
  if (!row) return undefined;
  return row.citations.find((c) => c.raw_table === "brick_oee") ?? row.citations[0];
}

const pts = (v: number | null) => (v === null ? "n/a" : `${(v * 100).toFixed(1)} pts`);

function Stat({ label, s }: { label: string; s: GapStats }) {
  return (
    <div className="stat">
      <span className="muted">{label} gap, mean absolute (computed vs published)</span>
      <b>{pts(s.mean_abs)}</b>
      <span className="muted">
        median {pts(s.median_abs)}, max {pts(s.max_abs)}; within 2 pts: {pct(s.share_within_2pts)}; n = {s.n}
      </span>
    </div>
  );
}

export default function Validation() {
  const [res, setRes] = useState<Result<ValidationData> | null>(null);
  const [rowsByShift, setRowsByShift] = useState<Map<string, OeeRow>>(new Map());
  const [period, setPeriod] = useState<Period>("before");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getValidation(), getOee({ line_id: "brick", group: "shift", limit: 500 })])
      .then(([v, o]) => {
        setRes(v);
        setRowsByShift(new Map((o.data?.rows ?? []).map((r) => [r.key, r])));
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error || !res) return <Loading error={error} />;
  const data = res.data;
  const shifts = (data?.shifts ?? []).filter((s) => s.period === period);
  const summary = data?.periods[period];
  const win = data?.windows[period];

  return (
    <>
      <h2>Brick line validation <RealBadge /></h2>
      <p className="muted">
        Availability recomputed from the stop log, compared with the dataset's published values.
        Gap is computed minus published.
      </p>
      <Notice result={res} />
      <div className="controls" role="group" aria-label="Period">
        {(["before", "after"] as const).map((p) => (
          <button key={p} aria-pressed={period === p} onClick={() => setPeriod(p)}>
            {p === "before" ? "Before program" : "After program"}
          </button>
        ))}
      </div>
      {summary && win && (
        <>
          <p className="muted">
            Window: {win.first} to {win.last}. Published shifts: {summary.n_published}, matched:{" "}
            {summary.n_matched}, no stops: {summary.n_no_stops}, no published row:{" "}
            {summary.n_no_published}.
          </p>
          <div className="stats">
            <Stat label="Availability" s={summary.availability} />
            <Stat label="OEE" s={summary.oee} />
          </div>
        </>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Shift date</th>
              <th>Match</th>
              <th className="num">Availability (computed)</th>
              <th className="num">Availability (published)</th>
              <th className="num">Gap</th>
              <th className="num">OEE (computed)</th>
              <th className="num">OEE (published)</th>
              <th className="num">Gap</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {shifts.map((s) => {
              const row = rowsByShift.get(s.shift_id);
              const c = evidenceCitation(row);
              return (
                <tr key={s.shift_id}>
                  <td>{day(s.shift_date)}</td>
                  <td>{s.match_status}</td>
                  <td className="num">{pct(s.availability_calc)}</td>
                  <td className="num">{pct(s.availability_pub)}</td>
                  <td className="num">{gapPts(s.availability_gap)}</td>
                  <td className="num">{pct(s.oee_calc_with_pub_pq)}</td>
                  <td className="num">{pct(s.oee_pub)}</td>
                  <td className="num">{gapPts(s.oee_gap)}</td>
                  <td>
                    {c && row ? (
                      <Cite citation={c} label={`${row.citation_count} rows`} />
                    ) : (
                      <span className="muted">n/a</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted">
        "Published" columns are the values in the source dataset. "Computed" OEE combines the
        recomputed availability with the published performance and quality.
      </p>
      <Assumptions items={res.assumptions} />
    </>
  );
}
