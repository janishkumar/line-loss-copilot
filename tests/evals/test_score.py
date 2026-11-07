"""Scoring the ANSWER line."""

import pytest

from evals.score import dates, is_na, numbers, score

RATIO = {"abs": 0.005}
REL = {"rel": 0.02}


def num(answer: str, expected: float, unit: str, tol=REL) -> bool:
    return score(answer, "numeric", expected, unit, tol).correct


def test_score_numeric_units_and_tolerance():
    # ratios: percent or fraction, 0.5 pp absolute
    assert num("Text [event:1]\nANSWER: 62.3%", 0.6234, "ratio", RATIO)
    assert num("ANSWER: 0.623", 0.6234, "ratio", RATIO)
    assert num("ANSWER: 62.3", 0.6234, "ratio", RATIO)
    assert num("ANSWER: 62.7 percent", 0.6234, "ratio", RATIO)
    assert not num("ANSWER: 61.5%", 0.6234, "ratio", RATIO)
    # machine ids and dates are not the number
    assert num("ANSWER: s_1 in 2021-03 had OEE 52.6% [event:7]", 0.5264, "ratio", RATIO)
    assert num("ANSWER: March 2021: 52.6%", 0.5264, "ratio", RATIO)
    # percentage points, signed
    assert num("ANSWER: -3.2 pp", -0.032, "pp", RATIO)
    assert num("ANSWER: −3.2 percentage points", -0.032, "pp", RATIO)
    assert not num("ANSWER: 3.2 pp", -0.032, "pp", RATIO)
    # durations: stated unit wins, else the unit the question asked for
    assert num("ANSWER: 23.8 h", 23.8 * 3600, "s_as_h")
    assert num("ANSWER: 23.8", 23.8 * 3600, "s_as_h")
    assert num("ANSWER: 1428 minutes", 23.8 * 3600, "s_as_h")
    assert num("ANSWER: 85680 s", 23.8 * 3600, "s_as_h")
    assert num("ANSWER: 16.4 min", 984.0, "s_as_min")
    assert num("ANSWER: 984 seconds", 984.0, "s_as_min")
    assert not num("ANSWER: 16.4 h", 984.0, "s_as_min")
    # 2% relative
    assert num("ANSWER: 1,483 stops", 1483, "count")
    assert num("ANSWER: 1500", 1483, "count")
    assert not num("ANSWER: 1520", 1483, "count")
    assert not num("ANSWER: 7", 6, "count")


def test_numeric_needs_answer_line_and_a_number():
    assert not num("The OEE was 62.3%.", 0.623, "ratio", RATIO)
    assert not num("ANSWER: NOT_AVAILABLE", 0.623, "ratio", RATIO)
    assert not num("ANSWER: about two thirds", 0.623, "ratio", RATIO)


def test_numbers_drop_noise():
    assert numbers("s_3 2021-04-01 [event:12, 13] 4.5 h") == [(4.5, "h")]


def test_score_na_phrases():
    for text in (
        "ANSWER: NOT_AVAILABLE",
        "The data has no energy readings.\nANSWER: Not available",
        "ANSWER: no data for June 2025",
        "ANSWER: insufficient evidence",
        "Machine s_9 does not exist in the data.",  # no ANSWER line: whole text
    ):
        assert score(text, "na", "NOT_AVAILABLE").correct, text
    assert not score("ANSWER: 1234 kWh", "na", "NOT_AVAILABLE").correct
    assert not score("ANSWER: 41.2%", "na", "NOT_AVAILABLE").correct
    assert is_na("unavailable") and is_na("ANSWER: N/A") and not is_na("ANSWER: 4 n/an")


@pytest.mark.parametrize(
    "line,ok",
    [
        ("ANSWER: A_065", True),
        ("ANSWER: a065 [event:3]", True),
        ("ANSWER: The top alarm was A-065 (38 h).", True),
        ("ANSWER: A_0650", False),
        ("ANSWER: A_065, then A_066", False),  # names another candidate
        ("ANSWER: A_066", False),
    ],
)
def test_score_label(line, ok):
    assert score(line, "label", "A_065", "label", alternatives=["A_066", "A_001"]).correct is ok


def test_score_label_multiword():
    alts = ["FAILURE", "OPERATIONAL"]
    line = "ANSWER: setups-changeovers"
    assert score(line, "label", "SETUPS-CHANGEOVERS", "label", None, alts).correct
    assert score("ANSWER: FAILURE stops", "label", "FAILURE", "label", None, alts[1:]).correct


def test_score_dates():
    for line in (
        "ANSWER: 2025-10-08",
        "ANSWER: 8 October 2025",
        "ANSWER: October 8, 2025 [event:651]",
        "ANSWER: 08/10/2025",
    ):
        assert score(line, "label", "2025-10-08", "date").correct, line
    assert not score("ANSWER: 2025-10-09", "label", "2025-10-08", "date").correct
    assert not score("ANSWER: 2025-10-08 or 2025-10-09", "label", "2025-10-08", "date").correct
    assert dates("on the 3rd March 2026") == ["2026-03-03"]
