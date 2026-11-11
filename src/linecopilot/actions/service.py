"""The action service: preview, propose, approve, reject, close, release, complete.

Connections. Every public method takes an open psycopg connection in AUTOCOMMIT mode (a plain
`autocommit=True` connection, as the rest of the project uses) and opens its own transactions on
it with `conn.transaction()`; a non-autocommit connection is refused up front, because a
caller-held transaction could roll back a burned code or an audit row. `preview` and `propose`
run on the restricted agent role; `approve`, `reject`, `close_work_order`, `release_hold` and
`complete_follow_up` need the main role (the agent role cannot lock or update proposals).

Rule: the agent proposes, a person approves. Free text is stored as written and only ever
inspected by the checks, which warn."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from linecopilot.actions import args as argmod
from linecopilot.actions import audit, codes
from linecopilot.actions.checks import (
    CheckResult,
    Snapshot,
    asset_labels,
    blocked,
    check_instruction_like_text,
    event_relation,
    load_snapshot,
    run_checks,
    still_relevant,
)
from linecopilot.actions.identity import AGENT, ActionContext, AppUser, get_user
from linecopilot.actions.policy import Policy

OutcomeName = Literal[
    "proposed", "approved", "rejected", "closed", "released", "refused", "blocked", "error"
]

# Who may change the status of an approved action. Not in policy.toml (the policy file covers
# proposing and approving); kept here as the one place these rules live.
CLOSE_ROLES = ("shift_supervisor", "plant_manager")
RELEASE_ROLES = ("quality_lead", "plant_manager")
FOLLOW_UP_ADMIN = "plant_manager"

KINDS = {"work_order": "work_order", "quality_hold": "quality_hold", "follow_up": "follow_up"}
_TABLES = {
    "work_order": ("actions.work_order", "work_order_id"),
    "quality_hold": ("actions.quality_hold", "hold_id"),
    "follow_up": ("actions.follow_up", "follow_up_id"),
}


@dataclass
class Preview:
    action: str
    args: dict
    summary: str
    checks: list[CheckResult]
    code: str | None
    evidence: list[dict]
    blocked: bool
    notes: list[dict] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)  # ["synthetic", ...] for a simulated asset


@dataclass
class Outcome:
    outcome: OutcomeName
    message: str
    checks: list[CheckResult] = field(default_factory=list)
    proposal_id: int | None = None
    target_id: int | None = None
    audit_id: int | None = None


def _require_autocommit(conn: psycopg.Connection) -> None:
    if not conn.autocommit:
        raise ValueError("ActionService needs an autocommit connection")


def _valid_identity(conn: psycopg.Connection, ctx: ActionContext) -> CheckResult:
    user = get_user(conn, ctx.on_behalf_of)
    if user is None:
        return CheckResult("valid_identity", "block", f"unknown user {ctx.on_behalf_of!r}")
    if user.role == "agent" or ctx.on_behalf_of == AGENT:
        return CheckResult("valid_identity", "block", "the agent cannot act on its own behalf")
    if ctx.principal != AGENT and ctx.principal != ctx.on_behalf_of:
        return CheckResult(
            "valid_identity", "block", "principal must be the agent or the user themselves"
        )
    if (ctx.principal == AGENT) != (ctx.channel in ("mcp", "web_chat")):
        return CheckResult(
            "valid_identity", "block", f"channel {ctx.channel} does not fit principal"
        )
    return CheckResult("valid_identity", "pass", f"acting for {user.display_name}")


def _summary(conn: psycopg.Connection, ctx: ActionContext, canon: dict, snap: Snapshot) -> str:
    user = get_user(conn, ctx.on_behalf_of)
    who = user.display_name if user else ctx.on_behalf_of
    n = len(snap.evidence)
    hours = float(sum(float(r.duration_s or 0) for r in snap.evidence)) / 3600
    linked = f"{n} linked stop{'' if n == 1 else 's'} ({hours:.1f} h)"
    if snap.action == "work_order":
        head = (
            f"Work order on {canon['asset_id']} for '{canon['failure_mode']}', "
            f"priority {canon['priority']}, {linked}"
        )
    elif snap.action == "quality_hold":
        product = f" of '{canon['product']}'" if canon.get("product") else ""
        head = (
            f"Quality hold on {canon['asset_id']}{product} from {canon['window_start']} to "
            f"{canon['window_end']}, {linked}"
        )
    else:
        head = (
            f"Follow-up for {canon['assignee_role']} due {canon['due_date']}, "
            f"{n} linked event{'' if n == 1 else 's'}"
            + (f", {len(canon['order_ids'])} linked order(s)" if canon.get("order_ids") else "")
        )
    tag = " [SYNTHETIC: simulated inspection station]" if snap.asset_simulated else ""
    return f"{head}{tag}. Proposed by {ctx.principal} for {who} via {ctx.channel}."


NOTE_CAP = 600
NOTES_MAX = 10


def _cap(text: str | None) -> str | None:
    if text is None or len(text) <= NOTE_CAP:
        return text
    return text[:NOTE_CAP] + "..."


def _note_dicts(snap: Snapshot) -> list[dict]:
    """The notes linked to the evidence, then those of the linked orders, as quoted data: the
    same text a person sees in the inbox. Demo notes and order notes are flagged synthetic; a
    translation carries its model's name."""
    out = [
        {
            "event_id": n.event_id,
            "order_id": None,
            "source": n.source,
            "synthetic": n.source == "demo.injected_note",
            "text": _cap(n.text),
            "translation": _cap(n.translation),
            "translation_model": n.translation_model if n.translation else None,
            "truncated": len(n.text) > NOTE_CAP,
        }
        for n in snap.notes[:NOTES_MAX]
    ]
    out += [
        {
            "event_id": None,
            "order_id": o.order_id,
            "source": "synthetic.customer_order",
            "synthetic": True,
            "text": _cap(o.note),
            "translation": None,
            "translation_model": None,
            "truncated": len(o.note) > NOTE_CAP,
        }
        for o in snap.orders[:NOTES_MAX]
        if o.note
    ]
    return out


