from linecopilot.reports.readme import render_readme


def test_render_replaces_only_marked_section():
    text = (
        "intro\n<!-- oee:start -->\nold\n<!-- oee:end -->\n"
        "<!-- other:start -->\nkeep\n<!-- other:end -->\ntail\n"
    )
    out = render_readme(text, {"oee": "new line"})
    assert "new line" in out and "old" not in out
    assert "<!-- other:start -->\nkeep\n<!-- other:end -->" in out
    assert out.startswith("intro\n") and out.endswith("tail\n")


def test_render_is_idempotent():
    text = "<!-- oee:start -->\n<!-- oee:end -->\n"
    once = render_readme(text, {"oee": "x"})
    assert render_readme(once, {"oee": "x"}) == once


def test_missing_marker_raises():
    import pytest

    with pytest.raises(ValueError):
        render_readme("no markers", {"oee": "x"})
