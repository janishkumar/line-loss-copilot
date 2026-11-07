"""Shortage eval (stage 4): the netting detector and the naive stock-below-demand rule, scored
against the planted ground truth in `synthetic.planted_shortage`.

Scored as precision and recall on (material, order) pairs and on materials, overall and per
planted kind. Decoys are negatives: a decoy is a case a naive rule flags that is not a shortage.
Both methods are scored on raw materials (sub-assemblies are never reported as shortages by
definition 10.2). Writes evals/results/shortages.json and .md. `make eval-shortages` runs it on
the main database (the answer key is owner-only, the agent role cannot read it)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.safety.run import git_commit
from linecopilot.supply.mrp import SupplyInput, detect, naive_rule

RESULTS = Path(__file__).resolve().parent / "results"
KINDS = ("plain", "timing", "level_two")

Pair = tuple[str, str]


def raw_only(pairs, kinds: dict[str, str]) -> set[Pair]:
    return {(m, o) for m, o in pairs if kinds.get(m, "raw") == "raw"}


def _prf(tp: int, fp: int, fn: int) -> dict[str, Any]:
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
    }


def _score_set(pred: set, truth: set, decoys: set) -> dict[str, Any]:
    """Overall: every prediction outside the truth is a false positive. A kind's row counts as
    false positives only the decoys of that kind, so it shows which cases fool a method."""
    return _prf(len(pred & truth), len(pred - truth), len(truth - pred))


def score(pred_pairs: set[Pair], truth_rows: list[dict]) -> dict[str, Any]:
    pred = set(pred_pairs)
    truth = {(r["material_id"], r["order_id"]) for r in truth_rows if not r["decoy"]}
    decoys = {(r["material_id"], r["order_id"]) for r in truth_rows if r["decoy"]}
    pred_m = {m for m, _ in pred}
    truth_m = {m for m, _ in truth}
    decoy_m = {m for m, _ in decoys} - truth_m

    def kind_sets(kind: str) -> tuple[set, set, set, set]:
        t = {
            (r["material_id"], r["order_id"])
            for r in truth_rows
            if not r["decoy"] and r["kind"] == kind
        }
        d = {
            (r["material_id"], r["order_id"])
            for r in truth_rows
            if r["decoy"] and r["kind"] == kind
        }
        return t, d, {m for m, _ in t}, {m for m, _ in d} - truth_m

    out: dict[str, Any] = {
        "pairs": {"overall": _score_set(pred, truth, decoys), "by_kind": {}},
        "materials": {"overall": _score_set(pred_m, truth_m, decoy_m), "by_kind": {}},
        "unplanted_flags": len(pred - truth - decoys),
        "decoys_flagged": len(pred & decoys),
        "decoys": len(decoys),
    }
    for kind in KINDS:
        t, d, tm, dm = kind_sets(kind)
        out["pairs"]["by_kind"][kind] = _prf(len(pred & t), len(pred & d), len(t - pred))
        out["materials"]["by_kind"][kind] = _prf(
            len(pred_m & tm), len(pred_m & dm), len(tm - pred_m)
        )
    return out


def evaluate(supply: SupplyInput, truth_rows: list[dict]) -> dict[str, Any]:
    found = {(f.material_id, f.order_id) for f in detect(supply)[0]}
    naive = raw_only(naive_rule(supply.orders, supply.bom, supply.stock), supply.kinds)
    return {
        "detector": score(found, truth_rows),
        "naive": score(naive, truth_rows),
        "flagged": {"detector": len(found), "naive": len(naive)},
    }


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def _rows(name: str, block: dict[str, Any]) -> list[str]:
    rows = [("all", block["overall"]), *((k, block["by_kind"][k]) for k in KINDS)]
    return [
        f"| {name} | {label} | {r['tp']} | {r['fp']} | {r['fn']} | "
        f"{_fmt(r['precision'])} | {_fmt(r['recall'])} |"
        for label, r in rows
    ]


def markdown(doc: dict[str, Any]) -> str:
    m = doc["meta"]
    L = [
        "# Shortage eval (synthetic data)",
        "",
        f"- Synthetic data: generation {m['generation_id']}, seed {m['seed']}, "
        f"content sha256 `{m['content_sha256']}`",
        f"- Date (UTC): {m['date']}",
        f"- Git commit: {m['git_commit']}",
        f"- {m['orders']} orders, {m['planted']} planted shortages, {m['decoys']} decoys "
        "(counted as negatives)",
        "",
        "The detector and the generator share the netting definition (need date, allocation "
        "order, receipts at or before the need time, sub-assembly netting before raw "
        "explosion), so a perfect detector score shows the code implements the definition, "
        "not real-world accuracy. The naive rule flags a material when on hand is below its "
        "total gross requirement and flags every order that uses it. Both are scored on raw "
        "materials. The data is synthetic; planted shortages test the software.",
        "",
        "Per-kind rows: false positives are the decoys of that kind; the `all` row counts every "
        "prediction outside the planted shortages as a false positive.",
        "",
    ]
    for title, key in (("(material, order) pairs", "pairs"), ("Materials", "materials")):
        L += [
            f"## {title}",
            "",
            "| Method | Kind | TP | FP | FN | Precision | Recall |",
            "|---|---|---|---|---|---|---|",
            *_rows("netting detector", doc["detector"][key]),
            *_rows("naive rule", doc["naive"][key]),
            "",
        ]
    d, n = doc["detector"], doc["naive"]
    L += [
        f"Flags outside the planted cases: detector {d['unplanted_flags']}, naive rule "
        f"{n['unplanted_flags']}. Decoys flagged: detector {d['decoys_flagged']} of "
        f"{d['decoys']}, naive rule {n['decoys_flagged']} of {n['decoys']}.",
    ]
    return "\n".join(L) + "\n"


def run(conn) -> dict[str, Any]:
    from linecopilot.supply.load import load_supply

    supply = load_supply(conn)
    if supply.generation_id is None:
        raise SystemExit("no synthetic data: run `make synth`")
    cur = conn.execute("SELECT material_id, order_id, kind, decoy FROM synthetic.planted_shortage")
    truth = [
        {"material_id": a, "order_id": b, "kind": c, "decoy": d} for a, b, c, d in cur.fetchall()
    ]
    res = evaluate(supply, truth)
    return {
        "meta": {
            "generation_id": supply.generation_id,
            "seed": supply.seed,
            "content_sha256": supply.content_sha256,
            "date": datetime.now(UTC).isoformat(timespec="seconds"),
            "git_commit": git_commit(),
            "orders": len(supply.orders),
            "planted": sum(not r["decoy"] for r in truth),
            "decoys": sum(r["decoy"] for r in truth),
            "synthetic": True,
        },
        **res,
    }


def write(doc: dict[str, Any], out_dir: Path = RESULTS) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "shortages.json"
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    path.with_suffix(".md").write_text(markdown(doc))
    return path


def main(argv: list[str] | None = None) -> int:
    import psycopg

    from linecopilot.config import get_settings

    ap = argparse.ArgumentParser(
        description="Shortage detector and naive rule against planted truth."
    )
    ap.add_argument("--db-url", help="default: the main database (owner role)")
    args = ap.parse_args(argv)
    with psycopg.connect(args.db_url or get_settings().database_url) as conn:
        doc = run(conn)
    path = write(doc)
    print(f"wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
