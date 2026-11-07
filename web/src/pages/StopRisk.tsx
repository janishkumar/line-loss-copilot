import { useState } from "react";
import { getRisk, getRiskMetrics, type MetricRow } from "../api";
import AssetPicker, { type Selection } from "../components/AssetPicker";
import Citations from "../components/Citations";
import { Assumptions, Loading, Notice, RealBadge } from "../components/Common";
import { num, pct } from "../format";
import { useResult } from "../hooks";

const BASELINES = ["persistence", "hour_of_week"];
const COLS: [string, string][] = [
  ["pr_auc", "PR-AUC"],
  ["precision_top1", "Precision, top 1 per shift"],
  ["recall_top1", "Recall, top 1 per shift"],
  ["precision_top3", "Precision, top 3 per shift"],
  ["recall_top3", "Recall, top 3 per shift"],
];

/** Pooled test-split rows: [target][model][metric]. Per-machine rows are left out. */
function pool(rows: MetricRow[]) {
  const t: Record<string, Record<string, Record<string, number | null>>> = {};
  for (const r of rows) {
    if (r.split !== "test" || r.machine_id !== null) continue;
    ((t[r.target] ??= {})[r.model_name] ??= {})[r.metric] = r.value;
  }
  return t;
}

const ratio = (a: number, b: number) => (b > 0 ? `${(a / b).toFixed(1)}x` : "n/a");

/** Describes the long-stop result from the pooled test rows. "Weak" only when the best model's
 * PR-AUC is under 2x persistence or under 4x the base rate. */
export function signalSentence(t: ReturnType<typeof pool>): string | null {
  const long = t.long;
  if (!long) return null;
  const models = Object.keys(long).filter((m) => m !== "data" && !BASELINES.includes(m));
  const best = models.sort((x, y) => (long[y].pr_auc ?? 0) - (long[x].pr_auc ?? 0))[0];
  const base = long.data?.base_rate;
  const prauc = best ? long[best].pr_auc : null;
  const pers = long.persistence?.pr_auc;
  if (!best || prauc == null || base == null || pers == null) return null;
  const vsPers = prauc / pers;
  const vsBase = prauc / base;
  const weak = vsPers < 2 || vsBase < 4;
  const p3 = long[best].precision_top3;
  return (
    `${weak ? "The long-stop signal is weak" : "The long-stop signal shows lift"}: on the test split the best model ` +
    `(${best}) reaches PR-AUC ${num(prauc)}, ${ratio(prauc, pers)} persistence (${num(pers)}) and ` +
    `${ratio(prauc, base)} the base rate (${pct(base)})` +
    (p3 != null ? `; precision at top-3 volume is ${pct(p3)}` : "") +
    (weak ? ". Most alerts for a long stop would be false." : ".")
  );
}

export default function StopRisk() {
  const [sel, setSel] = useState<Selection>({ lineId: "", start: "", end: "" });
  const [target, setTarget] = useState("long");
  const [at, setAt] = useState("");
  const risk = useResult(
    () => getRisk({ machine_id: sel.lineId || undefined, at: at ? `${at}:00Z` : undefined, target }),
    [sel.lineId, at, target],
  );
  const metrics = useResult(() => getRiskMetrics(), []);
  const pooled = metrics.result?.data ? pool(metrics.result.data.rows) : {};
  const signal = signalSentence(pooled);
  const t0 = risk.result?.data?.rows[0]?.t;

  return (
    <>
      <h2>Stop risk <RealBadge /></h2>
      <p className="muted">
        Next-hour risk scores for the PIADE machines. A score is a ranking signal, not a probability
        of a stop.
      </p>
      <AssetPicker value={sel} onChange={(s) => setSel({ ...sel, lineId: s.lineId })}
                   system="piade" allLabel="All machines" showWindow={false}>
        <label>
          Target
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="long">long stop (600 s or more)</option>
            <option value="any">any stop</option>
          </select>
        </label>
        <label>
          At (UTC, blank for latest scored hour)
          <input type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} />
        </label>
      </AssetPicker>
      {risk.error && <Loading error={risk.error} />}
      {!risk.result && !risk.error && <Loading error={null} />}
      {risk.result && <Notice result={risk.result} />}
      {risk.result?.status === "ok" && risk.result.data && (
        <>
          <p className="muted">
            {risk.result.data.definition}. Scored hour: {t0 ? `${t0.slice(0, 13).replace("T", " ")}:00 UTC` : "n/a"}.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Machine</th><th className="num">Score</th><th className="num">Alert threshold (top-3 volume)</th>
                  <th className="num">Base rate</th><th>Alert</th><th>Top features</th><th>Source</th></tr>
              </thead>
              <tbody>
                {risk.result.data.rows.map((r) => (
                  <tr key={r.machine_id}>
                    <td>{r.machine_id}</td>
                    <td className="num">{num(r.score)}</td>
                    <td className="num">{num(r.alert_threshold)}</td>
                    <td className="num">{pct(r.base_rate)}</td>
                    <td>{r.alert === null ? "n/a" : r.alert ? "yes" : "no"}</td>
                    <td className="text">
                      {r.top_features.map((f) => `${f.feature} (${f.contribution >= 0 ? "+" : ""}${f.contribution.toFixed(2)})`).join(", ")}
                    </td>
                    <td><Citations count={r.citation_count} citations={r.citations} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Assumptions items={risk.result.assumptions} />
        </>
      )}

      <h3>Model metrics (test split, all machines)</h3>
      {metrics.error && <Loading error={metrics.error} />}
      {!metrics.result && !metrics.error && <Loading error={null} />}
      {metrics.result && <Notice result={metrics.result} />}
      {metrics.result?.status === "ok" && (
        <>
          {signal && <p className="notice">{signal}</p>}
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Target</th><th>Model</th>{COLS.map(([, l]) => <th key={l} className="num">{l}</th>)}</tr>
              </thead>
              <tbody>
                {Object.entries(pooled).flatMap(([tg, models]) =>
                  Object.entries(models)
                    .filter(([m]) => m !== "data")
                    .map(([m, vals]) => (
                      <tr key={`${tg}:${m}`}>
                        <td>{tg}</td>
                        <td>{m}{BASELINES.includes(m) ? " (baseline)" : ""}</td>
                        {COLS.map(([k]) => <td key={k} className="num">{k === "pr_auc" ? num(vals[k]) : pct(vals[k])}</td>)}
                      </tr>
                    )),
                )}
              </tbody>
            </table>
          </div>
          <p className="muted">
            Top 1 and top 3 mean the highest-scoring hours per machine per 8 h shift raise an alert; thresholds are chosen on the
            validation split. Base rate (test): {Object.entries(pooled).map(([tg, m]) => `${tg} ${pct(m.data?.base_rate)}`).join(", ")}.
          </p>
        </>
      )}
    </>
  );
}
