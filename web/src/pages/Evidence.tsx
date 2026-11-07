import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getSource, type Result, type SourceData } from "../api";
import { Loading, Notice, RealBadge } from "../components/Common";

const cell = (v: unknown) => (v === null || v === undefined ? "" : String(v));

export default function Evidence() {
  const { eventId = "" } = useParams();
  const [res, setRes] = useState<Result<SourceData> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRes(null);
    setError(null);
    getSource(eventId).then(setRes).catch((e: Error) => setError(e.message));
  }, [eventId]);

  if (error || !res) return <Loading error={error} />;
  const d = res.data;
  const cols = d ? Object.keys(d.rows[0] ?? {}) : [];
  return (
    <>
      <h2>Evidence: event {eventId} <RealBadge /></h2>
      <Notice result={res} />
      {d && (
        <>
          <p className="muted">
            Table <code>{d.raw_table}</code>, file <code>{d.source_file}</code>, event key{" "}
            <code>{d.event_key}</code>. Raw rows exactly as loaded; source_row is the 1-based line in the
            file. Text is shown verbatim, in its original language.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
              </thead>
              <tbody>
                {d.rows.map((r, i) => (
                  <tr key={i}>
                    {cols.map((c) => <td key={c} className="text" lang={c === "note" ? "el" : undefined}>{cell(r[c])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
