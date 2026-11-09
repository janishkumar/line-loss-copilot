"""ONNX export, parity and CPU latency per VisA subset (stage 5, task 4).

For each subset: export data/models/vision/<subset>.onnx from the trained memory bank, check
parity with the PyTorch scorer on real test-split images (10 per subset, 5 normal and 5
anomalous; nothing is tuned on them), then measure latency with onnxruntime
CPUExecutionProvider at batch 1 (20 warm-up runs excluded, 200 timed runs, intra-op threads 1
and 4) and, for context, PyTorch CPU with the same protocol. Preprocessing (decode, resize,
normalise) is timed separately and is not part of the graph or of the ONNX numbers.

Results are written after every subset and a rerun skips subsets whose model file is unchanged,
so an interrupted run resumes. Writes evals/results/vision_latency.json and .md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.safety.run import git_commit
from linecopilot.vision import export as X
from linecopilot.vision.data import SUBSETS, load_split, val_test_split

RESULTS = Path(__file__).resolve().parent / "results"
THREADS = (1, 4)
RUNS = 200
WARMUP = 20
PARITY_PER_LABEL = 5


def file_sha(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def markdown(doc: dict[str, Any]) -> str:
    m = doc["machine"]
    L = [
        "# Vision: ONNX export and CPU latency",
        "",
        f"Date: {doc['date']}; commit `{doc['commit']}`.",
        "",
        f"Machine: {m['cpu']}, {m['cpu_count']} cores; onnxruntime {m['onnxruntime']}, "
        f"torch {m['torch']}, opset {m['opset']}; CPUExecutionProvider, batch 1.",
        "",
        f"System load average (1 min) at the start of the run: {doc.get('load_average_1m')}. "
        "Latency was measured on a laptop in normal use, so expect run-to-run noise of tens of "
        "percent; more threads did not help much because one image is a small workload.",
        "",
        "Protocol: 20 warm-up runs excluded, 200 timed runs, p50 and p95 in ms. The graph takes "
        "the preprocessed 1 x 3 x 224 x 224 tensor and returns (score, map); preprocessing is "
        "outside the graph and timed separately. The PyTorch rows run `PatchCore.score` with "
        "the same protocol, for context.",
        "",
        "| Subset | Model MB | Max rel. score diff | Max abs map diff | ONNX 1 thread p50 / p95 | "
        "ONNX 4 threads p50 / p95 | PyTorch 1 thread p50 / p95 | PyTorch 4 threads p50 / p95 | "
        "Preprocess p50 / p95 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    def pp(d: dict[str, Any]) -> str:
        return f"{d['p50_ms']:.1f} / {d['p95_ms']:.1f}"

    for s, r in doc["subsets"].items():
        o = {x["threads"]: x for x in r["onnx"]}
        t = {x["threads"]: x for x in r["torch"]}
        L.append(
            f"| {s} | {r['model_mb']:.1f} | {r['parity']['max_rel_score_diff']:.2e} "
            f"| {r['parity']['max_abs_map_diff']:.2e} | {pp(o[1])} | {pp(o[4])} "
            f"| {pp(t[1])} | {pp(t[4])} | {pp(r['preprocess'])} |"
        )
    L += [
        "",
        f"Parity: {PARITY_PER_LABEL * 2} real test-split images per subset, tolerance "
        f"{X.PARITY_TOL:.0e} relative on the score; the export fails if it is exceeded. The "
        "PyTorch scorer uses `torch.cdist`; the graph uses the exact matmul form of the "
        "distance and a fixed matrix for the channel reduction, so differences are float "
        "rounding only.",
        "",
    ]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    from linecopilot.config import get_settings
    from linecopilot.vision.patchcore import PatchCore
    from linecopilot.vision.preprocess import preprocess_image

    ap = argparse.ArgumentParser(description="ONNX export, parity and CPU latency.")
    ap.add_argument("--subsets", nargs="*", default=list(SUBSETS))
    ap.add_argument("--runs", type=int, default=RUNS)
    ap.add_argument("--warmup", type=int, default=WARMUP)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    settings = get_settings()
    root = settings.data_dir / "visa"
    models = settings.data_dir / "models" / "vision"
    out = RESULTS / "vision_latency.json"
    doc: dict[str, Any] = {"subsets": {}}
    if out.exists() and not args.force:
        doc = json.loads(out.read_text())
    machine = X.machine_info()
    if doc.get("machine") not in (None, machine):
        doc["subsets"] = {}  # measured on another machine or runtime: start again
    doc.update(machine=machine, date=datetime.now(UTC).date().isoformat(), commit=git_commit())
    doc["load_average_1m"] = round(os.getloadavg()[0], 2)  # background load, a noise caveat
    doc["protocol"] = {"runs": args.runs, "warmup": args.warmup, "threads": list(THREADS)}
    for sub in args.subsets:
        pt = models / f"{sub}.pt"
        sha = file_sha(pt)
        prev = doc["subsets"].get(sub)
        onnx_path = models / f"{sub}.onnx"
        if (
            prev
            and prev["model_sha256"] == sha
            and prev["protocol"] == doc["protocol"]
            and onnx_path.exists()
        ):
            print(f"{sub}: unchanged, skipped", flush=True)
            continue
        print(sub, flush=True)
        model = PatchCore.load(pt)
        X.export_onnx(model, onnx_path)
        _, test = val_test_split(load_split(root, sub, "test"))
        pick = [s for s in test if s.label == 0][:PARITY_PER_LABEL]
        pick += [s for s in test if s.label == 1][:PARITY_PER_LABEL]
        parity = X.parity(model, onnx_path, [preprocess_image(s.image_path) for s in pick])
        print(f"  parity {parity}", flush=True)
        onnx_rows = [X.benchmark(onnx_path, t, runs=args.runs, warmup=args.warmup) for t in THREADS]
        torch_rows = [
            X.benchmark_torch(model, t, runs=args.runs, warmup=args.warmup) for t in THREADS
        ]
        pre = X.benchmark_preprocess([s.image_path for s in pick])
        doc["subsets"][sub] = {
            "model_sha256": sha,
            "protocol": doc["protocol"],
            "model_mb": onnx_path.stat().st_size / 1e6,
            "bank_size": int(model.bank.shape[0]),
            "parity": parity,
            "parity_images": [s.image_id for s in pick],
            "onnx": onnx_rows,
            "torch": torch_rows,
            "preprocess": pre,
        }
        print(f"  onnx p50 {[round(r['p50_ms'], 1) for r in onnx_rows]} ms", flush=True)
        RESULTS.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, indent=2) + "\n")
        out.with_suffix(".md").write_text(markdown(doc))
    out.write_text(json.dumps(doc, indent=2) + "\n")
    out.with_suffix(".md").write_text(markdown(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
