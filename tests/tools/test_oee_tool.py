"""get_oee against the fixture database: row-scoped citations and envelope edge cases."""

from datetime import UTC, datetime

import pytest

from linecopilot.tools.envelope import CITATION_CAP, cap_citations
from linecopilot.tools.oee import GetOeeArgs, get_oee

pytestmark = pytest.mark.db


def key(c):
    return (c.raw_table, c.source_file, c.raw_row_id)


def test_get_oee_top_level_citations_match_rows(built):
    r = get_oee(built, GetOeeArgs(line_id="brick", start="2026-02-02", end="2026-02-05"))
    assert r.status == "ok" and len(r.data.rows) == 2
    union = [c for row in r.data.rows for c in row.citations]
    capped, _ = cap_citations(union)
    assert [key(c) for c in r.citations] == [key(c) for c in capped]
    assert len(r.citations) <= CITATION_CAP
    row_events = {c.event_id for row in r.data.rows for c in row.citations}
    assert all(c.event_id in row_events for c in r.citations)
    assert r.citation_count == sum(row.citation_count for row in r.data.rows)
    # nothing outside the returned rows: the 2026-01-30 shift's events are not cited
    shifts = {
        s
        for (s,) in built.execute(
            "SELECT shift_id FROM core.event WHERE event_id = ANY(%s)",
            ([c.event_id for c in r.citations],),
        ).fetchall()
    }
    assert shifts <= {"brick:2026-02-02", "brick:2026-02-03"}


@pytest.mark.parametrize(
    ("args", "trunc"),
    [
        ({"machine_id": "s_3", "group": "day"}, "day"),
        ({"machine_id": "s_3", "group": "month"}, "month"),
        ({"machine_id": "s_1", "group": "day"}, "day"),
        ({"line_id": "brick", "group": "month"}, "month"),
    ],
)
def test_coarse_rows_cite_their_own_shifts(built, args, trunc):
    r = get_oee(built, GetOeeArgs(**args))
    assert r.status == "ok" and r.data.rows
    brick = args.get("line_id") == "brick"
    tz = "Europe/Nicosia" if brick else "UTC"
    extra = (
        " AND (event_type = 'production_count' OR stop_type <> 'Planned - Not included in OEE')"
        if brick
        else ""
    )
    for row in r.data.rows:
        assert row.citations, row.key
        # every cited event belongs to a shift whose start falls in this row's period
        periods = built.execute(
            f"SELECT DISTINCT to_char(date_trunc('{trunc}', s.shift_start AT TIME ZONE %s), "
            f"'{'YYYY-MM' if brick else 'YYYY-MM-DD'}') "
            "FROM core.event e JOIN core.shift s USING (shift_id) WHERE e.event_id = ANY(%s)",
            (tz, [c.event_id for c in row.citations]),
        ).fetchall()
        assert [p for (p,) in periods] == [row.key], row.key
        # the count is the number of evidence events of the row's shifts
        mart = "mart.brick_shift_oee" if brick else "mart.piade_shift_oee"
        mfilter = "" if brick else f" AND m.machine_id = '{args['machine_id']}'"
        if trunc == "day" or brick:  # PIADE months are whole months, the rest the window
            mfilter += (
                f" AND s.shift_start >= '{r.window.start.isoformat()}'"
                f" AND s.shift_start < '{r.window.end.isoformat()}'"
            )
        (n,) = built.execute(
            f"SELECT count(*) FROM core.event e JOIN core.shift s USING (shift_id) "
            f"JOIN {mart} m USING (shift_id) WHERE to_char(date_trunc('{trunc}', "
            f"s.shift_start AT TIME ZONE %s), '{'YYYY-MM' if brick else 'YYYY-MM-DD'}') = %s"
            f"{mfilter}{extra}",
            (tz, row.key),
        ).fetchone()
        assert row.citation_count == n
    union = [c for row in r.data.rows for c in row.citations]
    assert [key(c) for c in r.citations] == [key(c) for c in cap_citations(union)[0]]
    assert r.citation_count == sum(row.citation_count for row in r.data.rows)


def test_get_oee_truncated_rows_cite_only_returned_rows(built):
    r = get_oee(built, GetOeeArgs(line_id="brick", limit=2))
    assert r.data.rows_truncated and len(r.data.rows) == 2
    returned = {row.key for row in r.data.rows}
    (n,) = built.execute(
        "SELECT count(*) FROM core.event WHERE event_id = ANY(%s) AND NOT shift_id = ANY(%s)",
        ([c.event_id for c in r.citations], list(returned)),
    ).fetchone()
    assert n == 0


