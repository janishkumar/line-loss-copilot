"""Load parsed source files into the raw schema with row-level lineage.

Every data row carries `load_id`, `source_file` and `source_row` (the 1-based data line of the
file, header excluded). Re-loading a file replaces that file's earlier rows (data and rejects)
inside one transaction that commits per file, so running the load twice leaves identical row
counts and a failure on one file keeps the files already loaded. Past `raw.load` entries are
kept as a history of runs.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

from linecopilot.config import get_settings
from linecopilot.db import connect
from linecopilot.ingest.brick import parse_brick_downtime, parse_brick_oee
from linecopilot.ingest.contracts import ParsedFile
from linecopilot.ingest.piade import OUTPUT_COLUMNS, parse_piade_raw

SCHEMA_FILE = Path(__file__).resolve().parents[3] / "sql" / "raw_schema.sql"
PIADE_COLUMNS = (*OUTPUT_COLUMNS, "start_raw", "end_raw")


@dataclass(frozen=True)
class FileSpec:
    dataset: str
    filename: str
    table: str
    parse: Callable[[Path], ParsedFile]


FILES: tuple[FileSpec, ...] = (
    FileSpec("brick", "OEEdataset.csv", "brick_oee", lambda p: parse_brick_oee(p, "before")),
    FileSpec(
        "brick", "OEEdataset_afterLSS.csv", "brick_oee", lambda p: parse_brick_oee(p, "after")
    ),
    FileSpec(
        "brick",
        "DowntimeDataset.csv",
        "brick_downtime",
        lambda p: parse_brick_downtime(p, "before"),
    ),
    FileSpec(
        "brick",
        "DowntimeDataset_afterLSS.csv",
        "brick_downtime",
        lambda p: parse_brick_downtime(p, "after"),
    ),
    FileSpec("piade", "raw_data.csv", "piade_raw", parse_piade_raw),
)


@dataclass(frozen=True)
class LoadSummary:
    load_id: int
    dataset: str
    filename: str
    table: str
    rows_read: int
    rows_accepted: int
    rows_rejected: int
    seconds: float


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_FILE.read_text())
    conn.commit()


class ChecksumMismatch(RuntimeError):
    pass


def _sha256(path: Path, manifest_dir: Path) -> str:
    """Hash the file being parsed; refuse it if the manifest records a different hash."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    manifest = manifest_dir / "checksums.json"
    if manifest.exists():
        for entry in json.loads(manifest.read_text()).get("files", []):
            expected = entry.get("sha256")
            if entry.get("filename") == path.name and expected and expected != actual:
                raise ChecksumMismatch(
                    f"{path}: sha256 {actual} != manifest {expected}; nothing loaded"
                )
    return actual


def _rows_for_copy(parsed: ParsedFile, columns: tuple[str, ...]):
    """Yield (value tuple, source_row) per accepted row, values in `columns` order."""
    if parsed.frame is not None:
        frame = parsed.frame
        missing = [c for c in columns if c not in frame.columns]
        if missing:
            raise ValueError(f"parser output lacks schema columns {missing}")
        for source_row, *values in frame[list(columns)].itertuples(name=None):
            yield [None if v is None or v != v else v for v in values], int(source_row)
    else:
        missing = sorted({c for row in parsed.rows for c in columns if c not in row})
        if missing:
            raise ValueError(f"parser output lacks schema columns {missing}")
        for row, source_row in zip(parsed.rows, parsed.source_rows, strict=True):
            yield [row.get(c) for c in columns], source_row


def _table_columns(conn: psycopg.Connection, table: str) -> tuple[str, ...]:
    lineage = {"load_id", "source_file", "source_row"}
    cur = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'raw' AND table_name = %s ORDER BY ordinal_position",
        (table,),
    )
    return tuple(r[0] for r in cur.fetchall() if r[0] not in lineage)


def load_file(conn: psycopg.Connection, spec: FileSpec, data_dir: Path) -> LoadSummary:
    path = data_dir / "raw" / spec.dataset / spec.filename
    source_file = f"{spec.dataset}/{spec.filename}"
    started = time.monotonic()
    sha = _sha256(path, data_dir)
    parsed = spec.parse(path)
    columns = _table_columns(conn, spec.table)
    accepted = len(parsed.source_rows)
    rejected = len(parsed.rejected)
    table = sql.Identifier("raw", spec.table)
    conn.commit()  # close the implicit transaction opened by the column lookup
    with conn.transaction():  # commits on exit: each file is its own transaction
        conn.execute(sql.SQL("DELETE FROM {} WHERE source_file = %s").format(table), (source_file,))
        conn.execute("DELETE FROM raw.rejected WHERE source_file = %s", (source_file,))
        load_id = conn.execute(
            "INSERT INTO raw.load (dataset, filename, sha256, rows_read, rows_accepted, "
            "rows_rejected, trimmed_columns, trimmed_rows) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING load_id",
            (
                spec.dataset,
                spec.filename,
                sha,
                accepted + rejected,
                accepted,
                rejected,
                parsed.trimmed_columns,
                parsed.trimmed_rows,
            ),
        ).fetchone()[0]
        copy = sql.SQL("COPY {} ({}) FROM STDIN").format(
            table,
            sql.SQL(", ").join(
                sql.Identifier(c) for c in (*columns, "load_id", "source_file", "source_row")
            ),
        )
        with conn.cursor() as cur, cur.copy(copy) as cp:
            for values, source_row in _rows_for_copy(parsed, columns):
                cp.write_row([*values, load_id, source_file, source_row])
        if rejected:
            with (
                conn.cursor() as cur,
                cur.copy(
                    "COPY raw.rejected (load_id, source_file, source_row, reason, raw) FROM STDIN"
                ) as cp,
            ):
                for rej in parsed.rejected:
                    cp.write_row(
                        [load_id, source_file, rej.source_row, rej.reason, json.dumps(rej.raw)]
                    )
    return LoadSummary(
        load_id,
        spec.dataset,
        spec.filename,
        spec.table,
        accepted + rejected,
        accepted,
        rejected,
        time.monotonic() - started,
    )


def load_all(conn: psycopg.Connection, data_dir: Path) -> list[LoadSummary]:
    init_schema(conn)
    return [load_file(conn, spec, data_dir) for spec in FILES]


def main() -> int:
    settings = get_settings()
    started = time.monotonic()
    with connect(settings.database_url) as conn:
        summaries = load_all(conn, settings.data_dir)
        for s in summaries:
            print(
                f"{s.dataset}/{s.filename} -> raw.{s.table}: read {s.rows_read}, "
                f"accepted {s.rows_accepted}, rejected {s.rows_rejected} ({s.seconds:.1f}s)"
            )
    print(f"done in {time.monotonic() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
