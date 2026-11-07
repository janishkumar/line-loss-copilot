import type { CheckResult, Outcome } from "../api";

/** The checks of a preview or proposal. Level drives the styling: warn yellow, block red. */
export function CheckList({ checks }: { checks: CheckResult[] }) {
  if (!checks.length) return <p className="muted">No checks recorded.</p>;
  return (
    <ul className="checks">
      {checks.map((c, i) => (
        <li key={`${c.name}-${i}`} className={c.level}>
          <span className="level">{c.level}</span> <strong>{c.name}</strong>
          <span className="msg"> {c.message}</span>
        </li>
      ))}
    </ul>
  );
}

/** An action's outcome from the server: a refusal or block reads as an alert with its checks. */
export function OutcomeNotice({ outcome }: { outcome: Outcome }) {
  const bad = ["refused", "blocked", "error"].includes(outcome.outcome);
  return (
    <div className={bad ? "notice" : "notice ok"} role={bad ? "alert" : "status"}>
      <strong>{outcome.outcome}.</strong> {outcome.message}
      {outcome.checks.some((c) => c.level !== "pass") && (
        <CheckList checks={outcome.checks.filter((c) => c.level !== "pass")} />
      )}
    </div>
  );
}
