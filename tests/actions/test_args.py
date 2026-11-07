"""Canonical action arguments and the payload hash."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from linecopilot.actions import args
from linecopilot.actions.identity import ActionContext

CTX = ActionContext("copilot-agent", "sup.a", "mcp")

WO = {
    "asset_id": "s_1",
    "failure_mode": "jam",
    "priority": "medium",
    "description": "repeat jams",
    "evidence_event_ids": [3, 5],
}
QH = {
    "asset_id": "s_1",
    "product": "box",
    "window_start": "2021-01-01T08:00:00Z",
    "window_end": "2021-01-01T10:00:00Z",
    "reason": "bad seals",
    "evidence_event_ids": [3],
}
FU = {
    "assignee_role": "planner",
    "due_date": "2021-02-01",
    "description": "check spares",
    "evidence_event_ids": [],
}
RAW = {"work_order": WO, "quality_hold": QH, "follow_up": FU}


def h(action, raw, ctx=CTX):
    return args.payload_sha256(action, ctx, args.canonical(action, args.parse(action, raw)))


@pytest.mark.parametrize("extra", [{"on_behalf_of": "pm.a"}, {"user": "pm.a"}, {"role": "x"}])
@pytest.mark.parametrize("action", list(RAW))
def test_identity_fields_rejected(action, extra):
    with pytest.raises(args.InvalidArgs):
        args.parse(action, {**RAW[action], **extra})


def test_invalid_args_message_is_one_line():
    with pytest.raises(args.InvalidArgs) as e:
        args.parse("work_order", {**WO, "priority": "urgent", "evidence_event_ids": []})
    assert "\n" not in str(e.value)
    assert "priority" in str(e.value)


def test_unknown_action():
    with pytest.raises(args.InvalidArgs):
        args.parse("delete_everything", {})


def test_canonical_sorts_and_dedupes_evidence():
    m = args.parse("work_order", {**WO, "evidence_event_ids": [5, 3, 5]})
    assert args.canonical("work_order", m)["evidence_event_ids"] == [3, 5]


def test_evidence_bounds():
    with pytest.raises(args.InvalidArgs):
        args.parse("work_order", {**WO, "evidence_event_ids": []})
    with pytest.raises(args.InvalidArgs):
        args.parse("work_order", {**WO, "evidence_event_ids": list(range(51))})
    assert args.parse("follow_up", FU).evidence_event_ids == []
    with pytest.raises(args.InvalidArgs):
        args.parse("follow_up", {**FU, "evidence_event_ids": list(range(51))})


def test_max_lengths():
    with pytest.raises(args.InvalidArgs):
        args.parse("work_order", {**WO, "asset_id": "x" * 41})
    with pytest.raises(args.InvalidArgs):
        args.parse("work_order", {**WO, "failure_mode": "x" * 141})
    with pytest.raises(args.InvalidArgs):
        args.parse("follow_up", {**FU, "description": "x" * 2001})


def test_whitespace_only_change_same_hash():
    noisy = {
        **WO,
        "asset_id": " s_1 ",
        "description": "\n repeat jams  ",
        "evidence_event_ids": [5, 3, 3],
    }
    assert h("work_order", noisy) == h("work_order", WO)


def test_timezone_spelling_same_hash():
    other = {
        **QH,
        "window_start": "2021-01-01T10:00:00+02:00",
        "window_end": "2021-01-01T12:00:00+02:00",
    }
    assert h("quality_hold", other) == h("quality_hold", QH)
    canon = args.canonical("quality_hold", args.parse("quality_hold", other))
    assert canon["window_start"] == "2021-01-01T08:00:00+00:00"


CHANGES = {
    "work_order": {
        "asset_id": "s_2",
        "failure_mode": "jam2",
        "priority": "high",
        "description": "other",
        "evidence_event_ids": [3, 6],
    },
    "quality_hold": {
        "asset_id": "s_2",
        "product": "tin",
        "window_start": "2021-01-01T07:00:00Z",
        "window_end": "2021-01-01T11:00:00Z",
        "reason": "other",
        "evidence_event_ids": [4],
    },
    "follow_up": {
        "assignee_role": "operator",
        "due_date": "2021-02-02",
        "description": "other",
        "evidence_event_ids": [1],
    },
}


@pytest.mark.parametrize("action", list(RAW))
def test_any_field_change_changes_hash(action):
    base = h(action, RAW[action])
    for field, value in CHANGES[action].items():
        assert h(action, {**RAW[action], field: value}) != base, field


def test_context_and_action_bind_the_hash():
    base = h("work_order", WO)
    assert h("work_order", WO, ActionContext("copilot-agent", "sup.b", "mcp")) != base
    assert h("work_order", WO, ActionContext("sup.a", "sup.a", "web_form")) != base
    assert h("work_order", WO, ActionContext("x", "sup.a", "mcp")) != base
    # channel is not part of the bound payload (design: action, principal, on_behalf_of, args)
    assert h("work_order", WO, ActionContext("copilot-agent", "sup.a", "web_chat")) == base


def test_hash_is_sha256_hex():
    assert len(h("work_order", WO)) == 64


def test_hold_window_order():
    with pytest.raises(args.InvalidArgs):
        args.parse("quality_hold", {**QH, "window_end": QH["window_start"]})
    with pytest.raises(args.InvalidArgs):
        args.parse("quality_hold", {**QH, "window_end": "2021-01-01T07:00:00Z"})


def test_naive_datetime_rejected():
    with pytest.raises(args.InvalidArgs):
        args.parse("quality_hold", {**QH, "window_start": "2021-01-01T08:00:00"})
    with pytest.raises(args.InvalidArgs):
        args.parse("quality_hold", {**QH, "window_end": "2021-01-01T10:00:00"})


def test_aware_datetime_objects_accepted():
    s = datetime(2021, 1, 1, 8, tzinfo=timezone(timedelta(hours=1)))
    m = args.parse("quality_hold", {**QH, "window_start": s, "window_end": s + timedelta(hours=1)})
    assert m.window_start.astimezone(UTC).hour == 7


def test_product_optional():
    raw = {k: v for k, v in QH.items() if k != "product"}
    assert args.canonical("quality_hold", args.parse("quality_hold", raw))["product"] is None


def test_unicode_normalisation_same_hash():
    nfc = {**WO, "description": "caf\u00e9 jam"}
    nfd = {**WO, "description": "cafe\u0301 jam"}
    assert h("work_order", nfc) == h("work_order", nfd)


def test_evidence_ids_must_be_real_ints():
    for bad in (True, "2", 3.0):
        with pytest.raises(args.InvalidArgs):
            args.parse("work_order", {**WO, "evidence_event_ids": [bad]})
