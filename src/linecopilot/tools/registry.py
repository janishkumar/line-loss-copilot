"""Name -> tool. The API, the MCP server and the chat loop all dispatch through call_tool."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from linecopilot.tools.assets import ListAssetsArgs, list_assets
from linecopilot.tools.envelope import Result
from linecopilot.tools.evidence import (
    GetSourceRowsArgs,
    ShiftEvidenceArgs,
    get_source_rows,
    shift_evidence,
)
from linecopilot.tools.oee import GetOeeArgs, get_oee


@dataclass
class ToolSpec:
    name: str
    fn: Callable[[Any, Any], Result]
    args_model: type[BaseModel]
    description: str
    read_only: bool = True


TOOLS: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    TOOLS[spec.name] = spec
    return spec


register(
    ToolSpec(
        "list_assets",
        list_assets,
        ListAssetsArgs,
        "List the production lines and machines loaded, with each one's data coverage "
        "(first and last timestamp) and event count.",
    )
)
register(
    ToolSpec(
        "get_oee",
        get_oee,
        GetOeeArgs,
        "OEE (availability, performance, quality) for the brick line or a PIADE machine, per "
        "shift, day or month over a window. Each row cites the raw rows behind it.",
    )
)
register(
    ToolSpec(
        "get_source_rows",
        get_source_rows,
        GetSourceRowsArgs,
        "Fetch raw source rows exactly as loaded, by citation (raw_table, source_file, "
        "raw_row_id) or by event id. Unknown references are listed as not found.",
    )
)
register(
    ToolSpec(
        "shift_evidence",
        shift_evidence,
        ShiftEvidenceArgs,
        "Every raw row behind one shift's OEE numbers, with all columns as loaded.",
    )
)


def _errors(e: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or 'args'}: {err['msg']}" for err in e.errors()
    )


def call_tool(conn: Any, name: str, args: dict | None) -> Result:
    """Validate `args` against the tool's model and run it. An unknown tool or invalid
    arguments come back as an out_of_scope Result rather than an exception."""
    spec = TOOLS.get(name)
    if spec is None:
        return Result(status="out_of_scope", missing=f"unknown tool {name!r}")
    try:
        parsed = spec.args_model.model_validate(args if args is not None else {})
    except ValidationError as e:
        return Result(status="out_of_scope", missing=f"invalid arguments for {name}: {_errors(e)}")
    return spec.fn(conn, parsed)
