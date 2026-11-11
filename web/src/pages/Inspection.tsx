import { useState } from "react";
import { Link } from "react-router-dom";
import { getInspections, type InspectionDecision } from "../api";
import { Assumptions, Loading, Notice, SimulatedBadge } from "../components/Common";
import { imageName } from "../format";
import { useResult } from "../hooks";

const FILTERS: { label: string; value: InspectionDecision | "all" | "unreviewed" }[] = [
  { label: "Needs review", value: "unreviewed" },
  { label: "Rejected", value: "reject" },
  { label: "Passed", value: "pass" },
  { label: "All", value: "all" },
];

export default function Inspection() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["value"]>("unreviewed");
  const { result, error } = useResult(
    () =>
      getInspections(
        filter === "unreviewed" ? { decision: "review", unreviewed: true } : filter === "all" ? {} : { decision: filter },
      ),
    [filter],
  );
  const data = result?.data;
  return (
    <>
      <h2>Inspection <SimulatedBadge /></h2>
      <p className="muted">
        Product images scored by an anomaly model. Above the threshold is rejected, just below it goes to a
        person, the rest passes. The images are real VisA photos, but the stream, the stations and the quality
        events are simulated, and this test half is about two thirds defective, far above a real plant.
      </p>
      <div role="group" aria-label="Filter by decision">
        {FILTERS.map((f) => (
          <button key={f.value} type="button" aria-pressed={filter === f.value}
            onClick={() => setFilter(f.value)}>{f.label}</button>
        ))}
      </div>
      {!result && <Loading error={error} />}
      {result && <Notice result={result} />}
      {data && (
        <>
          <p>
            Whole stream: {data.counts.pass ?? 0} passed, {data.counts.review ?? 0} to review, {data.counts.reject ?? 0} rejected.{" "}
            {data.pending_review} waiting for a reviewer. Showing {data.rows.length} of {data.total}.
          </p>
          {data.rows.length === 0 ? (
            <p className="muted">No inspections match this filter.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Image</th><th>Station</th><th>Score</th><th>Threshold</th><th>Decision</th><th>Reviewed</th></tr>
                </thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.inspection_id}>
                      <td><Link to={`/inspection/${r.inspection_id}`}>#{r.inspection_id} {r.subset} {imageName(r.image_id)}</Link></td>
                      <td>{r.asset_id}</td>
                      <td>{r.score.toFixed(3)}</td>
                      <td>{r.threshold.toFixed(3)}</td>
                      <td>{r.decision}</td>
                      <td>{r.review ? `${r.review.decision} by ${r.review.reviewer}` : ""}</td>
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
