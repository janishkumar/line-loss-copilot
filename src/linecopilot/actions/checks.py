"""Checks run before an action is proposed or approved.

The checks are pure functions over a `Snapshot` of the facts they need; `load_snapshot` reads
those facts from Postgres. Free text is only ever inspected here: instruction-like wording
produces a warning for the human and never changes the arguments or any function's behaviour."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import psycopg

from linecopilot.actions.identity import ActionContext, get_user
from linecopilot.actions.policy import Policy

Level = Literal["pass", "warn", "block"]


@dataclass(frozen=True)
class CheckResult:
    name: str
    level: Level
    message: str
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "level": self.level,
            "message": self.message,
            "detail": self.detail,
        }


def blocked(results: Sequence[CheckResult]) -> bool:
    return any(r.level == "block" for r in results)


@dataclass(frozen=True)
class EvidenceRow:
    event_key: str
    event_id: int
    line_id: str | None
    machine_id: str | None
    start_ts: datetime | None
    duration_s: Any
    event_type: str | None
    reason_code: str | None
    alarm_code: str | None


@dataclass(frozen=True)
class NoteText:
    event_id: int
    source: str  # "core.note" or "demo.injected_note"
    text: str
    translation: str | None = None
    translation_model: str | None = None


@dataclass(frozen=True)
class Duplicate:
    kind: str  # work_order, quality_hold, proposal, released_hold
    ref: int
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ref": self.ref, "detail": self.detail}


@dataclass(frozen=True)
class Snapshot:
    action: str
    canon: dict
    asset_exists: bool
    evidence: tuple[EvidenceRow, ...]
    notes: tuple[NoteText, ...]
    duplicates: tuple[Duplicate, ...]
    proposer_role: str | None
    released_holds: tuple[Duplicate, ...] = ()

    @property
    def asset_id(self) -> str | None:
        return self.canon.get("asset_id")


FREE_TEXT_FIELDS = {
    "work_order": ("failure_mode", "description"),
    "quality_hold": ("product", "reason"),
    "follow_up": ("description",),
}


# --- individual checks -------------------------------------------------------------------------


def check_asset_exists(s: Snapshot) -> CheckResult:
    if s.asset_id is None:
        return CheckResult("asset_exists", "pass", "no asset named")
    if s.asset_exists:
        return CheckResult("asset_exists", "pass", f"{s.asset_id} is a known line or machine")
    return CheckResult("asset_exists", "block", f"{s.asset_id} is not a known line or machine id")


def _belongs(row: EvidenceRow, asset: str | None) -> bool:
    return asset is None or asset in (row.machine_id, row.line_id)


def check_evidence_exists(s: Snapshot) -> CheckResult:
    wanted = s.canon.get("evidence_event_ids", [])
    if not wanted:
        return CheckResult("evidence_exists", "pass", "no evidence linked")
    found = {r.event_id: r for r in s.evidence}
    missing = [i for i in wanted if i not in found]
    wrong = [i for i in wanted if i in found and not _belongs(found[i], s.asset_id)]
    if missing or wrong:
        parts = []
        if missing:
            parts.append(f"event id(s) not found: {missing}")
        if wrong:
            parts.append(f"event id(s) not on {s.asset_id}: {wrong}")
        return CheckResult(
            "evidence_exists",
            "block",
            "; ".join(parts),
            {"missing": missing, "wrong_asset": wrong},
        )
    return CheckResult("evidence_exists", "pass", f"{len(wanted)} evidence event(s) found")


def check_duplicate_open(s: Snapshot) -> CheckResult:
    if not s.duplicates:
        return CheckResult("duplicate_open", "pass", "no open duplicate")
    return CheckResult(
        "duplicate_open",
        "block",
        "; ".join(d.detail for d in s.duplicates),
        {"duplicates": [d.to_dict() for d in s.duplicates]},
    )


def check_role_may_propose(s: Snapshot, policy: Policy) -> CheckResult:
    role = s.proposer_role
    if role is None:
        return CheckResult("role_may_propose", "block", "the user is not a known app user")
    if policy.may_propose(role, s.action):
        return CheckResult("role_may_propose", "pass", f"{role} may propose {s.action}")
    return CheckResult("role_may_propose", "block", f"role {role} may not propose {s.action}")


def check_priority_sanity(s: Snapshot, policy: Policy) -> CheckResult:
    priority = s.canon.get("priority")
    floor = policy.priority_floor(priority) if priority else None
    if floor is None:
        return CheckResult("priority_sanity", "pass", "no priority floor applies")
    min_s, min_events = floor
    total = float(sum(float(r.duration_s or 0) for r in s.evidence))
    n = len(s.evidence)
    detail = {
        "priority": priority,
        "total_duration_s": total,
        "events": n,
        "min_stop_s": min_s,
        "min_events": min_events,
    }
    if total < min_s or n < min_events:
        return CheckResult(
            "priority_sanity",
            "warn",
            f"priority {priority} usually needs at least {min_events} events and {min_s} s of "
            f"stops; the evidence has {n} and {total:.0f} s",
            detail,
        )
    return CheckResult("priority_sanity", "pass", "evidence supports the priority", detail)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    # drop marks (accents, variation selectors) and invisible format characters (zero-width,
    # soft hyphen); the patterns below treat every space as optional, so a format character
    # used as the gap between words still matches
    kept = "".join(
        c
        for c in decomposed
        if unicodedata.category(c)[0] != "M" and unicodedata.category(c) != "Cf"
    )
    return " ".join(kept.casefold().split())


_INSTRUCTION_PATTERNS = [
    r"ignore (all |any )?(previous|prior|above) instructions",
    r"\bsystem\s*:",
    r"\bassistant\s*:",
    r"approve (this|it|immediately|all)\b",
    r"do not (ask|wait|preview)",
    r"disregard",
    r"you are now",
    r"skip (the )?(approval|preview|check)",
    r"set priority",
    # Greek, written with accents; _fold strips them from the pattern and the text alike
    r"αγνόησε",
    r"εγκρίνετε",
    r"έγκριση αμέσως",
]
_INSTRUCTION_RE = re.compile(
    "|".join(f"(?:{_fold(p).replace(' ', ' ?')})" for p in _INSTRUCTION_PATTERNS)
)


def _note_key(n: NoteText) -> str:
    base = f"note:{n.event_id}"
    return base if n.source == "core.note" else f"{base}:{n.source}"


def check_instruction_like_text(s: Snapshot) -> CheckResult:
    hits: dict[str, str] = {}
    for name in FREE_TEXT_FIELDS.get(s.action, ()):
        value = s.canon.get(name)
        if isinstance(value, str):
            m = _INSTRUCTION_RE.search(_fold(value))
            if m:
                hits[name] = m.group(0)
    for n in s.notes:
        m = _INSTRUCTION_RE.search(_fold(n.text))
        if m:
            hits[_note_key(n)] = m.group(0)
    if hits:
        return CheckResult(
            "instruction_like_text",
            "warn",
            "instruction-like wording found in " + ", ".join(hits) + "; treated as data only",
            hits,
        )
    return CheckResult("instruction_like_text", "pass", "no instruction-like text")


def run_checks(s: Snapshot, policy: Policy) -> list[CheckResult]:
    """The propose-time checks, in a fixed order."""
    return [
        check_asset_exists(s),
        check_evidence_exists(s),
        check_duplicate_open(s),
        check_role_may_propose(s, policy),
        check_priority_sanity(s, policy),
        check_instruction_like_text(s),
    ]


def still_relevant(s: Snapshot, linked_keys: Sequence[str]) -> CheckResult:
    """Approve-time re-check on fresh data. `s` must be loaded with the proposal's linked event
    keys (and `exclude_proposal_id` / `since` set) so evidence is resolved by key."""
    present = {r.event_key for r in s.evidence}
    missing = [k for k in linked_keys if k not in present]
    problems: list[str] = []
    detail: dict[str, Any] = {}
    if missing:
        problems.append(f"evidence no longer present: {missing}")
        detail["missing_keys"] = missing
    if s.asset_id is not None and not s.asset_exists:
        problems.append(f"{s.asset_id} no longer exists")
    if s.duplicates:
        problems.append("; ".join(d.detail for d in s.duplicates))
        detail["duplicates"] = [d.to_dict() for d in s.duplicates]
    if s.released_holds:
        problems.append("; ".join(d.detail for d in s.released_holds))
        detail["released_holds"] = [d.to_dict() for d in s.released_holds]
    if problems:
        return CheckResult("still_relevant", "block", "; ".join(problems), detail)
    return CheckResult("still_relevant", "pass", "still relevant on fresh data")


# --- reading the facts -------------------------------------------------------------------------

_EVENT_COLS = (
    "event_key, event_id, line_id, machine_id, start_ts, duration_s, event_type, "
    "reason_code, alarm_code"
)


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and a_end > b_start


def _parse_ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _duplicates(
    conn: psycopg.Connection, action: str, canon: dict, exclude_proposal_id: int | None
) -> list[Duplicate]:
    asset = canon.get("asset_id")
    if asset is None:
        return []
    out: list[Duplicate] = []
    pending = conn.execute(
        "SELECT proposal_id, args FROM actions.proposal "
        "WHERE status = 'pending' AND action = %s AND args->>'asset_id' = %s "
        "AND (%s::bigint IS NULL OR proposal_id <> %s) ORDER BY proposal_id",
        (action, asset, exclude_proposal_id, exclude_proposal_id),
    ).fetchall()
    if action == "work_order":
        mode = canon["failure_mode"]
        for wid, fm in conn.execute(
            "SELECT work_order_id, failure_mode FROM actions.work_order "
            "WHERE status = 'open' AND asset_id = %s ORDER BY work_order_id",
            (asset,),
        ).fetchall():
            if fm.casefold() != mode.casefold():
                continue
            out.append(
                Duplicate("work_order", wid, f"open work order #{wid} on {asset} for '{fm}'")
            )
        for pid, args in pending:
            if str(args.get("failure_mode", "")).casefold() == mode.casefold():
                out.append(
                    Duplicate(
                        "proposal",
                        pid,
                        f"pending work order proposal #{pid} on {asset} for '{mode}'",
                    )
                )
    elif action == "quality_hold":
        start = datetime.fromisoformat(canon["window_start"])
        end = datetime.fromisoformat(canon["window_end"])
        for hid, ws, we in conn.execute(
            "SELECT hold_id, window_start, window_end FROM actions.quality_hold "
            "WHERE status = 'active' AND asset_id = %s AND window_start < %s AND window_end > %s "
            "ORDER BY hold_id",
            (asset, end, start),
        ).fetchall():
            out.append(
                Duplicate(
                    "quality_hold",
                    hid,
                    f"active quality hold #{hid} on {asset} overlaps the window "
                    f"({ws.isoformat()} to {we.isoformat()})",
                )
            )
        for pid, args in pending:
            ps, pe = _parse_ts(args.get("window_start")), _parse_ts(args.get("window_end"))
            if ps and pe and ps.tzinfo and pe.tzinfo and _overlaps(start, end, ps, pe):
                out.append(
                    Duplicate(
                        "proposal",
                        pid,
                        f"pending quality hold proposal #{pid} on {asset} overlaps the window",
                    )
                )
    return out


def _released_holds(
    conn: psycopg.Connection, canon: dict, since: datetime | None
) -> list[Duplicate]:
    if since is None or "window_start" not in canon:
        return []
    start = datetime.fromisoformat(canon["window_start"])
    end = datetime.fromisoformat(canon["window_end"])
    rows = conn.execute(
        "SELECT hold_id FROM actions.quality_hold WHERE status = 'released' AND asset_id = %s "
        "AND created_at >= %s AND window_start < %s AND window_end > %s ORDER BY hold_id",
        (canon["asset_id"], since, end, start),
    ).fetchall()
    return [
        Duplicate(
            "released_hold",
            hid,
            f"quality hold #{hid} on {canon['asset_id']} covering the window was released "
            "after the proposal",
        )
        for (hid,) in rows
    ]


def load_snapshot(
    conn: psycopg.Connection,
    action: str,
    canon: dict,
    ctx: ActionContext,
    *,
    evidence_keys: Sequence[str] | None = None,
    exclude_proposal_id: int | None = None,
    since: datetime | None = None,
) -> Snapshot:
    """Read what the checks need. By default evidence is resolved by the canonical event ids;
    with `evidence_keys` (approve-time re-check) it is resolved by event key instead.
    `exclude_proposal_id` leaves the proposal being re-checked out of the duplicates and `since`
    (the proposal's creation time) turns on the released-hold look."""
    if evidence_keys is not None:
        rows = conn.execute(
            f"SELECT {_EVENT_COLS} FROM core.event WHERE event_key = ANY(%s) ORDER BY event_id",
            (list(evidence_keys),),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_EVENT_COLS} FROM core.event WHERE event_id = ANY(%s) ORDER BY event_id",
            (list(canon.get("evidence_event_ids", [])),),
        ).fetchall()
    evidence = tuple(EvidenceRow(*r) for r in rows)

    asset = canon.get("asset_id")
    asset_exists = True
    if asset is not None:
        asset_exists = (
            conn.execute(
                "SELECT 1 FROM core.line WHERE line_id = %s "
                "UNION ALL SELECT 1 FROM core.machine WHERE machine_id = %s LIMIT 1",
                (asset, asset),
            ).fetchone()
            is not None
        )

    notes: list[NoteText] = []
    if evidence:
        ids = [r.event_id for r in evidence]
        for eid, text, tr, model in conn.execute(
            "SELECT n.event_id, n.original_text, t.translated_text, t.model_name "
            "FROM core.note n LEFT JOIN LATERAL (SELECT translated_text, model_name "
            "FROM core.note_translation WHERE note_id = n.note_id "
            "ORDER BY 1 LIMIT 1) t ON true "
            "WHERE n.event_id = ANY(%s) ORDER BY n.event_id, n.note_id",
            (ids,),
        ).fetchall():
            notes.append(NoteText(eid, "core.note", text, tr, model))
        by_key = {r.event_key: r.event_id for r in evidence}
        for key, text in conn.execute(
            "SELECT event_key, text FROM demo.injected_note WHERE event_key = ANY(%s) ORDER BY id",
            (list(by_key),),
        ).fetchall():
            notes.append(NoteText(by_key[key], "demo.injected_note", text))

    user = get_user(conn, ctx.on_behalf_of)
    return Snapshot(
        action=action,
        canon=canon,
        asset_exists=asset_exists,
        evidence=evidence,
        notes=tuple(notes),
        duplicates=tuple(_duplicates(conn, action, canon, exclude_proposal_id)),
        proposer_role=user.role if user else None,
        released_holds=tuple(_released_holds(conn, canon, since)),
    )
