"""ONNX export, parity and CPU latency per VisA subset (stage 5, task 4).

Phase 1, per subset: export data/models/vision/<subset>.onnx from the trained memory bank,
check parity with the PyTorch scorer on real test-split images (10 per subset, 5 normal and 5
anomalous; nothing is tuned on them) and time preprocessing (decode, resize, normalise), which
is outside the graph and reported separately.

Phase 2, latency: onnxruntime CPUExecutionProvider at batch 1, intra-op threads 1 and 4, and
PyTorch CPU with the same protocol for context. To keep background load from landing on one
subset or one runtime, the work is split into rounds; each round runs every subset x
{onnx-1, onnx-4, torch-1, torch-4} block once, in a seeded shuffled order. A block is 20
warm-up runs (excluded) then 40 timed runs. Before each block the 1-minute load average must be
below a limit; otherwise the run waits and retries, and if the machine stays busy it stops and
flags the result incomplete. The load, date and commit of every block are stored with the
block. Reported latency is the median of the per-round medians, with their min and max.

A rerun resumes: finished blocks (same model hash) are kept, with their own provenance.
Writes evals/results/vision_latency.json and .md. `make export-vision` runs it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import statistics
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.safety.run import git_commit
from linecopilot.vision import export as X
from linecopilot.vision.data import SUBSETS, load_split, val_test_split

RESULTS = Path(__file__).resolve().parent / "results"
CONFIGS = ("onnx-1", "onnx-4", "torch-1", "torch-4")
ROUNDS = 5
RUNS = 40
WARMUP = 20
LOAD_LIMIT = 2.0  # 1-minute load average; the machine has 10 cores
PARITY_PER_LABEL = 5
SEED = 0
RETRIES = 40
RETRY_DELAY_S = 30


def file_sha(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def schedule(subsets: list[str], rounds: int, seed: int) -> list[tuple[int, str, str]]:
    plan: list[tuple[int, str, str]] = []
    for r in range(rounds):
        blocks = [(r, s, c) for s in subsets for c in CONFIGS]
        random.Random(seed * 1000 + r).shuffle(blocks)
        plan += blocks
    return plan


def wait_quiet(
    limit: float,
    load_fn: Callable[[], tuple[float, float, float]] = os.getloadavg,
    sleep: Callable[[float], None] = time.sleep,
    retries: int = RETRIES,
    delay: float = RETRY_DELAY_S,
) -> float | None:
    """The 1-minute load once it is below `limit`, or None if it never is within the retries."""
    for i in range(retries):
        load = load_fn()[0]
        if load < limit:
            return load
        if i < retries - 1:
            sleep(delay)
    return None


def aggregate(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    p50 = [b["p50_ms"] for b in blocks]
    return {
        "p50_ms": statistics.median(p50),
        "p50_min_ms": min(p50),
        "p50_max_ms": max(p50),
        "p95_ms": statistics.median(b["p95_ms"] for b in blocks),
        "rounds": len(blocks),
        "load_max": max(b["load"] for b in blocks),
    }


def run_blocks(
    doc: dict[str, Any],
    plan: list[tuple[int, str, str]],
    measure: Callable[[str, str], dict[str, Any]],
    *,
    limit: float,
    commit: str,
    today: str,
    save: Callable[[], None],
    load_fn: Callable[[], tuple[float, float, float]] = os.getloadavg,
    sleep: Callable[[float], None] = time.sleep,
    retries: int = RETRIES,
) -> bool:
    """Run the blocks not yet done. Returns False (and flags the doc) if load stays high."""
    blocks = doc.setdefault("blocks", {})
    for rnd, sub, cfg in plan:
        if any(r["round"] == rnd for r in blocks.get(sub, {}).get(cfg, [])):
            continue
        load = wait_quiet(limit, load_fn, sleep, retries)
        if load is None:
            doc["incomplete"] = True
            return False
        res = measure(sub, cfg)
        recs = blocks.setdefault(sub, {}).setdefault(cfg, [])
        recs.append(
            {"round": rnd, "p50_ms": res["p50_ms"], "p95_ms": res["p95_ms"], "load": load,
             "date": today, "commit": commit}
        )  # fmt: skip
        recs.sort(key=lambda r: r["round"])
        save()
    doc["incomplete"] = False
    return True


def _pp(a: dict[str, Any]) -> str:
    return f"{a['p50_ms']:.1f} ({a['p50_min_ms']:.1f} to {a['p50_max_ms']:.1f})"


def summary(doc: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Per-subset aggregates per config, and pooled over subsets (identical graph cost)."""
    per: dict[str, dict[str, Any]] = {}
    pooled: dict[str, list[dict[str, Any]]] = {c: [] for c in CONFIGS}
    for sub, cfgs in doc.get("blocks", {}).items():
        per[sub] = {c: aggregate(r) for c, r in cfgs.items() if r}
        for c, r in cfgs.items():
            pooled[c] += r
    return per, {c: aggregate(r) for c, r in pooled.items() if r}