def test_get_oee_end_before_start_live_conn(built):
    r = get_oee(built, GetOeeArgs(line_id="brick", start="2025-10-10", end="2025-10-09"))
    assert r.status == "out_of_scope" and r.missing == "end must be after start"
    # a start past coverage with the end defaulted is caught after defaulting
    r = get_oee(built, GetOeeArgs(line_id="brick", start="2030-01-01"))
    assert r.status == "out_of_scope" and r.missing == "end must be after start"


def test_get_oee_empty_window_insufficient(built):
    # Fixture analogue of the live check (s_2 2020-01..02, coverage from 2020-06-15):
    # s_3's fixture coverage starts 2020-01-02, the window ends before its first shift.
    r = get_oee(
        built,
        GetOeeArgs(
            machine_id="s_3",
            start=datetime(2019, 12, 1, tzinfo=UTC),
            end=datetime(2020, 1, 1, 12, tzinfo=UTC),
        ),
    )
    assert r.status == "insufficient_evidence" and r.data is None
    assert "2020-01-02" in r.missing and "coverage is" in r.missing
    assert r.window.machine_id == "s_3" and r.window.group == "shift"


def test_default_window_keeps_first_shift(built):
    # s_1's first event (12:00) falls inside the 06:00 shift; a default window must start at
    # that shift's start, not at the first event, or the shift is dropped.
    (first_shift,) = built.execute(
        "SELECT s.shift_id FROM core.shift s JOIN core.line l USING (line_id)"
        " WHERE l.line_id = 's_1' AND s.shift_start <= l.first_ts AND l.first_ts < s.shift_end"
    ).fetchone()
    r = get_oee(built, GetOeeArgs(machine_id="s_1"))
    assert first_shift in {row.key for row in r.data.rows}
    (lo,) = built.execute(
        "SELECT min(shift_start) FROM core.shift WHERE line_id = 's_1'"
    ).fetchone()
    assert r.window.start == lo
    day = get_oee(built, GetOeeArgs(machine_id="s_1", group="day"))
    month = get_oee(built, GetOeeArgs(machine_id="s_1", group="month"))
    assert day.citation_count == month.citation_count == r.citation_count


@pytest.mark.parametrize(
    "args",
    [
        {"line_id": "brick"},
        {"line_id": "brick", "group": "month"},
        {"machine_id": "s_1", "group": "day"},
        {"machine_id": "s_3", "group": "month"},
    ],
)
def test_citation_count_is_distinct_raw_rows(built, args):
    r = get_oee(built, GetOeeArgs(**args))
    brick = args.get("line_id") == "brick"
    extra = (
        " AND (e.event_type = 'production_count' OR e.stop_type <> 'Planned - Not included in OEE')"
        if brick
        else ""
    )
    events = built.execute(
        "SELECT event_id FROM core.event e WHERE e.event_id = ANY(%s)",
        ([c.event_id for row in r.data.rows for c in row.citations],),
    ).fetchall()
    assert events
    # every row's shifts, recovered from its cited events, give the distinct raw-row total
    (n,) = built.execute(
        "SELECT count(DISTINCT (e.raw_table, e.source_file, rid)) FROM core.event e,"
        " unnest(e.raw_row_ids) rid WHERE e.shift_id IN (SELECT shift_id FROM core.event"
        f" WHERE event_id = ANY(%s)){extra}",
        ([c.event_id for row in r.data.rows for c in row.citations],),
    ).fetchone()
    assert r.citation_count == n
    assert r.citation_count == sum(row.citation_count for row in r.data.rows)
    assert r.citation_count >= len(r.citations)


def test_piade_day_group_honours_limit(built):
    full = get_oee(built, GetOeeArgs(machine_id="s_3", group="day"))
    assert full.status == "ok" and len(full.data.rows) == 2
    assert full.data.row_count == 2 and not full.data.rows_truncated
    one = get_oee(built, GetOeeArgs(machine_id="s_3", group="day", limit=1))
    assert [r.key for r in one.data.rows] == [full.data.rows[0].key]
    assert one.data.row_count == 2 and one.data.rows_truncated
    assert any("Showing the first 1 of 2 rows" in a for a in one.assumptions)
    # top-level citations follow the returned rows only
    first = {(c.raw_table, c.raw_row_id) for c in full.data.rows[0].citations}
    assert {(c.raw_table, c.raw_row_id) for c in one.citations} <= first
