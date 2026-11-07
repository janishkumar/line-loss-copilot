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
    assert num("ANSWER: -3.2", -0.032, "pp", RATIO)  # bare number on a pp question: points
    assert not num("ANSWER: -0.032", -0.032, "pp", RATIO)
    # a number with a % unit wins over an earlier bare one
    assert num("ANSWER: 21 shifts, availability 70.2%", 0.702, "ratio", RATIO)
    # alarm codes are not numbers
    assert num("ANSWER: A_101 cost 23.7 h", 23.7 * 3600, "s_as_h")
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


def test_na_phrase_next_to_a_number_is_wrong():
    for text in (
        "ANSWER: not available (0%)",
        "ANSWER: No data, about 1200 kWh",
        "ANSWER: unknown, maybe 40%",
        "Energy use is not available.\nANSWER: 1234 kWh",  # only the ANSWER line counts
    ):
        assert not score(text, "na", "NOT_AVAILABLE").correct, text
    # the answer line is judged alone when present, even if the text before it says n/a
    assert score("I found 3 rows.\nANSWER: NOT_AVAILABLE", "na", "NOT_AVAILABLE").correct
    # an answerable question answered "not available, 62%" is wrong too
    assert not score("ANSWER: not available, 62%", "numeric", 0.62, "ratio", RATIO).correct


def test_bare_words_are_not_na():
    assert not is_na("The cause is unknown but OEE was 40%")
    assert not is_na("the line was unavailable for maintenance")
    assert is_na("unknown") and is_na("Data is unavailable.")


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
    assert is_na("ANSWER: N/A") and not is_na("ANSWER: n/an")
    assert is_na("ANSWER: no data for s_9 in May 2021 [event:12]")
    assert is_na("ANSWER: not available for 14 October 2025")


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


def test_pp_and_ratio_preference():
    # pp question: pp/points first, then a signed or bare number, then %
    assert num("ANSWER: +3.0 (60.0% to 63.0%)", 0.03, "pp", RATIO)
    assert num("ANSWER: from 60.0% to 63.0%, up 3.0 pp", 0.03, "pp", RATIO)
    assert num("ANSWER: rose 2 pp to 70.2%", 0.02, "pp", RATIO)
    assert num("ANSWER: 3.0%", 0.03, "pp", RATIO)  # only a % given: read as points
    # ratio question: % first, then pp
    assert num("ANSWER: rose 2 pp to 70.2%", 0.702, "ratio", RATIO)
    assert num("ANSWER: from 60.0% to 63.0%, up 3.0 pp", 0.60, "ratio", RATIO)


def test_years_are_noise():
    assert num("ANSWER: In 2021 the OEE was 52.6%", 0.526, "ratio", RATIO)
    assert num("ANSWER: 1483 stops in 2020", 1483, "count")
    assert numbers("in 2021") == []


def test_explicit_na_token_wins():
    assert score("ANSWER: NOT_AVAILABLE (0 rows in 2021-02, 0%)", "na", "NOT_AVAILABLE").correct
    assert score("ANSWER: not_available 0", "na", "NOT_AVAILABLE").correct
    assert not score("ANSWER: not available (0%)", "na", "NOT_AVAILABLE").correct