def _evidence_dicts(snap: Snapshot) -> list[dict]:
    return [
        {
            "event_id": r.event_id,
            "event_key": r.event_key,
            "line_id": r.line_id,
            "machine_id": r.machine_id,
            "start_ts": r.start_ts.isoformat() if r.start_ts else None,
            "duration_s": float(r.duration_s) if r.duration_s is not None else None,
            "event_type": r.event_type,
            "reason_code": r.reason_code,
            "alarm_code": r.alarm_code,
        }
        for r in snap.evidence
    ]


@contextmanager
def _error_audit(conn: psycopg.Connection, **fields: Any) -> Iterator[None]:
    """Wrap a transaction: an unexpected exception (the transaction inside has already rolled
    back) is recorded as an `error` audit row in a fresh statement, then re-raised unchanged so
    the caller sees the failure (including InsufficientPrivilege on the wrong role)."""
    try:
        yield
    except Exception as e:
        try:
            audit.write(conn, outcome="error", detail=f"{type(e).__name__}: {e}"[:500], **fields)
        except Exception:  # noqa: S110 - never mask the original failure
            pass
        raise


def _lock_asset(conn: psycopg.Connection, action: str, canon: dict) -> None:
    """Serialise propose/approve on the same action type and asset, so two concurrent
    duplicates cannot both pass the duplicate check. Held until the transaction ends."""
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{action}:{canon.get('asset_id', '')}",)
    )


