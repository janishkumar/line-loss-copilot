import { Link } from "react-router-dom";
import type { Citation } from "../api";

export default function Cite({ citation, label }: { citation: Citation; label?: string }) {
  const text = label ?? `${citation.source_file}:${citation.raw_row_id}`;
  if (citation.event_id === null) return <span>{text}</span>;
  return (
    <Link to={`/evidence/${citation.event_id}`} title={`${citation.raw_table} row ${citation.raw_row_id}`}>
      {text}
    </Link>
  );
}
