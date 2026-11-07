"""Loss tool logic that needs no database: the repeat chain rule, labels and arguments."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from linecopilot.tools.losses import (
    BreakdownArgs,
    LossParetoArgs,
    RepeatArgs,
    chain_repeats,
    shift_slot,
    value,
)
from linecopilot.tools.registry import TOOLS, call_tool

T0 = datetime(2020, 1, 1, tzinfo=UTC)


def ep(i: int, start_h: float, key: str = "A_065", machine: str = "s_1", dur_min: int = 10):
    start = T0 + timedelta(hours=start_h)
    return {
        "episode_id": i,
        "machine_id": machine,
        "line_id": machine,
        "key": key,
        "start_ts": start,
        "end_ts": start + timedelta(minutes=dur_min),
        "duration_s": dur_min * 60.0,
    }


def test_repeat_chain_rule():
    eps = [ep(1, 0), ep(2, 2), ep(3, 4)]  # each starts ~1h50m after the previous ends
    (chain,) = chain_repeats(eps, within_hours=24, min_repeats=3)
    assert [e["episode_id"] for e in chain] == [1, 2, 3]
    assert chain_repeats(eps, within_hours=1, min_repeats=3) == []
    assert chain_repeats(eps, within_hours=24, min_repeats=4) == []


def test_repeat_chain_splits_on_key_and_machine_and_sorts_by_lost():
    eps = [
        ep(1, 0),
        ep(2, 1, key="A_001"),
        ep(3, 2),
        ep(4, 3, machine="s_2"),
        ep(5, 4),
        ep(6, 100, key="A_001", dur_min=60),
        ep(7, 101, key="A_001", dur_min=60),
        ep(8, 102, key="A_001", dur_min=60),
    ]
    chains = chain_repeats(eps, within_hours=24, min_repeats=3)
    assert [[e["episode_id"] for e in c] for c in chains] == [[6, 7, 8], [1, 3, 5]]


def test_repeat_chain_skips_missing_key_and_handles_input_order():
    eps = [ep(3, 4), ep(1, 0), ep(2, 2), {**ep(9, 1), "key": None}]
    (chain,) = chain_repeats(eps, within_hours=24, min_repeats=3)
    assert [e["episode_id"] for e in chain] == [1, 2, 3]


def test_shift_slot_labels():
    assert shift_slot("piade:s_1:2020-01-01T06") == "A 06-14"
    assert shift_slot("piade:s_1:2020-01-01T14") == "B 14-22"
    assert shift_slot("piade:s_1:2020-01-01T22") == "C 22-06"


def test_stop_month_and_weekday_follow_the_stop_start():
    # PIADE stop at 03:00 UTC on 1 Feb 2020 belongs to the 22:00 shift of 31 Jan, but its
    # month and weekday are those of its own start.
    e = {"start_ts": datetime(2020, 2, 1, 3, tzinfo=UTC), "shift_id": "piade:s_1:2020-01-31T22"}
    assert value(e, "month", "piade") == "2020-02" and value(e, "weekday", "piade") == "Sat"
    # Brick: 23:30 UTC on 31 Oct 2025 is 01:30 on 1 Nov in Europe/Nicosia.
    b = {"start_ts": datetime(2025, 10, 31, 23, 30, tzinfo=UTC), "shift_id": "brick:2025-10-31"}
    assert value(b, "month", "brick") == "2025-11" and value(b, "weekday", "brick") == "Sat"


def test_args_limits():
    with pytest.raises(ValidationError):
        LossParetoArgs(line_id="brick", by="reason", top=51)
    with pytest.raises(ValidationError):
        LossParetoArgs(line_id="brick", by="weekday")
    with pytest.raises(ValidationError):
        RepeatArgs(line_id="brick", within_hours=0.4)
    with pytest.raises(ValidationError):
        RepeatArgs(line_id="brick", min_repeats=1)
    with pytest.raises(ValidationError):
        BreakdownArgs(line_id="brick", rows="reason", cols="hour")
    with pytest.raises(ValidationError):
        BreakdownArgs(line_id="brick", rows="reason", cols="month", bogus=1)


def test_loss_tools_registered():
    assert {"loss_pareto", "breakdown", "repeat_failures"} <= set(TOOLS)
    r = call_tool(None, "loss_pareto", {"line_id": "brick", "by": "reason", "top": 0})
    assert r.status == "out_of_scope" and "top" in r.missing
    r = call_tool(
        None,
        "repeat_failures",
        {"line_id": "brick", "start": "2025-10-10", "end": "2025-10-09"},
    )
    assert r.status == "out_of_scope" and r.missing == "end must be after start"


def test_repeat_chain_uses_running_max_end():
    # A long stop (0h-5h) overlaps a short one (1h-1h10); the next starts at 5h30. Against the
    # last episode's end (1h10) the gap is 4h20; against the chain's latest end (5h) it is 30m.
    eps = [ep(1, 0, dur_min=300), ep(2, 1), ep(3, 5.5)]
    (chain,) = chain_repeats(eps, within_hours=1, min_repeats=3)
    assert [e["episode_id"] for e in chain] == [1, 2, 3]


def test_repeat_chain_keeps_chains_touching_window():
    eps = [ep(1, 0), ep(2, 2), ep(3, 4), ep(4, 50), ep(5, 52), ep(6, 54)]
    inside = (T0 + timedelta(hours=3), T0 + timedelta(hours=10))
    (chain,) = chain_repeats(eps, within_hours=24, min_repeats=3, inside=inside)
    # The chain starts before the window and is kept whole; the later chain has no
    # episode starting inside the window and is dropped.
    assert [e["episode_id"] for e in chain] == [1, 2, 3]