def markdown(doc: dict[str, Any]) -> str:
    m, prot = doc["machine"], doc["protocol"]
    per, pooled = summary(doc)
    every = [b for cfgs in doc.get("blocks", {}).values() for r in cfgs.values() for b in r]
    L = [
        "# Vision: ONNX export and CPU latency",
        "",
        f"Machine: {m['cpu']}, {m['cpu_count']} cores ({m['platform']}); onnxruntime "
        f"{m['onnxruntime']}, torch {m['torch']}, opset {m['opset']}; CPUExecutionProvider, "
        "batch 1. This is the only machine measured.",
        "",
    ]
    if every:
        dates = sorted({b["date"] for b in every})
        commits = sorted({b["commit"] for b in every})
        loads = [b["load"] for b in every]
        L += [
            f"Provenance: {len(every)} blocks measured on {', '.join(dates)} at commit(s) "
            f"{', '.join(commits)}; 1-minute load average before each block "
            f"{min(loads):.2f} to {max(loads):.2f} (median {statistics.median(loads):.2f}), "
            f"limit {prot['load_limit']}. Each block's own date, commit and load are in "
            "`vision_latency.json`.",
            "",
        ]
    if doc.get("incomplete"):
        L += ["**Incomplete: the machine stayed busy and the run stopped; rerun to finish.**", ""]
    L += [
        f"Protocol: {prot['rounds']} rounds; each round runs every subset x {{ONNX 1 thread, "
        "ONNX 4 threads, PyTorch 1 thread, PyTorch 4 threads}} once in a seeded shuffled order, "
        f"so load drifts across all of them equally. Each block is {prot['warmup']} warm-up "
        f"runs (excluded) then {prot['runs']} timed runs on one fixed random input (the graph's "
        "cost does not depend on pixel values). Figures are the median of the per-round p50s in "
        "ms, with the range of those round medians in brackets. The graph takes the "
        "preprocessed 1 x 3 x 224 x 224 tensor and returns (score, map); preprocessing is "
        "outside the graph and timed separately. The PyTorch rows run `PatchCore.score`, for "
        "context.",
        "",
        "All six graphs have the same shape and cost (same 16384 x 1024 bank, same input), so "
        "differences between subsets are noise, not model effects. The pooled row is the one "
        "number to quote.",
        "",
        "| Subset | ONNX 1 thread | ONNX 4 threads | PyTorch 1 thread | PyTorch 4 threads |",
        "|---|---|---|---|---|",
    ]
    for sub, a in per.items():
        L.append(f"| {sub} | " + " | ".join(_pp(a[c]) if c in a else "n/a" for c in CONFIGS) + " |")
    if pooled:
        L.append(
            "| **all subsets** | "
            + " | ".join(_pp(pooled[c]) if c in pooled else "n/a" for c in CONFIGS)
            + " |"
        )
    L += [
        "",
        "p95 per block, median over rounds and subsets: "
        + ", ".join(f"{c} {pooled[c]['p95_ms']:.1f}" for c in CONFIGS if c in pooled)
        + ".",
        "",
        "| Subset | Model MB | of which memory bank | of which backbone | Max rel. score diff "
        "| Max abs map diff | Preprocess p50 / p95 ms | Exported |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s, r in doc["subsets"].items():
        L.append(
            f"| {s} | {r['model_mb']:.1f} | {r['bank_mb']:.1f} | {r['backbone_mb']:.1f} "
            f"| {r['parity']['max_rel_score_diff']:.2e} | {r['parity']['max_abs_map_diff']:.2e} "
            f"| {r['preprocess']['p50_ms']:.1f} / {r['preprocess']['p95_ms']:.1f} "
            f"| {r['date']} `{r['commit']}` load {r['load']:.2f} |"
        )
    L += [
        "",
        f"Parity: {PARITY_PER_LABEL * 2} real test-split images per subset; the export fails if "
        f"the score differs by more than {X.PARITY_TOL:.0e} relative or the map by more than "
        f"{X.MAP_TOL:.0e} absolute. The PyTorch scorer uses `torch.cdist`; the graph uses the "
        "exact matmul form of the distance and a fixed matrix for the channel reduction, so "
        "differences are float rounding only.",
        "",
        "Not demonstrated: suitability for a small plant computer. Only an Apple M4 laptop was "
        "measured. No x86 or older or low-power CPU, no RAM use, no quantisation and no smaller "
        "memory bank were tried; each model file is about 173 MB (six subsets, about 1 GB).",
        "",
    ]
    return "\n".join(L)


def _write(doc: dict[str, Any]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "vision_latency.json"
    out.write_text(json.dumps(doc, indent=2) + "\n")
    out.with_suffix(".md").write_text(markdown(doc))


def main(argv: list[str] | None = None) -> int:
    from linecopilot.config import get_settings
    from linecopilot.vision.patchcore import PatchCore, default_backbone
    from linecopilot.vision.preprocess import preprocess_image

    ap = argparse.ArgumentParser(description="ONNX export, parity and CPU latency.")
    ap.add_argument("--subsets", nargs="*", default=list(SUBSETS))
    ap.add_argument("--rounds", type=int, default=ROUNDS)
    ap.add_argument("--runs", type=int, default=RUNS)
    ap.add_argument("--warmup", type=int, default=WARMUP)
    ap.add_argument("--load-limit", type=float, default=LOAD_LIMIT)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    settings = get_settings()
    root = settings.data_dir / "visa"
    models = settings.data_dir / "models" / "vision"
    out = RESULTS / "vision_latency.json"
    doc: dict[str, Any] = {"subsets": {}, "blocks": {}}
    if out.exists() and not args.force:
        doc = json.loads(out.read_text())
    machine = X.machine_info()
    protocol = {
        "rounds": args.rounds, "runs": args.runs, "warmup": args.warmup,
        "load_limit": args.load_limit, "seed": SEED,
    }  # fmt: skip
    # a different machine, runtime or timing protocol invalidates the timings (not the exports)
    stale = doc.get("machine") not in (None, machine) or doc.get("protocol") not in (None, protocol)
    if stale:
        doc["blocks"] = {}
    doc.update(machine=machine, protocol=protocol)
    commit, today = git_commit(), datetime.now(UTC).date().isoformat()
    backbone = default_backbone()
    fitted: dict[str, Any] = {}

    def model_for(sub: str):
        if sub not in fitted:
            fitted[sub] = PatchCore.load(models / f"{sub}.pt", backbone=backbone)
        return fitted[sub]

    for sub in args.subsets:
        pt, onnx_path = models / f"{sub}.pt", models / f"{sub}.onnx"
        sha = file_sha(pt)
        prev = doc["subsets"].get(sub)
        if prev and prev["model_sha256"] == sha and onnx_path.exists():
            print(f"{sub}: export unchanged, kept", flush=True)
            continue
        print(sub, flush=True)
        doc["blocks"].pop(sub, None)
        model = model_for(sub)
        X.export_onnx(model, onnx_path)
        _, test = val_test_split(load_split(root, sub, "test"))
        pick = [s for s in test if s.label == 0][:PARITY_PER_LABEL]
        pick += [s for s in test if s.label == 1][:PARITY_PER_LABEL]
        parity = X.parity(model, onnx_path, [preprocess_image(s.image_path) for s in pick])
        print(f"  parity {parity}", flush=True)
        total_mb = onnx_path.stat().st_size / 1e6
        bank_mb = model.bank.numel() * 4 / 1e6
        doc["subsets"][sub] = {
            "model_sha256": sha,
            "model_mb": total_mb,
            "bank_size": int(model.bank.shape[0]),
            "bank_mb": bank_mb,
            "backbone_mb": total_mb - bank_mb,
            "parity": parity,
            "parity_images": [s.image_id for s in pick],
            "preprocess": X.benchmark_preprocess([s.image_path for s in pick]),
            "date": today,
            "commit": commit,
            "load": round(os.getloadavg()[0], 2),
        }
        _write(doc)

    def measure(sub: str, cfg: str) -> dict[str, Any]:
        kind, threads = cfg.split("-")
        if kind == "onnx":
            return X.benchmark(
                models / f"{sub}.onnx", int(threads), runs=args.runs, warmup=args.warmup
            )
        return X.benchmark_torch(model_for(sub), int(threads), runs=args.runs, warmup=args.warmup)

    plan = schedule(args.subsets, args.rounds, SEED)
    done = run_blocks(
        doc, plan, measure, limit=args.load_limit, commit=commit, today=today,
        save=lambda: _write(doc),
    )  # fmt: skip
    _write(doc)
    if not done:
        print(
            f"load average stayed above {args.load_limit}; stopped early, result is incomplete",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
