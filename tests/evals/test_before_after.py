"""Claim parsing and scoring for the before/after test."""

from evals.before_after import parse_claims, score_claims

TRUTH = {
    "facts": [
        {"metric": "availability", "status": "scored", "direction": "down"},
        {"metric": "reason:FAILURE", "status": "scored", "direction": "down"},
        {"metric": "stop_count", "status": "ambiguous", "direction": None},
        {"metric": "mttr", "status": "flat", "direction": None},
    ],
    "status": {
        "availability": "down",
        "reason:FAILURE": "down",
        "reason:MATERIALS": "ambiguous",
        "stop_count": "ambiguous",
        "mttr": "flat",
    },
}


def test_parse_claims_fenced_and_bare():
    text = 'x\n```json\n[{"metric": "OEE", "direction": "Down", "value": 1}]\n```'
    assert parse_claims(text) == [{"metric": "OEE", "direction": "down", "value": 1}]
    bare = 'Claims: [{"metric": "mttr", "direction": "up"}, {"metric": "x"}, 3]\nANSWER: y'
    assert parse_claims(bare) == [{"metric": "mttr", "direction": "up", "value": None}]
    assert parse_claims("no json here") == []
    assert parse_claims("```json\n[not json]\n```") == []


def test_score_claims():
    claims = [
        {"metric": "Availability", "direction": "down", "value": None},  # found
        {"metric": "reason:failure", "direction": "up", "value": None},  # contradicts: wrong
        {"metric": "mttr", "direction": "up", "value": None},  # flat: neutral
        {"metric": "stop_count", "direction": "down", "value": None},  # ambiguous: neutral
        {"metric": "reason:MATERIALS", "direction": "up", "value": None},  # ambiguous
        {"metric": "reason:NOPE", "direction": "down", "value": None},  # unknown: wrong
        {"metric": "energy", "direction": "up", "value": None},  # unknown: wrong
    ]
    s = score_claims(claims, TRUTH)
    assert s["facts_total"] == 2 and s["facts_found"] == 1 and s["found"] == ["availability"]
    assert s["missed"] == ["reason:FAILURE"]
    assert s["wrong_claims"] == 3 and s["neutral_claims"] == 3
    assert s["not_scored"] == {"stop_count": "ambiguous", "mttr": "flat"}
    assert s["share_found"] == 0.5
    assert [c["verdict"] for c in s["claims"]] == [
        "correct",
        "wrong",
        "neutral",
        "neutral",
        "neutral",
        "wrong",
        "wrong",
    ]
