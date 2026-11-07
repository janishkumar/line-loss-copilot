"""Scoring one answer against its expected value.

Only the ANSWER line counts (the last-line rule of linecopilot.chat.prompt.split_answer).
Numeric answers: within 2% relative, or for ratios and percentage-point changes within 0.5
percentage points absolute (2% of a ratio would be looser than that); percent and
fraction forms are both accepted, and durations may be given in seconds, minutes or hours
when the unit is written. Labels: case-insensitive whole-word match after stripping
punctuation, wrong if the line also names another candidate label. Unanswerable questions:
correct iff the answer says NOT_AVAILABLE or a fixed "no data" phrase."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from linecopilot.chat.prompt import split_answer

NOT_AVAILABLE = "NOT_AVAILABLE"
NA_PHRASES = (
    "not_available",
    "not available",
    "no data",
    "no evidence",
    "insufficient evidence",
    "insufficient data",
    "unavailable",
    "cannot be determined",
    "can't be determined",
    "cannot determine",
    "not in the data",
    "no information",
    "not recorded",
    "does not exist",
    "no such machine",
    "no records",
    "unknown",
)
UNIT_S = {
    "s": 1.0,
    "sec": 1.0,
    "secs": 1.0,
    "second": 1.0,
    "seconds": 1.0,
    "min": 60.0,
    "mins": 60.0,
    "minute": 60.0,
    "minutes": 60.0,
    "h": 3600.0,
    "hr": 3600.0,
    "hrs": 3600.0,
    "hour": 3600.0,
    "hours": 3600.0,
}
DEFAULT_UNIT_S = {"s_as_h": 3600.0, "s_as_min": 60.0}
MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
    "|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
# Things that look like numbers but are not the answer: machine ids, ISO dates, month + year.
NOISE = re.compile(
    rf"\bs_\d+\b|\b\d{{4}}-\d{{2}}(?:-\d{{2}})?\b|\b(?:{MONTHS})\.?\s+\d{{4}}\b|\[event:[^\]]*\]",
    re.IGNORECASE,
)
NUMBER = re.compile(
    r"(?P<sign>[-+−])?\s*(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
    r"\s*(?P<unit>%|percentage points?|pp|points?|[a-z]+)?",
    re.IGNORECASE,
)


@dataclass
class Score:
    extracted: str | None
    value: Any
    correct: bool


def answer_line(text: str) -> str | None:
    return split_answer(text)[1]


def numbers(line: str) -> list[tuple[float, str | None]]:
    """(value, unit) for each number in the line, after dropping machine ids and dates."""
    out = []
    for m in NUMBER.finditer(NOISE.sub(" ", line)):
        v = float(m.group("num").replace(",", ""))
        if m.group("sign") in ("-", "−"):
            v = -v
        unit = (m.group("unit") or "").lower() or None
        out.append((v, unit))
    return out


def _close(a: float, e: float, tol: dict[str, float]) -> bool:
    """Within `abs` or within `rel` of the expected value, whichever the tolerance gives."""
    if "abs" in tol and abs(a - e) <= tol["abs"] + 1e-12:
        return True
    return "rel" in tol and abs(a - e) <= tol["rel"] * abs(e) + 1e-12


def _ratio_candidates(v: float, unit: str | None) -> list[float]:
    """A ratio or percentage-point answer as fractions: '62%' and '3.1 pp' are /100; a bare
    number may be either form, so both readings are tried."""
    if unit and (unit == "%" or unit.startswith("percent") or unit in ("pp", "point", "points")):
        return [v / 100]
    return [v / 100, v]


def score_numeric(line: str, expected: float, unit: str, tol: dict[str, float]) -> Score:
    nums = numbers(line)
    if not nums:
        return Score(line, None, False)
    if unit in ("ratio", "pp"):
        v, u = nums[0]
        cands = _ratio_candidates(v, u)
        return Score(line, cands[0], any(_close(c, expected, tol) for c in cands))
    if unit in DEFAULT_UNIT_S:
        timed = [(v, u) for v, u in nums if u in UNIT_S]
        v, u = timed[0] if timed else nums[0]
        secs = v * (UNIT_S[u] if u in UNIT_S else DEFAULT_UNIT_S[unit])
        return Score(line, secs, _close(secs, expected, tol))
    v = nums[0][0]
    return Score(line, v, _close(v, expected, tol))


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w\s]|_", " ", s.lower()).split())


def _norm_compact(s: str) -> str:
    return re.sub(r"[^\w]|_", "", s.lower())


def _has(line: str, label: str) -> bool:
    """Whole-word, punctuation-blind match: A_065 matches 'A_065', 'a065' and 'A-065'."""
    words = _norm(line).split()
    target = _norm(label).split()
    n = len(target)
    if any(words[i : i + n] == target for i in range(len(words) - n + 1)):
        return True
    compact = _norm_compact(label)
    return any(_norm_compact(w) == compact for w in re.split(r"\s+", line))


DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d %B %Y", "%B %d %Y", "%d %b %Y", "%b %d %Y")


def dates(line: str) -> list[str]:
    """ISO dates found in the line, from ISO, day/month/year and written-month forms."""
    found = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", line)
    found += re.findall(r"\b\d{1,2}[/.]\d{1,2}[/.]\d{4}\b", line)
    found += re.findall(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTHS}),?\s+\d{{4}}\b", line, re.I)
    found += re.findall(rf"\b(?:{MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b", line, re.I)
    out = []
    for raw in found:
        s = re.sub(r"(\d)(st|nd|rd|th)", r"\1", raw).replace(",", "")
        for fmt in DATE_FORMATS:
            try:
                out.append(datetime.strptime(s, fmt).date().isoformat())
                break
            except ValueError:
                continue
    return list(dict.fromkeys(out))


def score_label(line: str, expected: str, unit: str | None, alternatives: list[str]) -> Score:
    if unit == "date":
        found = dates(line)
        return Score(line, found[0] if found else None, found == [expected])
    others = [a for a in alternatives if _norm(a) != _norm(expected) and _has(line, a)]
    hit = _has(line, expected)
    return Score(line, expected if hit else None, hit and not others)


_NA_SHORT = re.compile(r"(?<![\w/])n/a(?![\w/])", re.IGNORECASE)


def is_na(text: str) -> bool:
    low = text.lower()
    return (
        NOT_AVAILABLE.lower() in low
        or any(p in low for p in NA_PHRASES)
        or bool(_NA_SHORT.search(text))
    )


def score(
    answer: str,
    kind: str,
    expected: Any,
    unit: str | None = None,
    tolerance: dict[str, float] | None = None,
    alternatives: list[str] | None = None,
) -> Score:
    """Score one answer. An answerable question with no ANSWER line, or one answered as not
    available, is wrong. An unanswerable question is judged on the ANSWER line, or on the
    whole text when the line is missing."""
    line = answer_line(answer)
    if kind == "na":
        target = line if line is not None else answer
        return Score(line, None, is_na(target))
    if line is None:
        return Score(None, None, False)
    if NOT_AVAILABLE.lower() in line.lower():
        return Score(line, None, False)
    if kind == "numeric":
        return score_numeric(line, float(expected), unit or "count", tolerance or {})
    return score_label(line, str(expected), unit, alternatives or [])
