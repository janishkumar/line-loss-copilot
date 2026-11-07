"""Run the scripted safety eval: every scenario with guardrails (`guarded`) and against the
naive baseline (`naive`), on the test database. `make eval-safety` runs both.

Writes evals/results/safety_{mode}.json and .md: per scenario outcome, totals per category,
the run date, the git commit and a hash of the scenario list."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from evals.safety.scenarios import CATEGORIES, SCENARIOS, Scenario, scenario_set_hash
from evals.safety.world import World, agent_url_for

RESULTS = Path(__file__).resolve().parents[1] / "results"
REPO = Path(__file__).resolve().parents[2]
MODES = ("guarded", "naive")


def git_commit() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"], cwd=REPO, capture_output=True, text=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=REPO,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except OSError:
        return "unknown"
    return f"{sha}{' (uncommitted changes)' if dirty else ''}" if sha else "unknown"


def run_scenario(w: World, sc: Scenario) -> dict[str, Any]:
    s = w.scope(sc.name)
    error = None
    try:
        result = bool(sc.run(w, s))
    except Exception as e:  # recorded, never counted as a pass
        result, error = False, f"{type(e).__name__}: {e}"[:300]
    finally:
        w.clock.offset = timedelta(0)
        s.cleanup()
    return {
        "name": sc.name,
        "kind": sc.kind,
        "category": sc.category,
        "what": sc.what,
        "result": result,
        "error": error,
        "evidence": s.evidence(),
    }


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    attacks = [r for r in records if r["kind"] == "attack"]
    legit = [r for r in records if r["kind"] == "legit"]
    by_cat: dict[str, dict[str, int]] = {}
    for r in attacks:
        c = by_cat.setdefault(r["category"], {"n": 0, "landed": 0})
        c["n"] += 1
        c["landed"] += int(bool(r["result"]))
    return {
        "attacks": {
            "n": len(attacks),
            "landed": sum(bool(r["result"]) for r in attacks),
            "errors": sum(bool(r["error"]) for r in attacks),
        },
        "by_category": by_cat,
        "legit": {
            "n": len(legit),
            "completed": sum(bool(r["result"]) for r in legit),
            "errors": sum(bool(r["error"]) for r in legit),
        },
    }


def run_mode(db_url: str, agent_url: str, guarded: bool) -> dict[str, Any]:
    w = World(db_url, agent_url, guarded)
    try:
        records = [run_scenario(w, sc) for sc in SCENARIOS]
    finally:
        w.close()
    policy = (REPO / "config" / "policy.toml").read_bytes()
    return {
        "meta": {
            "mode": "guarded" if guarded else "naive",
            "date": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_commit": git_commit(),
            "scenario_set_hash": scenario_set_hash(),
            "scenarios": len(SCENARIOS),
            "database": urlparse(db_url).path.lstrip("/"),
            "policy_sha256": hashlib.sha256(policy).hexdigest()[:16],
            "run_id": w.run_id,
        },
        "summary": summarize(records),
        "scenarios": records,
    }


def _mark(r: dict[str, Any]) -> str:
    if r["error"]:
        return f"error: {r['error']}"
    if r["kind"] == "attack":
        return "landed" if r["result"] else "stopped"
    return "completed" if r["result"] else "did not complete"


def markdown(doc: dict[str, Any]) -> str:
    m, s = doc["meta"], doc["summary"]
    lines = [
        f"# Safety eval: {m['mode']}",
        "",
        f"- Date (UTC): {m['date']}",
        f"- Git commit: {m['git_commit']}",
        f"- Scenario set hash: `{m['scenario_set_hash']}`",
        f"- Unsafe writes landed: {s['attacks']['landed']} of {s['attacks']['n']} attacks",
        f"- Legitimate flows completed: {s['legit']['completed']} of {s['legit']['n']}",
        "",
        "| Category | Attacks | Landed |",
        "|---|---|---|",
    ]
    for cat, c in s["by_category"].items():
        lines.append(f"| {cat} | {c['n']} | {c['landed']} |")
    lines += ["", "| Scenario | Category | Outcome | What it tries |", "|---|---|---|---|"]
    for r in doc["scenarios"]:
        lines.append(f"| {r['name']} | {r['category']} | {_mark(r)} | {r.get('what', '')} |")
    lines += ["", "Categories:", ""]
    lines += [f"- {k}: {v}." for k, v in CATEGORIES.items()]
    return "\n".join(lines) + "\n"


def write(doc: dict[str, Any], out_dir: Path = RESULTS) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"safety_{doc['meta']['mode']}.json"
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n")
    path.with_suffix(".md").write_text(markdown(doc))
    return path


def _check_db(db_url: str) -> None:
    """Fail early with a clear message if the fixture data is not loaded."""
    import psycopg

    with psycopg.connect(db_url, autocommit=True) as conn:
        ok = conn.execute(
            "SELECT to_regclass('core.event') IS NOT NULL "
            "AND to_regclass('actions.proposal') IS NOT NULL"
        ).fetchone()[0]
        if not ok or not conn.execute("SELECT count(*) FROM core.event").fetchone()[0]:
            raise SystemExit(f"{urlparse(db_url).path} has no fixture data: run `make test-db`")


def main(argv: list[str] | None = None) -> int:
    from linecopilot.config import get_settings

    ap = argparse.ArgumentParser(description="Scripted safety eval (guarded and naive).")
    ap.add_argument("--mode", choices=(*MODES, "both"), default="both")
    ap.add_argument("--db-url", help="default: LINECOPILOT_TEST_DB_URL")
    args = ap.parse_args(argv)
    db_url = args.db_url or get_settings().test_database_url
    if not db_url:
        raise SystemExit("set LINECOPILOT_TEST_DB_URL (the eval runs on the test database)")
    _check_db(db_url)
    agent = agent_url_for(db_url)
    for mode in MODES if args.mode == "both" else (args.mode,):
        doc = run_mode(db_url, agent, guarded=mode == "guarded")
        path = write(doc)
        print(f"wrote {path}: {json.dumps(doc['summary']['attacks'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
