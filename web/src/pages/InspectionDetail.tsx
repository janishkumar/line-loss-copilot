import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getInspection, HOLD_ROLES, REVIEW_ROLES, reviewInspection, type Inspection } from "../api";
import { Assumptions, Loading, Notice, SimulatedBadge } from "../components/Common";
import { imageName } from "../format";
import { useResult } from "../hooks";
import { useSession } from "../UserSwitcher";

export function holdLink(i: Inspection): string | null {
  if (i.decision === "pass" || i.quality_event_id === null) return null;
  return `/actions/new?${new URLSearchParams({ action: "quality_hold", asset: i.asset_id, events: String(i.quality_event_id) })}`;
}

export default function InspectionDetail() {
  const { id = "" } = useParams();
  const { user } = useSession();
  const [version, setVersion] = useState(0);
  const { result, error } = useResult(() => getInspection(id), [id, version]);
  const [overlay, setOverlay] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const i = result?.data;
  const canReview = !!user && REVIEW_ROLES.includes(user.role);

  async function decide(decision: "accept" | "reject") {
    setBusy(true);
    setMsg(null);
    const r = await reviewInspection(Number(id), decision);
    setBusy(false);
    if (r.ok) {
      setMsg({ ok: true, text: `Recorded: ${decision}${r.quality_event_id !== null ? `, simulated quality event ${r.quality_event_id} created` : ""}.` });
      setVersion((v) => v + 1);
    } else setMsg({ ok: false, text: r.message ?? "Not recorded." });
  }

  const link = i ? holdLink(i) : null;
  return (
    <>
      <p><Link to="/inspection">Back to the queue</Link></p>
      <h2>Inspection #{id} <SimulatedBadge /></h2>
      {!result && <Loading error={error} />}
      {result && <Notice result={result} />}
      {i && (
        <>
          <p className="muted">
            VisA {i.subset} image {imageName(i.image_id)} at simulated station {i.asset_id}. The image is real; the station
            and any quality event are synthetic.
          </p>
          {i.image_url || i.heatmap_url ? (
            <figure>
              {i.heatmap_url && (overlay || !i.image_url) ? (
                <img src={i.heatmap_url} alt={`Defect heatmap for ${i.subset} ${imageName(i.image_id)}`} style={{ maxWidth: "100%", width: 448 }} />
              ) : i.image_url ? (
                <img src={i.image_url} alt={`Product image ${i.subset} ${imageName(i.image_id)}`} style={{ maxWidth: "100%", width: 448 }} />
              ) : null}
              {i.heatmap_url && i.image_url && (
                <label>
                  <input type="checkbox" checked={overlay} onChange={(e) => setOverlay(e.target.checked)} /> Show heatmap overlay
                </label>
              )}
              <figcaption className="muted">Warmer areas are further from anything seen in normal images. A guide for a reviewer, not a verdict.</figcaption>
            </figure>
          ) : (
            <p className="muted">No image or heatmap file is available for this inspection.</p>
          )}
          <dl>
            <dt>Score</dt><dd>{i.score.toFixed(3)} against reject threshold {i.threshold.toFixed(3)}
              {i.review_lower !== null && <> (review band starts at {i.review_lower.toFixed(3)})</>}</dd>
            <dt>Model decision</dt><dd>{i.decision}</dd>
            <dt>Reviewer</dt>
            <dd>{i.review ? `${i.review.decision} by ${i.review.reviewer}` : "not reviewed"}</dd>
            <dt>Quality event</dt>
            <dd>{i.quality_event_id !== null ? `${i.quality_event_id} (simulated)` : "none"}</dd>
          </dl>
          {link && !!user && HOLD_ROLES.includes(user.role) && <p><Link to={link}>Draft quality hold</Link> <span className="muted">(a person approves it in the inbox)</span></p>}
          {i.decision === "review" && !i.review && (
            <section aria-label="Review">
              <h3>Review</h3>
              {!user && <p className="notice">Pick a demo user first (top right).</p>}
              {user && !canReview && (
                <p className="muted">
                  Your role ({user.role}) cannot review images. Quality lead, shift supervisor and plant manager can.
                </p>
              )}
              {canReview && (
                <>
                  <button type="button" disabled={busy} onClick={() => decide("accept")}>Accept (good product)</button>{" "}
                  <button type="button" disabled={busy} onClick={() => decide("reject")}>Reject (defect)</button>
                </>
              )}
            </section>
          )}
          {msg && <div className={msg.ok ? "notice ok" : "notice"} role={msg.ok ? "status" : "alert"}>{msg.text}</div>}
        </>
      )}
      {result && <Assumptions items={result.assumptions} />}
    </>
  );
}
