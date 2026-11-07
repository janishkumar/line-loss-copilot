import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { searchNotes } from "../api";
import AssetPicker, { scopeOf, type Selection } from "../components/AssetPicker";
import { Assumptions, Loading, Notice, RealBadge } from "../components/Common";
import { day } from "../format";
import { useResult } from "../hooks";

export default function Notes() {
  const [sel, setSel] = useState<Selection>({ lineId: "", start: "", end: "" });
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const { result, error } = useResult(
    query ? () => searchNotes({ ...scopeOf(sel), query }) : null,
    [sel, query],
  );
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setQuery(draft.trim());
  };
  return (
    <>
      <h2>Operator notes <RealBadge /></h2>
      <p className="muted">
        Notes are free text and shown exactly as written. Translations are machine-generated and
        may be wrong; the original is the record.
      </p>
      <form className="controls" onSubmit={submit}>
        <label>
          Search
          <input type="search" value={draft} onChange={(e) => setDraft(e.target.value)} />
        </label>
        <button type="submit">Search</button>
      </form>
      <AssetPicker value={sel} onChange={setSel} allLabel="All lines" />
      {error && <Loading error={error} />}
      {query && !result && !error && <Loading error={null} />}
      {result && <Notice result={result} />}
      {result?.status === "ok" && result.data && (
        <>
          <p className="muted">
            {result.data.total} matching notes{result.data.truncated ? `, showing the first ${result.data.hits.length}` : ""}.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>When</th><th>Machine</th><th>Reason</th><th>Original</th><th>Translation</th><th>Source</th></tr>
              </thead>
              <tbody>
                {result.data.hits.map((h) => (
                  <tr key={h.note_id}>
                    <td>{day(h.start_ts)}</td>
                    <td>{h.machine_id ?? ""}</td>
                    <td>{h.reason ?? ""}</td>
                    <td className="text">{h.original_text} <span className="muted">({h.language})</span></td>
                    <td className="text">
                      {h.translation ? (
                        <>
                          {h.translation.text}{" "}
                          <span className="badge">machine-translated · {h.translation.model_name}</span>
                        </>
                      ) : (
                        <span className="muted">No translation</span>
                      )}
                    </td>
                    <td><Link to={`/evidence/${h.event_id}`}>1 row</Link></td>
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
