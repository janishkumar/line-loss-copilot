"""Pure parts of the one-time codes (no database)."""

from datetime import UTC, datetime

from linecopilot.actions import codes
from linecopilot.actions.identity import ActionContext

CTX = ActionContext("copilot-agent", "sup.a", "mcp")
NOW = datetime(2021, 1, 1, 8, tzinfo=UTC)


def test_alphabet_has_no_lookalikes():
    assert codes.ALPHABET == "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    assert len(set(codes.ALPHABET)) == 31
    assert not set("ILO01") & set(codes.ALPHABET)


def test_normalise():
    assert codes.normalise("  ab3k-x ".replace("-", "")) == "AB3KX"
    assert codes.normalise(None) == ""


def test_hash_is_stable_and_normalised():
    assert codes.hash_code(" abc23 ") == codes.hash_code("ABC23")
    assert len(codes.hash_code("ABC23")) == 64


def test_new_code_shape():
    seen = {codes.new_code() for _ in range(50)}
    assert len(seen) == 50
    assert all(len(c) == 8 and set(c) <= set(codes.ALPHABET) for c in seen)


def test_missing_code_needs_no_database():
    for blank in (None, "", "   "):
        assert codes.redeem(None, blank, "work_order", CTX, "h", NOW) == "missing code"
