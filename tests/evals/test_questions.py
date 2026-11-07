"""The question set is deterministic, hashed, and fair to score."""

from collections import Counter

from evals.questions import build_questions, canonical_json, question_set_hash
from evals.truth import TRUTH_FNS

# Changing the questions changes this hash; update it on purpose, never to make a test pass.
PINNED_HASH = "51b9179fbd457995b1ab5045f8578299be04b77ec4add5b945bff40eeaf2ab27"


def test_question_set_deterministic_and_hash_stable():
    a, b = build_questions(), build_questions()
    assert canonical_json(a) == canonical_json(b)
    assert question_set_hash(a) == question_set_hash(b) == PINNED_HASH
    assert question_set_hash(build_questions(seed=1)) != PINNED_HASH


def test_has_ten_unanswerable():
    qs = build_questions()
    kinds = Counter(q.kind for q in qs)
    assert kinds["na"] == 10
    assert 55 <= kinds["numeric"] + kinds["label"] <= 65
    assert all(q.expected_fn == "not_available" for q in qs if q.kind == "na")


def test_questions_well_formed():
    qs = build_questions()
    assert len({q.id for q in qs}) == len(qs)
    assert len({q.text for q in qs}) == len(qs)
    for q in qs:
        assert q.expected_fn in TRUTH_FNS
        if q.kind != "na":
            # every answerable question states the form the ANSWER line should take
            assert "Answer " in q.text, q.id
            assert q.unit is not None, q.id
        if q.kind == "numeric":
            assert q.tolerance, q.id
    templates = Counter(q.template for q in qs)
    assert len(templates) == 11
