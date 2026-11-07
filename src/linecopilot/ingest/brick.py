"""Parse the brick line OEE and downtime CSVs into the standard contract.

Dates in the source are M/D/YY and are written out as ISO dates. Stop start and
end are local wall-clock times and stay local (no timezone conversion here).
Numeric values are validated and kept as stripped strings.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Literal

from linecopilot.ingest.contracts import ParsedFile, Rejected

Period = Literal["before", "after"]

OEE_FRACTIONS = ("oee", "availability", "performance", "quality")
OEE_QUANTITIES = (
    "good_production_s",
    "slow_production_s",
    "planned_s",
    "ideal_qty",
    "planned_stops_s",
    "unplanned_stops_s",
    "good_qty",
    "total_qty",
)
MAX_FRACTION = 1.5

_OEE_SHARED = {
    "shiftDate": "shift_date",
    "OEE": "oee",
    "Availability": "availability",
    "Performance": "performance",
    "Quality": "quality",
    "Sum of plannedStopsTimeSec": "planned_stops_s",
    "Sum of unplannedStopsTimeSec": "unplanned_stops_s",
    "Sum of goodQty": "good_qty",
    "Sum of totalQty": "total_qty",
}

OEE_COLUMNS: dict[Period, dict[str, str]] = {
    "before": {
        **_OEE_SHARED,
        "Sumof goodProductionTimeSec": "good_production_s",
        "Sum of slowProductionTimeSec": "slow_production_s",
        "Sumof plannedTime": "planned_s",
        "Sumof idealProductionQuantity": "ideal_qty",
    },
    "after": {
        **_OEE_SHARED,
        "Sum of goodProdction": "good_production_s",
        "Sum of slowProduction": "slow_production_s",
        "Sum of plannedTime": "planned_s",
        "Sum of idealQty": "ideal_qty",
    },
}

DOWNTIME_COLUMNS: dict[Period, dict[str, str]] = {
    "before": {
        "Date": "shift_date",
        "Productcode": "product",
        "StopGroup": "stop_group",
        "Stop": "stop",
        "StopType": "stop_type",
        "StopLocation": "location",
        "ExtraText": "note",
        "StopStartTime": "start_local",
        "StopEndTime": "end_local",
        "StopDuration(min)": "duration_min",
    },
    "after": {
        "Date": "shift_date",
        "Product code": "product",
        "Stop group": "stop_group",
        "Stop": "stop",
        "Stop type": "stop_type",
        "Stop Location": "location",
        "Extra text": "note",
        "Stop start time": "start_local",
        "Stop end time": "end_local",
        "Stop duration (min) (TTR)": "duration_min",
    },
}

DOWNTIME_REQUIRED = (
    "shift_date",
    "product",
    "stop_group",
    "stop",
    "stop_type",
    "start_local",
    "end_local",
    "duration_min",
)
DOWNTIME_OPTIONAL_TEXT = ("location", "note")


def _read(path: Path, mapping: dict[str, str]):
    """Return (records, trimmed_columns); each record is a dict keyed by normalised name."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"{path}: empty file")
        names = [h.strip() for h in header]
        unknown = [n for n in names if n and n not in mapping]
        if unknown:
            raise ValueError(f"{path}: unexpected columns {unknown}")
        named = [n for n in names if n]
        dupes = sorted({n for n in named if named.count(n) > 1})
        if dupes:
            raise ValueError(f"{path}: duplicate columns {dupes}")
        keep = [(i, mapping[n]) for i, n in enumerate(names) if n]
        missing = set(mapping.values()) - {k for _, k in keep}
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}")
        trimmed = sum(1 for n in names if not n)
        records = []
        for row in reader:
            records.append(
                {k: (row[i].strip() if i < len(row) else "") for i, k in keep}
                | {"__extra": any(c.strip() for c in row[len(names) :])}
            )
    return records, trimmed


def _is_empty(rec: dict) -> bool:
    return not rec["__extra"] and not any(v for k, v in rec.items() if k != "__extra")


