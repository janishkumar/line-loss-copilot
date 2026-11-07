import { Link } from "react-router-dom";
import type { Citation } from "../api";

/** "N rows" link to the Evidence page. One event links straight to it; several expand to a
 * list of event links, capped at the citations the API returned. */
export default function Citations({ count, citations }: { count: number; citations: Citation[] }) {
  if (!count) return null;
  const label = `${count} ${count === 1 ? "row" : "rows"}`;
  const withEvent = citations.filter((c) => c.event_id !== null);
  const ids = new Set(withEvent.map((c) => c.event_id));
  if (ids.size === 0) return <span className="muted">{label}</span>;
  if (count === 1 && ids.size === 1)
    return (
      <Link to={`/evidence/${[...ids][0]}`} title="Source rows for this number">
        {label}
      </Link>
    );
  return (
    <details className="cites">
      <summary>{label}</summary>
      <ul>
        {withEvent.map((c, i) => (
          <li key={i}>
            <Link to={`/evidence/${c.event_id}`}>
              event {c.event_id}
            </Link>{" "}
            <span className="muted">{c.raw_table} row {c.raw_row_id}</span>
          </li>
        ))}
      </ul>
      <p className="muted">showing {withEvent.length} of {count}</p>
    </details>
  );
}