class ActionService:
    def __init__(
        self, policy: Policy, now: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self.policy = policy
        self.now = now

    # --- preview and propose (agent role is enough) ----------------------------------------

    def _checks(
        self, conn: psycopg.Connection, ctx: ActionContext, action: str, canon: dict
    ) -> tuple[Snapshot, list[CheckResult]]:
        snap = load_snapshot(conn, action, canon, ctx)
        return snap, [_valid_identity(conn, ctx), *run_checks(snap, self.policy)]

    def _redeem(
        self,
        conn: psycopg.Connection,
        code: str | None,
        action: str,
        ctx: ActionContext,
        digest: str,
    ) -> str | None:
        """Burn and check a confirmation code: None if good, else the refusal text."""
        return codes.redeem(conn, code, action, ctx, digest, self.now())

    def preview(
        self, conn: psycopg.Connection, ctx: ActionContext, action: str, raw_args: dict
    ) -> Preview:
        _require_autocommit(conn)
        try:
            canon = argmod.canonical(action, argmod.parse(action, raw_args))
        except argmod.InvalidArgs as e:
            check = CheckResult("valid_arguments", "block", str(e))
            audit.write(
                conn,
                event="previewed",
                outcome="refused",
                principal=ctx.principal,
                on_behalf_of=ctx.on_behalf_of,
                channel=ctx.channel,
                action=action if action in argmod.ACTION_ARGS else None,
                checks=[check],
                detail=str(e),
            )
            return Preview(action, {}, f"Arguments refused: {e}", [check], None, [], True)

        digest = argmod.payload_sha256(action, ctx, canon)
        now = self.now()
        with conn.transaction():
            snap, results = self._checks(conn, ctx, action, canon)
            is_blocked = blocked(results)
            code = None
            if not is_blocked:
                code = codes.issue(
                    conn, action, ctx, digest, now, timedelta(minutes=self.policy.ttl_minutes)
                )
            summary = _summary(conn, ctx, canon, snap)
            audit.write(
                conn,
                event="previewed",
                outcome="blocked" if is_blocked else "ok",
                principal=ctx.principal,
                on_behalf_of=ctx.on_behalf_of,
                channel=ctx.channel,
                action=action,
                payload_sha256=digest,
                checks=results,
            )
        return Preview(
            action,
            canon,
            summary,
            results,
            code,
            _evidence_dicts(snap),
            is_blocked,
            _note_dicts(snap),
            asset_labels(snap.asset_simulated),
        )

    def propose(
        self,
        conn: psycopg.Connection,
        ctx: ActionContext,
        action: str,
        raw_args: dict,
        code: str | None,
    ) -> Outcome:
        _require_autocommit(conn)

        def refuse(message: str, digest: str | None = None, name: OutcomeName = "refused"):
            aid = audit.write(
                conn,
                event="proposed",
                outcome=name,
                principal=ctx.principal,
                on_behalf_of=ctx.on_behalf_of,
                channel=ctx.channel,
                action=action if action in argmod.ACTION_ARGS else None,
                payload_sha256=digest,
                detail=message,
            )
            return Outcome(name, message, audit_id=aid)

        try:
            canon = argmod.canonical(action, argmod.parse(action, raw_args))
        except argmod.InvalidArgs as e:
            return refuse(f"arguments refused: {e}")
        digest = argmod.payload_sha256(action, ctx, canon)

        # The burn is its own autocommit statement: nothing later can roll it back, and the
        # refusal audit row below is likewise its own statement.
        refusal = self._redeem(conn, code, action, ctx, digest)
        if refusal is not None:
            return refuse(refusal, digest)

        with (
            _error_audit(
                conn,
                event="proposed",
                principal=ctx.principal,
                on_behalf_of=ctx.on_behalf_of,
                channel=ctx.channel,
                action=action,
                payload_sha256=digest,
            ),
            conn.transaction(),
        ):
            _lock_asset(conn, action, canon)
            snap, results = self._checks(conn, ctx, action, canon)
            if blocked(results):
                msg = "; ".join(r.message for r in results if r.level == "block")
                aid = audit.write(
                    conn,
                    event="proposed",
                    outcome="blocked",
                    principal=ctx.principal,
                    on_behalf_of=ctx.on_behalf_of,
                    channel=ctx.channel,
                    action=action,
                    payload_sha256=digest,
                    checks=results,
                    detail=msg,
                )
                return Outcome("blocked", msg, results, audit_id=aid)
            summary = _summary(conn, ctx, canon, snap)
            pid = conn.execute(
                "INSERT INTO actions.proposal (action, args, payload_sha256, summary, checks, "
                "principal, on_behalf_of, channel, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING proposal_id",
                (
                    action,
                    json.dumps(canon),
                    digest,
                    summary,
                    json.dumps([r.to_dict() for r in results]),
                    ctx.principal,
                    ctx.on_behalf_of,
                    ctx.channel,
                    self.now(),
                ),
            ).fetchone()[0]
            for e in snap.evidence:
                conn.execute(
                    "INSERT INTO actions.proposal_evidence (proposal_id, event_key, "
                    "event_id_at_link) VALUES (%s, %s, %s)",
                    (pid, e.event_key, e.event_id),
                )
            aid = audit.write(
                conn,
                event="proposed",
                outcome="ok",
                principal=ctx.principal,
                on_behalf_of=ctx.on_behalf_of,
                channel=ctx.channel,
                action=action,
                proposal_id=pid,
                payload_sha256=digest,
                checks=results,
            )
        return Outcome("proposed", summary, results, proposal_id=pid, audit_id=aid)

    # --- decisions (human session, main role) -----------------------------------------------

    def _human(
        self, conn: psycopg.Connection, user_id: str, event: str, **ref: Any
    ) -> tuple[AppUser | None, Outcome | None]:
        """The acting user, or a refusal (already audited) if it is unknown or the agent."""
        user = get_user(conn, user_id) if user_id else None
        if user is not None and user.role != "agent" and user_id != AGENT:
            return user, None
        why = "the agent cannot make decisions" if user_id == AGENT or user else "unknown user"
        aid = audit.write(
            conn,
            event=event,
            outcome="refused",
            principal=user_id or "anonymous",
            detail=why,
            **ref,
        )
        return None, Outcome("refused", why, audit_id=aid)

    def _decision_checks(self, user: AppUser, prop: dict) -> list[CheckResult]:
        sod_hit = user.user_id in (prop["principal"], prop["on_behalf_of"])
        return [
            CheckResult(
                "segregation_of_duties",
                "block" if sod_hit else "pass",
                "approver is the proposer or the human the agent acted for"
                if sod_hit
                else "approver is independent of the proposal",
            ),
            (
                CheckResult("role_may_approve", "pass", f"{user.role} may approve {prop['action']}")
                if self.policy.may_approve(user.role, prop["action"])
                else CheckResult(
                    "role_may_approve",
                    "block",
                    f"role {user.role} may not approve {prop['action']}",
                )
            ),
        ]

    def _locked_pending(self, conn: psycopg.Connection, proposal_id: int) -> dict | None:
        cur = conn.cursor(row_factory=dict_row)
        return cur.execute(
            "SELECT * FROM actions.proposal WHERE proposal_id = %s FOR UPDATE", (proposal_id,)
        ).fetchone()

    def approve(
        self, conn: psycopg.Connection, user_id: str, proposal_id: int, note: str = ""
    ) -> Outcome:
        return self._decide(conn, user_id, proposal_id, note, approve=True)

    def reject(
        self, conn: psycopg.Connection, user_id: str, proposal_id: int, note: str = ""
    ) -> Outcome:
        return self._decide(conn, user_id, proposal_id, note, approve=False)

    def _decide(
        self, conn: psycopg.Connection, user_id: str, proposal_id: int, note: str, approve: bool
    ) -> Outcome:
        _require_autocommit(conn)
        event = "approved" if approve else "rejected"
        user, refusal = self._human(conn, user_id, event, proposal_id=proposal_id)
        if refusal:
            return refusal
        assert user is not None
        note = (note or "").strip()
        with (
            _error_audit(conn, event=event, principal=user_id, proposal_id=proposal_id),
            conn.transaction(),
        ):
            prop = self._locked_pending(conn, proposal_id)
            base = dict(
                event=event,
                principal=user_id,
                on_behalf_of=None,
                action=prop["action"] if prop else None,
                proposal_id=proposal_id,
                payload_sha256=prop["payload_sha256"] if prop else None,
            )
            if prop is None:
                aid = audit.write(conn, outcome="refused", detail="no such proposal", **base)
                return Outcome("refused", "no such proposal", audit_id=aid)
            if prop["status"] != "pending":
                msg = f"proposal is not pending (status {prop['status']})"
                aid = audit.write(conn, outcome="refused", detail=msg, **base)
                return Outcome("refused", msg, proposal_id=proposal_id, audit_id=aid)

            results = self._decision_checks(user, prop)
            canon = None
            if approve and not blocked(results):
                canon, results = self._recheck(conn, prop, results)
            if blocked(results):
                msg = "; ".join(r.message for r in results if r.level == "block")
                aid = audit.write(conn, outcome="blocked", checks=results, detail=msg, **base)
                return Outcome("blocked", msg, results, proposal_id, audit_id=aid)

            target_id = None
            now = self.now()
            if approve:
                assert canon is not None
                target_id = self._write_target(conn, prop, canon, user_id, now)
            conn.execute(
                "UPDATE actions.proposal SET status = %s, decided_by = %s, decided_at = %s, "
                "decision_note = %s, target_id = %s WHERE proposal_id = %s",
                (
                    "approved" if approve else "rejected",
                    user_id,
                    now,
                    note,
                    target_id,
                    proposal_id,
                ),
            )
            aid = audit.write(conn, outcome="ok", checks=results, detail=note, **base)
            msg = "approved and written" if approve else "rejected"
            return Outcome(event, msg, results, proposal_id, target_id, aid)  # type: ignore[arg-type]

    def _recheck(
        self, conn: psycopg.Connection, prop: dict, results: list[CheckResult]
    ) -> tuple[dict | None, list[CheckResult]]:
        """Re-run the propose checks and still_relevant on fresh data, excluding the proposal
        itself. Evidence is resolved by event key, so the event-id check is replaced by
        still_relevant (an id may legitimately change after a rebuild; the key may not vanish)."""
        ctx = ActionContext(prop["principal"], prop["on_behalf_of"], prop["channel"])
        try:
            canon = argmod.canonical(prop["action"], argmod.parse(prop["action"], prop["args"]))
        except argmod.InvalidArgs as e:
            return None, [*results, CheckResult("arguments_intact", "block", str(e))]
        if argmod.payload_sha256(prop["action"], ctx, canon) != prop["payload_sha256"]:
            return None, [
                *results,
                CheckResult(
                    "arguments_intact", "block", "stored arguments no longer match their hash"
                ),
            ]
        keys = [
            k
            for (k,) in conn.execute(
                "SELECT event_key FROM actions.proposal_evidence WHERE proposal_id = %s "
                "ORDER BY event_key",
                (prop["proposal_id"],),
            ).fetchall()
        ]
        _lock_asset(conn, prop["action"], canon)
        snap = load_snapshot(
            conn,
            prop["action"],
            canon,
            ctx,
            evidence_keys=keys,
            exclude_proposal_id=prop["proposal_id"],
            since=prop["created_at"],
        )
        fresh = [
            r
            for r in [_valid_identity(conn, ctx), *run_checks(snap, self.policy)]
            if r.name != "evidence_exists"
        ]
        fresh.append(still_relevant(snap, keys))
        return canon, [*results, *fresh]

    def _write_target(
        self, conn: psycopg.Connection, prop: dict, c: dict, user_id: str, now: datetime
    ) -> int:
        pid = prop["proposal_id"]
        if prop["action"] == "work_order":
            sql = (
                "INSERT INTO actions.work_order (proposal_id, asset_id, failure_mode, priority, "
                "description, created_by, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "RETURNING work_order_id"
            )
            params = (
                pid, c["asset_id"], c["failure_mode"], c["priority"], c["description"],
                user_id, now,
            )  # fmt: skip
        elif prop["action"] == "quality_hold":
            sql = (
                "INSERT INTO actions.quality_hold (proposal_id, asset_id, product, window_start, "
                "window_end, reason, created_by, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING hold_id"
            )
            params = (
                pid, c["asset_id"], c.get("product"), c["window_start"], c["window_end"],
                c["reason"], user_id, now,
            )  # fmt: skip
        else:
            sql = (
                "INSERT INTO actions.follow_up (proposal_id, assignee_role, due_date, "
                "description, created_by, created_at) VALUES (%s, %s, %s, %s, %s, %s) "
                "RETURNING follow_up_id"
            )
            params = (pid, c["assignee_role"], c["due_date"], c["description"], user_id, now)
        return conn.execute(sql, params).fetchone()[0]

    # --- closing what was approved ----------------------------------------------------------

    def _finish(
        self,
        conn: psycopg.Connection,
        user_id: str,
        kind: str,
        row_id: int,
        *,
        event: str,
        outcome_name: OutcomeName,
        open_status: str,
        allowed: Callable[[AppUser, dict], bool],
        update_sql: str,
        actor_cols: bool = True,
    ) -> Outcome:
        _require_autocommit(conn)
        table, key = _TABLES[kind]
        user, refusal = self._human(conn, user_id, event, action=kind)
        if refusal:
            return refusal
        assert user is not None
        with (
            _error_audit(conn, event=event, principal=user_id, action=kind),
            conn.transaction(),
        ):
            row = (
                conn.cursor(row_factory=dict_row)
                .execute(f"SELECT * FROM {table} WHERE {key} = %s FOR UPDATE", (row_id,))
                .fetchone()
            )
            base = dict(
                event=event,
                principal=user_id,
                action=kind,
                proposal_id=row["proposal_id"] if row else None,
            )
            if row is None:
                msg = f"no such {kind} #{row_id}"
            elif not allowed(user, row):
                msg = f"role {user.role} may not do this to a {kind}"
            elif row["status"] != open_status:
                msg = f"{kind} #{row_id} is already {row['status']}"
            else:
                params = (user_id, self.now(), row_id) if actor_cols else (row_id,)
                conn.execute(update_sql.format(table=table, key=key), params)
                aid = audit.write(conn, outcome="ok", detail=f"{kind} #{row_id}", **base)
                return Outcome(
                    outcome_name,
                    f"{kind} #{row_id} {outcome_name}",
                    target_id=row_id,
                    proposal_id=base["proposal_id"],
                    audit_id=aid,
                )
            aid = audit.write(conn, outcome="refused", detail=msg, **base)
            return Outcome("refused", msg, proposal_id=base["proposal_id"], audit_id=aid)

    def close_work_order(
        self, conn: psycopg.Connection, user_id: str, work_order_id: int
    ) -> Outcome:
        return self._finish(
            conn, user_id, "work_order", work_order_id,
            event="closed", outcome_name="closed", open_status="open",
            allowed=lambda u, r: u.role in CLOSE_ROLES,
            update_sql="UPDATE {table} SET status = 'closed', closed_by = %s, closed_at = %s "
            "WHERE {key} = %s",
        )  # fmt: skip

    def release_hold(self, conn: psycopg.Connection, user_id: str, hold_id: int) -> Outcome:
        return self._finish(
            conn, user_id, "quality_hold", hold_id,
            event="released", outcome_name="released", open_status="active",
            allowed=lambda u, r: u.role in RELEASE_ROLES,
            update_sql="UPDATE {table} SET status = 'released', released_by = %s, "
            "released_at = %s WHERE {key} = %s",
        )  # fmt: skip

    def complete_follow_up(
        self, conn: psycopg.Connection, user_id: str, follow_up_id: int
    ) -> Outcome:
        # follow_up has no completed_by column: the audit row records who completed it
        return self._finish(
            conn, user_id, "follow_up", follow_up_id,
            event="completed", outcome_name="closed", open_status="open",
            allowed=lambda u, r: u.role in (r["assignee_role"], FOLLOW_UP_ADMIN),
            update_sql="UPDATE {table} SET status = 'done' WHERE {key} = %s",
            actor_cols=False,
        )  # fmt: skip

    # --- read helpers for the API -----------------------------------------------------------

    def list_proposals(
        self, conn: psycopg.Connection, status: str | None = None, limit: int = 100
    ) -> list[dict]:
        return (
            conn.cursor(row_factory=dict_row)
            .execute(
                "SELECT proposal_id, action, summary, status, principal, on_behalf_of, channel, "
                "created_at, decided_by, decided_at, target_id FROM actions.proposal "
                "WHERE (%s::text IS NULL OR status = %s) ORDER BY proposal_id DESC LIMIT %s",
                (status, status, limit),
            )
            .fetchall()
        )

    def get_proposal(self, conn: psycopg.Connection, proposal_id: int) -> dict | None:
        cur = conn.cursor(row_factory=dict_row)
        prop = cur.execute(
            "SELECT * FROM actions.proposal WHERE proposal_id = %s", (proposal_id,)
        ).fetchone()
        if prop is None:
            return None
        evidence = cur.execute(
            "SELECT pe.event_key, pe.event_id_at_link, e.event_id AS current_event_id, "
            "(e.event_id IS NOT NULL) AS present, e.line_id, e.machine_id, e.start_ts, "
            "e.duration_s, e.event_type, e.reason_code, e.alarm_code "
            f"FROM actions.proposal_evidence pe LEFT JOIN {event_relation(conn)} e "
            "USING (event_key) WHERE pe.proposal_id = %s ORDER BY pe.event_key",
            (proposal_id,),
        ).fetchall()
        keys = [e["event_key"] for e in evidence]
        notes = cur.execute(
            "SELECT e.event_key, n.event_id, n.original_text AS text, 'core.note' AS source, "
            "t.translated_text AS translation, t.model_name AS translation_model "
            "FROM core.note n JOIN core.event e USING (event_id) "
            "LEFT JOIN LATERAL (SELECT translated_text, model_name FROM core.note_translation "
            "WHERE note_id = n.note_id ORDER BY 1 LIMIT 1) t ON true "
            "WHERE e.event_key = ANY(%s) "
            "UNION ALL SELECT event_key, NULL, text, 'demo.injected_note', NULL, NULL "
            "FROM demo.injected_note WHERE event_key = ANY(%s) ORDER BY event_key, source",
            (keys, keys),
        ).fetchall()
        ctx = ActionContext(prop["principal"], prop["on_behalf_of"], prop["channel"])
        warnings = [c for c in prop["checks"] if c["level"] == "warn"]
        snap = load_snapshot(conn, prop["action"], prop["args"], ctx, evidence_keys=keys)
        live = check_instruction_like_text(snap)
        if live.level == "warn" and not any(w["name"] == live.name for w in warnings):
            warnings.append(live.to_dict())
        order_notes = [
            {"order_id": o.order_id, "text": _cap(o.note), "synthetic": True}
            for o in snap.orders
            if o.note
        ]
        return {
            **prop,
            "evidence": evidence,
            "notes": notes,
            "order_notes": order_notes,
            "warnings": warnings,
            "labels": asset_labels(snap.asset_simulated),
        }

    def list_actions(self, conn: psycopg.Connection, kind: str) -> list[dict]:
        if kind not in _TABLES:
            raise ValueError(f"unknown action kind: {kind}")
        table, key = _TABLES[kind]
        return (
            conn.cursor(row_factory=dict_row)
            .execute(f"SELECT * FROM {table} ORDER BY {key} DESC")
            .fetchall()
        )

    def list_audit(
        self, conn: psycopg.Connection, limit: int = 200, proposal_id: int | None = None
    ) -> list[dict]:
        return (
            conn.cursor(row_factory=dict_row)
            .execute(
                "SELECT * FROM actions.audit_log WHERE (%s::bigint IS NULL OR proposal_id = %s) "
                "ORDER BY audit_id DESC LIMIT %s",
                (proposal_id, proposal_id, limit),
            )
            .fetchall()
        )
