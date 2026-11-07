"""The answer-eval question set: about 60 answerable questions from templates plus 10 the
data cannot answer.

Assets and months come from fixed pools of whole months with data, sampled with a seeded
RNG, so the list (and its hash) is the same on every run. Each question states the unit or
form the ANSWER line should take. The expected answer is not stored here: evals/truth.py
computes it from the database (`expected_fn` with `params`). `python -m evals.questions
--check` runs every truth function against the live database and fails on a question
whose answer is missing or degenerate (a top reason that nearly ties)."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

SEED = 0
REL_TOL = 0.02
ABS_TOL_RATIO = 0.005  # half a percentage point
TOP_MARGIN = 0.15  # top reason must beat the runner-up by this share of its lost time


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    kind: str  # numeric | label | na
    expected_fn: str
    params: dict[str, Any]
    template: str
    unit: str | None = None  # ratio | pp | s_as_h | s_as_min | count | date | label
    tolerance: dict[str, float] = field(default_factory=dict)


# Whole months with data. Partial months at the edges of each machine's coverage are left out.
BRICK_MONTHS = ["2025-10", "2025-11", "2025-12", "2026-02", "2026-03"]
# Brick availability is asked as availability_calc. October 2025 is left out (its published
# planned time disagrees with the stop log, docs/data-notes.md) and so is March 2026 (one
# shift has no published planned time, so it drops out of availability_calc).
BRICK_AVAILABILITY_MONTHS = ["2025-11", "2025-12", "2026-02"]
PIADE_MONTHS = {
    "s_1": [f"2020-{m:02d}" for m in range(1, 13)] + [f"2021-{m:02d}" for m in range(1, 13)],
    "s_2": [f"2020-{m:02d}" for m in (9, 11, 12)] + [f"2021-{m:02d}" for m in range(1, 13)],
    "s_3": ["2020-11", "2020-12"] + [f"2021-{m:02d}" for m in range(4, 13)],
    "s_4": [f"2020-{m:02d}" for m in (1, 2, 3, 4)] + [f"2021-{m:02d}" for m in range(4, 13)],
    "s_5": [f"2020-{m:02d}" for m in (2, 3, 5, 6, 7, 8, 9, 10)]
    + [f"2021-{m:02d}" for m in (4, 5, 6, 9, 10, 11, 12)],
}
# Top reasons that come within TOP_MARGIN of the runner-up (found with --check): not asked.
NEAR_TIES = {
    ("s_2", "2021-04"),
    ("s_2", "2021-06"),
    ("s_2", "2021-11"),
    ("s_4", "2021-08"),
    ("s_4", "2021-09"),
}
NOTE_WORDS = ["ΥΓΡΑΣΙΑ", "ΚΟΥΖΙΝΕΤΟ", "TELARVN", "ΜΑΓΝΗΤΗ", "reflector"]

RATIO_TOL = {"abs": ABS_TOL_RATIO}
REL = {"rel": REL_TOL}


def month_name(month: str) -> str:
    y, m = (int(x) for x in month.split("-"))
    return date(y, m, 1).strftime("%B %Y")


def availability_name(asset: str) -> str:
    if asset == "brick":
        return "availability recomputed from the stop log (availability_calc)"
    return "availability"


def reason_name(asset: str) -> str:
    return "stop group" if asset == "brick" else "alarm code"


def asset_name(asset: str) -> str:
    return "the brick line" if asset == "brick" else f"machine {asset}"


def _piade_pairs() -> list[tuple[str, str]]:
    return [(a, m) for a, ms in PIADE_MONTHS.items() for m in ms]


def _pick(rng: random.Random, n_brick: int, n_piade: int, exclude=frozenset(), brick_months=None):
    months = BRICK_MONTHS if brick_months is None else brick_months
    brick = [("brick", m) for m in months if ("brick", m) not in exclude]
    piade = [p for p in _piade_pairs() if p not in exclude]
    return rng.sample(brick, n_brick) + rng.sample(piade, n_piade)


def build_questions(seed: int = SEED) -> list[Question]:
    rng = random.Random(seed)
    qs: list[Question] = []

    def add(template: str, text: str, kind: str, fn: str, params: dict, unit=None, tol=None):
        qs.append(
            Question(
                id=f"{template}_{sum(q.template == template for q in qs) + 1:02d}",
                text=text,
                kind=kind,
                expected_fn=fn,
                params=params,
                template=template,
                unit=unit,
                tolerance=tol or {},
            )
        )

    for a, m in _pick(rng, 0, 6):
        add(
            "oee_month",
            f"What was the OEE of {asset_name(a)} in {month_name(m)}? Answer as a percentage.",
            "numeric",
            "piade_oee",
            {"asset": a, "month": m},
            "ratio",
            RATIO_TOL,
        )
    for a, m in _pick(rng, 2, 5, brick_months=BRICK_AVAILABILITY_MONTHS):
        add(
            "availability_month",
            f"What was the {availability_name(a)} of {asset_name(a)} in {month_name(m)}? "
            "Answer as a percentage.",
            "numeric",
            "availability",
            {"asset": a, "month": m},
            "ratio",
            RATIO_TOL,
        )
    top_pairs = _pick(rng, 3, 6, exclude=NEAR_TIES)
    for a, m in top_pairs:
        if a == "brick":
            text = (
                f"Which stop group cost the brick line the most stop time in {month_name(m)}? "
                "Answer with the stop group name."
            )
        else:
            text = (
                f"Which alarm code cost {asset_name(a)} the most stop time in {month_name(m)}? "
                "Answer with the alarm code."
            )
        add("top_reason", text, "label", "top_reason", {"asset": a, "month": m}, "label")
    for a, m in _pick(rng, 2, 4, exclude=NEAR_TIES):
        add(
            "top_reason_lost",
            f"How much stop time did the biggest {reason_name(a)} cost {asset_name(a)} in "
            f"{month_name(m)}? Answer in hours.",
            "numeric",
            "top_reason_lost_s",
            {"asset": a, "month": m},
            "s_as_h",
            REL,
        )
    for a, m in _pick(rng, 2, 4):
        add(
            "mttr_month",
            f"What was the MTTR (mean time to repair) of {asset_name(a)} in {month_name(m)}? "
            "Answer in minutes.",
            "numeric",
            "mttr_s",
            {"asset": a, "month": m},
            "s_as_min",
            REL,
        )
    for a, m in _pick(rng, 2, 3):
        add(
            "mtbf_month",
            f"What was the MTBF (mean time between failures) of {asset_name(a)} in "
            f"{month_name(m)}? Answer in minutes.",
            "numeric",
            "mtbf_s",
            {"asset": a, "month": m},
            "s_as_min",
            REL,
        )
    for a, m in _pick(rng, 2, 4):
        add(
            "stop_count",
            f"How many stops that count in OEE did {asset_name(a)} have in {month_name(m)}? "
            "Answer with a number.",
            "numeric",
            "stop_count",
            {"asset": a, "month": m},
            "count",
            REL,
        )
    for a, m in _pick(rng, 2, 3):
        key = "stop group" if a == "brick" else "alarm code"
        add(
            "repeat_chains",
            f"How many repeat-failure chains did {asset_name(a)} have in {month_name(m)}, "
            f"counting a chain as the same {key} failing at least 3 times with each failure "
            "starting within 24 hours of the previous one? Answer with a number.",
            "numeric",
            "repeat_chain_count",
            {"asset": a, "month": m, "within_hours": 24, "min_repeats": 3},
            "count",
            REL,
        )
    for w in NOTE_WORDS:
        add(
            "note_date",
            f"On what date was a brick line stop logged with an operator note mentioning "
            f'"{w}"? Answer as YYYY-MM-DD.',
            "label",
            "note_date",
            {"word": w},
            "date",
        )
    piade = _piade_pairs()
    by_asset: dict[str, list[str]] = {}
    for a, m in piade:
        by_asset.setdefault(a, []).append(m)
    compare_assets = ["brick", *rng.sample(sorted(PIADE_MONTHS), 4)]
    for a in compare_assets:
        months = BRICK_AVAILABILITY_MONTHS if a == "brick" else by_asset[a]
        ma, mb = sorted(rng.sample(months, 2))
        add(
            "compare_availability",
            f"By how many percentage points did the {availability_name(a)} of {asset_name(a)} "
            "change "
            f"from {month_name(ma)} to {month_name(mb)}? Answer in percentage points, "
            "negative if it fell.",
            "numeric",
            "availability_delta",
            {"asset": a, "month_a": ma, "month_b": mb},
            "pp",
            RATIO_TOL,
        )
    qs += unanswerable()
    return qs


def unanswerable() -> list[Question]:
    na = [
        ("How much electricity, in kWh, did machine s_1 use in March 2021?", {}),
        ("What was the OEE of machine s_9 in May 2021? Answer as a percentage.", {}),
        (
            "What was the availability of the brick line in June 2025? Answer as a percentage.",
            {"asset": "brick", "month": "2025-06"},
        ),
        ("Which operator was running the brick line on 14 October 2025?", {}),
        ("What did the downtime on machine s_2 cost in euros in July 2021?", {}),
        (
            "What was the OEE of machine s_3 in February 2021? Answer as a percentage.",
            {"asset": "s_3", "month": "2021-02"},
        ),
        ("How many kilograms of scrap did the brick line produce in November 2025?", {}),
        ("Which maintenance technician repaired the longest stop on machine s_4 in 2021?", {}),
        ("What was the average ambient temperature at machine s_5 in June 2021?", {}),
        (
            "What was the MTTR of machine s_5 in August 2021? Answer in minutes.",
            {"asset": "s_5", "month": "2021-08"},
        ),
    ]
    return [
        Question(
            id=f"na_{i:02d}",
            text=text,
            kind="na",
            expected_fn="not_available",
            params=params,
            template="unanswerable",
        )
        for i, (text, params) in enumerate(na, 1)
    ]


def canonical_json(qs: list[Question]) -> str:
    return json.dumps(
        [asdict(q) for q in qs], sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def question_set_hash(qs: list[Question] | None = None) -> str:
    qs = build_questions() if qs is None else qs
    return hashlib.sha256(canonical_json(qs).encode()).hexdigest()


UNIT_SCALE = {"ratio": 100.0, "pp": 100.0, "s_as_h": 1 / 3600, "s_as_min": 1 / 60}


def in_question_unit(q: Question, expected: float) -> float:
    """The expected value in the unit the question asks for (%, pp, hours, minutes, count)."""
    return expected * UNIT_SCALE.get(q.unit or "", 1.0)


def check(conn, qs: list[Question]) -> list[str]:
    """Problems with the question set on this database: a truth that cannot be computed, a
    top reason within TOP_MARGIN of the runner-up, an answerable question with zero
    evidence, or mart.stop_episode disagreeing with a recount from core.event on the
    cross-check months (the answer key shares the marts with the tools)."""
    from evals.truth import CROSSCHECK_MONTHS, NoTruth, compute, crosscheck_episodes

    problems = [p for a, m in CROSSCHECK_MONTHS for p in crosscheck_episodes(conn, a, m)]
    for q in qs:
        try:
            t = compute(conn, q.expected_fn, q.params)
        except NoTruth as e:
            problems.append(f"{q.id}: {e}")
            continue
        if q.expected_fn in ("top_reason", "top_reason_lost_s"):
            top = compute(conn, "top_reason", q.params)
            lost, runner = top.detail["lost_s"], top.detail["runner_up_lost_s"]
            if runner > (1 - TOP_MARGIN) * lost:
                problems.append(f"{q.id}: top reason nearly ties ({lost:.0f} s vs {runner:.0f} s)")
        if q.kind != "na" and not t.evidence_event_ids:
            problems.append(f"{q.id}: no evidence events")
        if q.kind == "numeric" and 1900 <= abs(in_question_unit(q, float(t.expected))) < 2100:
            problems.append(f"{q.id}: answer looks like a year, which scoring treats as noise")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="validate against the live database")
    ap.add_argument("--list", action="store_true", help="print the questions")
    args = ap.parse_args(argv)
    qs = build_questions()
    print(f"{len(qs)} questions, hash {question_set_hash(qs)}")
    if args.list:
        for q in qs:
            print(f"{q.id}\t{q.kind}\t{q.text}")
    if args.check:
        import psycopg

        from linecopilot.config import get_settings

        with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
            problems = check(conn, qs)
        for p in problems:
            print(p)
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
