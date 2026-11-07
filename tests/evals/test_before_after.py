"""Claim parsing and scoring for the before/after test."""

from evals.before_after import parse_claims, score_claims

TRUTH = {
    "facts": [
        {"metric": "availability", "direction": "down"},
        {"metric": "reason:SETUPS-CHANGEOVERS", "direction": "down"},
    ],
    "directions": {"availability": "down", "reason:SETUPS-CHANGEOVERS": "down", "mttr": "up"},
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
        {"metric": "Availability", "direction": "down", "value": None},
        {"metric": "reason:setups-changeovers", "direction": "up", "value": None},
        {"metric": "mttr", "direction": "up", "value": None},
        {"metric": "reason:NOPE", "direction": "down", "value": None},
    ]
    s = score_claims(claims, TRUTH)
    assert s["facts_found"] == 1 and s["found"] == ["availability"]
    assert s["missed"] == ["reason:SETUPS-CHANGEOVERS"]
    assert s["wrong_claims"] == 2  # wrong direction, and a group that does not exist
    assert s["share_found"] == 0.5
