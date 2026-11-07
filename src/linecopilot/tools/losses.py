"""Loss tools over mart.stop_episode: loss_pareto, breakdown and repeat_failures.

A stop belongs to a window by its start. Each result row cites the core.event rows of its
episodes (capped per row); top-level citations are the capped union of the returned rows'
citations, in row order, and citation_count counts the distinct raw rows behind them."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, Field

from linecopilot.tools.common import Scope, ScopeArgs, keyed_citations, resolve_scope, rows
from linecopilot.tools.envelope import CITATION_CAP, Citation, Result, cap_citations

ParetoBy = Literal["reason", "reason_detail", "alarm", "location", "product", "shift"]
Dim = Literal[
    "reason", "reason_detail", "alarm", "location", "product", "shift_slot", "weekday", "month"
]
RepeatKey = Literal["reason", "reason_detail", "alarm"]

PARETO_DIMS = {
    "brick": ("reason", "reason_detail", "location", "product", "shift"),
    "piade": ("reason", "alarm", "shift"),
}
BREAKDOWN_DIMS = {
    "brick": ("reason", "reason_detail", "location", "product", "weekday", "month"),
    "piade": ("reason", "alarm", "shift_slot", "weekday", "month"),
}
REPEAT_KEYS = {"brick": ("reason", "reason_detail"), "piade": ("reason", "alarm")}
SLOTS = {"06": "A 06-14", "14": "B 14-22", "22": "C 22-06"}
BLANK = "(blank)"
OTHER = "other"
CELL_CITES = 10

ASSUME_PIADE = (
    "PIADE stop: an episode of consecutive 'stopped' (downtime) intervals on one machine; a "
    "stopped interval starting at most 5 s after the previous stopped interval ends joins its "
    "episode, and lost time is the sum of the stopped intervals (the seconds between them, "
    "such as short running blips, are not counted). idle, scheduled downtime (off) and "
    "performance loss are not stops. Overlapping intervals are clipped as in the OEE marts."
)
ASSUME_PIADE_REASON = (
    "PIADE reason and alarm are both the alarm code of the episode's first interval "
    "(NO_ALARM if blank). Every PIADE stop counts as a failure: the data has no failure flag."
)
ASSUME_BRICK = (
    "Brick stop: one stop-log row, lost time is its end minus start. reason is the stop "
    "group, reason_detail the stop name. A failure is a stop with stop group FAILURE."
)
ASSUME_BRICK_OVERLAP = (
    "Brick stops can overlap; each counts in full here, so lost time can exceed the union "
    "of stop time used for availability."
)
ASSUME_WINDOW = (
    "A stop belongs to the window by its start; start is inclusive, end exclusive. Times "
    "for weekday and month are those of the shift the stop starts in (brick: Europe/Nicosia "
    "date; PIADE: assumed 3 x 8 h UTC shifts)."
)


def _not_in_oee_note(include: bool) -> str:
    if include:
        return "Brick stops typed 'Planned - Not included in OEE' are included."
    return (
        "Brick stops typed 'Planned - Not included in OEE' are excluded "
        "(set include_not_in_oee to include them)."
    )


# Arguments and results ------------------------------------------------------------------


class LossParetoArgs(ScopeArgs):
    by: ParetoBy = Field(description="category to rank lost time by")
    include_not_in_oee: bool = Field(
        default=False, description="brick: also count stops planned and not included in OEE"
    )
    top: int = Field(default=10, ge=1, le=50, description="categories returned; rest is other")


class BreakdownArgs(ScopeArgs):
    rows: Dim
    cols: Dim
    top: int = Field(default=8, ge=1, le=50, description="top rows and cols; rest is other")
    include_not_in_oee: bool = False


class RepeatArgs(ScopeArgs):
    within_hours: float = Field(
        default=24, ge=0.5, le=168, description="max gap from one stop's end to the next start"
    )
    min_repeats: int = Field(default=3, ge=2, le=100)
    key: RepeatKey = "reason"
    limit: int = Field(default=20, ge=1, le=200, description="chains returned, by lost time")


class ParetoRow(BaseModel):
    category: str
    lost_s: float
    stop_count: int
    share: float
    cumulative_share: float
    citations: list[Citation] = Field(default_factory=list)
    citation_count: int = Field(default=0, description="distinct raw rows behind this row")


class ParetoData(BaseModel):
    source_system: str
    by: str
    rows: list[ParetoRow]
    total_lost_s: float
    total_stop_count: int
    other_lost_s: float = 0
    other_stop_count: int = 0
    other_categories: int = 0


class Cell(BaseModel):
    row: str
    col: str
    lost_s: float
    stop_count: int


class BreakdownData(BaseModel):
    source_system: str
    rows: str
    cols: str
    row_keys: list[str]
    col_keys: list[str]
    cells: list[Cell]
    total_lost_s: float
    total_stop_count: int


class RepeatChain(BaseModel):
    machine_id: str | None
    line_id: str
    key: str
    count: int
    first_start: datetime
    last_end: datetime
    lost_s: float
    episode_ids: list[int]
    citations: list[Citation] = Field(default_factory=list)
    citation_count: int = 0


class RepeatData(BaseModel):
    source_system: str
    key: str
    within_hours: float
    min_repeats: int
    chains: list[RepeatChain]
    chain_count: int
    chains_truncated: bool = False
    failure_count: int


# Helpers ------------------------------------------------------------------------------------


def shift_slot(shift_id: str) -> str:
    """PIADE shift label from a shift_id ending in THH (06, 14 or 22 UTC)."""
    return SLOTS[shift_id.rsplit("T", 1)[1][:2]]


def _shift_date(shift_id: str) -> datetime:
    # brick:YYYY-MM-DD and piade:s_n:YYYY-MM-DDTHH both end in the shift's date (and hour).
    return datetime.strptime(shift_id.rsplit(":", 1)[1][:10], "%Y-%m-%d")


def value(ep: dict[str, Any], dim: str, source: str) -> str | None:
    """The category of an episode on a dimension; None when the source left it blank."""
    if dim == "alarm":
        return ep["reason"]
    if dim == "shift":
        return shift_slot(ep["shift_id"]) if source == "piade" else ep["shift_id"].split(":")[1]
    if dim == "shift_slot":
        return shift_slot(ep["shift_id"])
    if dim == "weekday":
        return _shift_date(ep["shift_id"]).strftime("%a")
    if dim == "month":
        return _shift_date(ep["shift_id"]).strftime("%Y-%m")
    return ep[dim]


EPISODES = """SELECT episode_id, source_system, line_id, machine_id, start_ts, end_ts,
                     duration_s::float8 AS duration_s, shift_id, reason, reason_detail,
                     location, product, in_oee, is_failure
              FROM mart.stop_episode
              WHERE line_id = %(line)s AND start_ts >= %(s)s AND start_ts < %(e)s
                AND (in_oee OR %(all)s) AND (is_failure OR NOT %(fail)s)
              ORDER BY start_ts, episode_id"""


def _episodes(conn, scope: Scope, include_all: bool, failures: bool = False) -> list[dict]:
    p = {"line": scope.line_id, "s": scope.start, "e": scope.end, "all": include_all}
    return rows(conn, EPISODES, {**p, "fail": failures})


EPISODE_EVENTS = """SELECT g.key, g.ord, e.event_id, e.event_type, e.raw_table, e.source_file,
                           e.raw_row_ids
                    FROM unnest(%(keys)s::text[], %(eids)s::bigint[], %(ords)s::int[])
                         AS g(key, episode_id, ord)
                    JOIN mart.stop_episode s ON s.episode_id = g.episode_id
                    CROSS JOIN LATERAL unnest(s.event_ids) AS x(event_id)
                    JOIN core.event e ON e.event_id = x.event_id"""


def episode_citations(
    conn, groups: list[tuple[str, list[int]]]
) -> tuple[dict[str, tuple[list[Citation], int]], int]:
    """Per group of episodes: the core.event rows behind them, in the given episode order,
    capped per group, with distinct raw-row counts per group and over all groups."""
    keys = [k for k, ids in groups for _ in ids]
    eids = [i for _, ids in groups for i in ids]
    if not eids:
        return {}, 0
    ords = [n for _, ids in groups for n in range(len(ids))]
    p = {"keys": keys, "eids": eids, "ords": ords, "cap": CITATION_CAP}
    return keyed_citations(conn, EPISODE_EVENTS, p, "ord, event_id")


def _by_size(eps: list[dict]) -> list[int]:
    """Episode ids, longest first, so the capped citations show the biggest losses."""
    return [e["episode_id"] for e in sorted(eps, key=lambda e: (-e["duration_s"], e["start_ts"]))]


def _assumptions(scope: Scope, include_not_in_oee: bool | None) -> list[str]:
    if scope.source_system == "piade":
        out = [ASSUME_PIADE, ASSUME_PIADE_REASON]
    else:
        out = [ASSUME_BRICK, ASSUME_BRICK_OVERLAP]
        if include_not_in_oee is not None:
            out.append(_not_in_oee_note(include_not_in_oee))
    return [*out, ASSUME_WINDOW]


def _asset(scope: Scope) -> str:
    return scope.machine_id or scope.line_id


def _invalid(scope: Scope, arg: str, given: str, valid: tuple[str, ...]) -> Result:
    return Result(
        status="out_of_scope",
        window=scope.window(),
        missing=(
            f"{arg}={given!r} is not available for {scope.source_system} {_asset(scope)}; "
            f"valid: {', '.join(valid)}"
        ),
    )


def _no_stops(scope: Scope, what: str, assumptions: list[str]) -> Result:
    return Result(
        status="insufficient_evidence",
        window=scope.window(),
        assumptions=assumptions,
        missing=(
            f"no {what} for {_asset(scope)} between {scope.start.isoformat()} and "
            f"{scope.end.isoformat()}; coverage is {scope.first_ts.isoformat()} to "
            f"{scope.last_ts.isoformat()}"
        ),
    )


def _top_union(per_row: list[list[Citation]]) -> list[Citation]:
    return cap_citations([c for cites in per_row for c in cites])[0]


def _lost(eps: list[dict]) -> float:
    return sum(e["duration_s"] for e in eps)


def _ranked(groups: dict[str, list[dict]]) -> list[tuple[str, list[dict]]]:
    return sorted(groups.items(), key=lambda kv: (-_lost(kv[1]), -len(kv[1]), kv[0]))


# Tools --------------------------------------------------------------------------------------


def loss_pareto(conn: psycopg.Connection, args: LossParetoArgs) -> Result[ParetoData]:
    scope = resolve_scope(conn, args.line_id, args.machine_id, args.start, args.end)
    if isinstance(scope, Result):
        return scope
    src = scope.source_system
    if args.by not in PARETO_DIMS[src]:
        return _invalid(scope, "by", args.by, PARETO_DIMS[src])
    assumptions = _assumptions(scope, args.include_not_in_oee)
    eps = _episodes(conn, scope, args.include_not_in_oee)
    total = _lost(eps)
    if not eps or total <= 0:
        return _no_stops(scope, "stops with lost time", assumptions)
    groups: dict[str, list[dict]] = defaultdict(list)
    for e in eps:
        groups[value(e, args.by, src) or BLANK].append(e)
    ranked = _ranked(groups)
    top, rest = ranked[: args.top], ranked[args.top :]
    cites, n_raw = episode_citations(conn, [(k, _by_size(es)) for k, es in top])
    out, cum = [], 0.0
    for k, es in top:
        share = _lost(es) / total
        cum += share
        c, n = cites.get(k, ([], 0))
        out.append(
            ParetoRow(
                category=k,
                lost_s=_lost(es),
                stop_count=len(es),
                share=share,
                cumulative_share=min(cum, 1.0),
                citations=c,
                citation_count=n,
            )
        )
    if src == "piade" and args.by == "shift":
        assumptions.append("shift is the UTC shift slot the stop starts in (A, B or C).")
    assumptions.append(
        "Each row cites the stop events of its category, longest stops first (capped per "
        "row); citation_count covers the returned rows, not other."
    )
    data = ParetoData(
        source_system=src,
        by=args.by,
        rows=out,
        total_lost_s=total,
        total_stop_count=len(eps),
        other_lost_s=sum(_lost(es) for _, es in rest),
        other_stop_count=sum(len(es) for _, es in rest),
        other_categories=len(rest),
    )
    return Result(
        status="ok",
        data=data,
        citations=_top_union([r.citations for r in out]),
        citation_count=n_raw,
        window=scope.window(),
        assumptions=assumptions,
    )


def breakdown(conn: psycopg.Connection, args: BreakdownArgs) -> Result[BreakdownData]:
    scope = resolve_scope(conn, args.line_id, args.machine_id, args.start, args.end)
    if isinstance(scope, Result):
        return scope
    src = scope.source_system
    for arg, dim in (("rows", args.rows), ("cols", args.cols)):
        if dim not in BREAKDOWN_DIMS[src]:
            return _invalid(scope, arg, dim, BREAKDOWN_DIMS[src])
    if args.rows == args.cols:
        return Result(
            status="out_of_scope", window=scope.window(), missing="rows and cols must differ"
        )
    assumptions = _assumptions(scope, args.include_not_in_oee)
    eps = _episodes(conn, scope, args.include_not_in_oee)
    if not eps:
        return _no_stops(scope, "stops", assumptions)

    def keep(dim: str) -> set[str]:
        groups: dict[str, list[dict]] = defaultdict(list)
        for e in eps:
            groups[value(e, dim, src) or BLANK].append(e)
        return {k for k, _ in _ranked(groups)[: args.top]}

    top_r, top_c = keep(args.rows), keep(args.cols)
    cells: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in eps:
        r = value(e, args.rows, src) or BLANK
        c = value(e, args.cols, src) or BLANK
        cells[(r if r in top_r else OTHER, c if c in top_c else OTHER)].append(e)
    ranked = sorted(cells.items(), key=lambda kv: (-_lost(kv[1]), -len(kv[1]), kv[0]))

    def order(idx: int) -> list[str]:
        tot: dict[str, float] = defaultdict(float)
        for k, es in cells.items():
            tot[k[idx]] += _lost(es)
        named = sorted((k for k in tot if k != OTHER), key=lambda k: (-tot[k], k))
        return named + ([OTHER] if OTHER in tot else [])

    cite_cells = ranked[:CELL_CITES]
    cites, n_raw = episode_citations(
        conn, [(f"{r}\x1f{c}", _by_size(es)) for (r, c), es in cite_cells]
    )
    assumptions.append(
        f"Rows and cols beyond the top {args.top} by lost time are folded into 'other'. "
        f"Citations are the stop events of the {CELL_CITES} cells with the most lost time."
    )
    data = BreakdownData(
        source_system=src,
        rows=args.rows,
        cols=args.cols,
        row_keys=order(0),
        col_keys=order(1),
        cells=[Cell(row=r, col=c, lost_s=_lost(es), stop_count=len(es)) for (r, c), es in ranked],
        total_lost_s=_lost(eps),
        total_stop_count=len(eps),
    )
    return Result(
        status="ok",
        data=data,
        citations=_top_union([cites.get(f"{r}\x1f{c}", ([], 0))[0] for (r, c), _ in cite_cells]),
        citation_count=n_raw,
        window=scope.window(),
        assumptions=assumptions,
    )


def chain_repeats(
    eps: list[dict[str, Any]], within_hours: float, min_repeats: int
) -> list[list[dict[str, Any]]]:
    """Chains of episodes with the same `key` on the same machine (or line), each starting
    at most `within_hours` after the previous one's end. Episodes without a key are skipped.
    Returns chains of at least `min_repeats`, most lost time first."""
    gap = timedelta(hours=within_hours)
    by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in eps:
        if e["key"] is not None:
            by[(e["machine_id"] or e["line_id"], e["key"])].append(e)
    chains: list[list[dict]] = []
    for group in by.values():
        group.sort(key=lambda e: (e["start_ts"], e["episode_id"]))
        cur = [group[0]]
        for e in group[1:]:
            if e["start_ts"] - cur[-1]["end_ts"] <= gap:
                cur.append(e)
            else:
                chains.append(cur)
                cur = [e]
        chains.append(cur)
    keep = [c for c in chains if len(c) >= min_repeats]
    return sorted(keep, key=lambda c: (-_lost(c), c[0]["start_ts"], c[0]["episode_id"]))


def repeat_failures(conn: psycopg.Connection, args: RepeatArgs) -> Result[RepeatData]:
    scope = resolve_scope(conn, args.line_id, args.machine_id, args.start, args.end)
    if isinstance(scope, Result):
        return scope
    src = scope.source_system
    if args.key not in REPEAT_KEYS[src]:
        return _invalid(scope, "key", args.key, REPEAT_KEYS[src])
    assumptions = _assumptions(scope, None)
    eps = _episodes(conn, scope, include_all=True, failures=True)
    if not eps:
        return _no_stops(scope, "failure stops", assumptions)
    for e in eps:
        e["key"] = value(e, args.key, src)
    chains = chain_repeats(eps, args.within_hours, args.min_repeats)
    shown = chains[: args.limit]
    cites, n_raw = episode_citations(
        conn, [(str(i), [e["episode_id"] for e in c]) for i, c in enumerate(shown)]
    )
    out = [
        RepeatChain(
            machine_id=c[0]["machine_id"],
            line_id=c[0]["line_id"],
            key=c[0]["key"],
            count=len(c),
            first_start=c[0]["start_ts"],
            last_end=max(e["end_ts"] for e in c),
            lost_s=_lost(c),
            episode_ids=[e["episode_id"] for e in c],
            citations=cites.get(str(i), ([], 0))[0],
            citation_count=cites.get(str(i), ([], 0))[1],
        )
        for i, c in enumerate(shown)
    ]
    assumptions.append(
        f"A chain is {args.min_repeats} or more failure stops with the same {args.key} on the "
        f"same machine, each starting within {args.within_hours:g} h of the previous one's "
        "end; chains are ranked by lost time. Stops with a blank key are not chained."
    )
    if len(chains) > len(shown):
        assumptions.append(f"Showing {len(shown)} of {len(chains)} chains; raise limit for more.")
    data = RepeatData(
        source_system=src,
        key=args.key,
        within_hours=args.within_hours,
        min_repeats=args.min_repeats,
        chains=out,
        chain_count=len(chains),
        chains_truncated=len(chains) > len(shown),
        failure_count=len(eps),
    )
    return Result(
        status="ok",
        data=data,
        citations=_top_union([c.citations for c in out]),
        citation_count=n_raw,
        window=scope.window(),
        assumptions=assumptions,
    )
