import type { ReactNode } from "react";
import type { Result } from "../api";

export const RealBadge = () => (
  <span className="badge" title="Every stage 1 number comes from the real public datasets">
    Real data
  </span>
);

export function Notice({ result }: { result: Result<unknown> }) {
  if (result.status === "ok") return null;
  const title =
    result.status === "insufficient_evidence" ? "Not enough evidence" : "Not available";
  return (
    <div className="notice" role="alert">
      <strong>{title}.</strong> {result.missing ?? "No data for this request."}
    </div>
  );
}

export function Assumptions({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <section aria-label="Assumptions">
      <h3>Assumptions</h3>
      <ul>
        {items.map((a) => (
          <li key={a}>{a}</li>
        ))}
      </ul>
    </section>
  );
}

export function Loading({ error, children }: { error: string | null; children?: ReactNode }) {
  if (error) return <div className="notice" role="alert">Could not load data: {error}</div>;
  return <p className="muted">{children ?? "Loading..."}</p>;
}

export const SyntheticBadge = () => (
  <span className="badge synthetic" title="Orders, BOMs, stock and receipts are generated; rates, availability and stops are real">
    Synthetic orders on real capacity
  </span>
);