def _iso_date(value: str) -> str | None:
    try:
        return datetime.strptime(value, "%m/%d/%y").date().isoformat()
    except ValueError:
        return None


def _iso_local(value: str) -> str | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").isoformat(timespec="minutes")
    except ValueError:
        return None


def _number(value: str) -> float | None:
    try:
        n = float(value)
    except ValueError:
        return None
    return n if n == n and n not in (float("inf"), float("-inf")) else None


def _raw(rec: dict) -> dict[str, str]:
    return {k: v for k, v in rec.items() if k != "__extra"}


def parse_brick_oee(path: Path, period: Period) -> ParsedFile:
    records, trimmed_cols = _read(path, OEE_COLUMNS[period])
    out = ParsedFile(rows=[], source_rows=[], trimmed_columns=trimmed_cols)
    for line, rec in enumerate(records, start=1):
        reason = _check_oee(rec)
        if reason:
            out.rejected.append(Rejected(line, reason, _raw(rec)))
            continue
        row: dict[str, str | None] = {"shift_date": _iso_date(rec["shift_date"])}
        for col in (*OEE_FRACTIONS, *OEE_QUANTITIES):
            row[col] = rec[col]
        row["period"] = period
        out.rows.append(row)
        out.source_rows.append(line)
    return out


def _check_oee(rec: dict) -> str | None:
    if _is_empty(rec):
        return "empty_row"
    for col in ("shift_date", *OEE_FRACTIONS, *OEE_QUANTITIES):
        if not rec[col]:
            return f"missing_required:{col}"
    if _iso_date(rec["shift_date"]) is None:
        return "bad_date:shift_date"
    for col in (*OEE_FRACTIONS, *OEE_QUANTITIES):
        if _number(rec[col]) is None:
            return f"bad_number:{col}"
    for col in OEE_FRACTIONS:
        if not 0 <= _number(rec[col]) <= MAX_FRACTION:
            return f"out_of_range:{col}"
    for col in OEE_QUANTITIES:
        if _number(rec[col]) < 0:
            return f"out_of_range:{col}"
    return None


def parse_brick_downtime(path: Path, period: Period) -> ParsedFile:
    records, trimmed_cols = _read(path, DOWNTIME_COLUMNS[period])
    # Trailing fully empty rows are spreadsheet padding, not data.
    last = len(records)
    while last > 0 and _is_empty(records[last - 1]):
        last -= 1
    out = ParsedFile(
        rows=[], source_rows=[], trimmed_columns=trimmed_cols, trimmed_rows=len(records) - last
    )
    for line, rec in enumerate(records[:last], start=1):
        reason = _check_downtime(rec)
        if reason:
            out.rejected.append(Rejected(line, reason, _raw(rec)))
            continue
        row: dict[str, str | None] = {
            "shift_date": _iso_date(rec["shift_date"]),
            "product": rec["product"],
            "stop_group": rec["stop_group"],
            "stop": rec["stop"],
            "stop_type": rec["stop_type"],
        }
        for col in DOWNTIME_OPTIONAL_TEXT:
            row[col] = None if rec[col] in ("", "-") else rec[col]
        row["start_local"] = _iso_local(rec["start_local"])
        row["end_local"] = _iso_local(rec["end_local"])
        row["duration_min"] = rec["duration_min"]
        row["period"] = period
        out.rows.append(row)
        out.source_rows.append(line)
    return out


def _check_downtime(rec: dict) -> str | None:
    if _is_empty(rec):
        return "empty_row"
    for col in DOWNTIME_REQUIRED:
        if not rec[col]:
            return f"missing_required:{col}"
    if _iso_date(rec["shift_date"]) is None:
        return "bad_date:shift_date"
    start, end = _iso_local(rec["start_local"]), _iso_local(rec["end_local"])
    if start is None:
        return "bad_date:start_local"
    if end is None:
        return "bad_date:end_local"
    duration = _number(rec["duration_min"])
    if duration is None:
        return "bad_number:duration_min"
    if duration < 0:
        return "out_of_range:duration_min"
    if end < start:
        return "end_before_start"
    return None
