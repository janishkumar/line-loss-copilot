import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getShiftEvidence, type EvidenceRow, type Result, type ShiftEvidenceData } from "../api";
import { Assumptions, Loading, Notice, RealBadge } from "../components/Common";

const cell = (v: unknown) => (v === null || v === undefined ? "" : String(v));

interface Group {
  table: string;
  file: string;
  rows: EvidenceRow[];
}

function groupRows(rows: EvidenceRow[]): Group[] {
  const groups = new Map<string, Group>();
  for (const r of rows) {
    const k = `${r.raw_table}\u0000${r.source_file}`;
    const g = groups.get(k) ?? { table: r.raw_table, file: r.source_file, rows: [] };
    g.rows.push(r);
    groups.set(k, g);
  }
  return [...groups.values()];
}

export default function ShiftEvidence() {
  const { shiftId = "" } = useParams();
  const [res, setRes] = useState<Result<ShiftEvidenceData> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    setRes(null);
    setError(null);
    getShiftEvidence(shiftId)
      .then((r) => current && setRes(r))
      .catch((e: Error) => current && setError(e.message));
    return () => {
      current = false;
    };
  }, [shiftId]);

  const groups = useMemo(() => groupRows(res?.data?.rows ?? []), [res]);

  if (error || !res) return <Loading error={error} />;
  const d = res.data;
  return (
    <>
      <h2>Evidence: shift {shiftId} <RealBadge /></h2>
      <Notice result={res} />
      {d && (
        <>
          <p className="muted">
            {d.event_count} events behind this shift's numbers
            {d.truncated ? ` (showing the first ${d.rows.length} rows)` : ""}. Raw rows exactly as
            loaded; source_row is the 1-based line in the file. Text is shown verbatim, in its
            original language.
          </p>
          {groups.map((g) => {
            const cols = Object.keys(g.rows[0].raw);
            return (
              <section key={`${g.table}:${g.file}`} aria-label={`${g.table} ${g.file}`}>
                <h3>
                  <code>{g.table}</code> from <code>{g.file}</code> ({g.rows.length} rows)
                </h3>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>event</th>
                        {cols.map((c) => <th key={c}>{c}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {g.rows.map((r) => (
                        <tr key={`${r.event_id}:${r.source_row}`}>
                          <td><Link to={`/evidence/${r.event_id}`}>{r.event_id}</Link></td>
                          {cols.map((c) => (
                            <td key={c} className="text" lang={c === "note" ? "el" : undefined}>
                              {cell(r.raw[c])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            );
          })}
          <Assumptions items={res.assumptions} />
        </>
      )}
    </>
  );
}
