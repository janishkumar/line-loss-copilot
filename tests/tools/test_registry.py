"""Tool registry dispatch (offline: invalid calls never reach the database)."""

import pytest

from linecopilot.tools.envelope import Result
from linecopilot.tools.evidence import GetSourceRowsArgs
from linecopilot.tools.registry import TOOLS, ToolSpec, call_tool


def test_registry_has_stage2_foundation_tools():
    assert {"list_assets", "get_oee", "get_source_rows", "shift_evidence"} <= set(TOOLS)
    for name, spec in TOOLS.items():
        assert isinstance(spec, ToolSpec) and spec.name == name
        assert spec.description and spec.read_only
        assert spec.args_model.model_config.get("extra") == "forbid"


def test_registry_unknown_tool_and_bad_args():
    r = call_tool(None, "nope", {})
    assert isinstance(r, Result) and r.status == "out_of_scope" and "nope" in r.missing
    r = call_tool(None, "get_oee", {"bogus": 1})
    assert r.status == "out_of_scope" and "bogus" in r.missing
    r = call_tool(None, "get_oee", {"line_id": "brick", "limit": 0})
    assert r.status == "out_of_scope" and "limit" in r.missing
    r = call_tool(None, "get_source_rows", {})
    assert r.status == "out_of_scope"
    r = call_tool(None, "get_oee", None)
    assert r.status == "out_of_scope"


def test_get_oee_end_before_start_envelope():
    # Checked before any query, so no database is needed.
    r = call_tool(None, "get_oee", {"line_id": "brick", "start": "2025-10-10", "end": "2025-10-09"})
    assert r.status == "out_of_scope" and r.missing == "end must be after start"
    assert r.window is not None and r.window.line_id == "brick"


def test_get_source_rows_args_limits():
    with pytest.raises(ValueError):
        GetSourceRowsArgs()
    with pytest.raises(ValueError):
        GetSourceRowsArgs(event_ids=list(range(201)))
