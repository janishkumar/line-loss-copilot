"""Vision eval (stage 5): PatchCore per VisA subset on the official 1cls test split.

The official test images are split once (stratified, seed 0) into validation, used for the
threshold and review band only, and test, used for every reported number. Image AUROC, pixel
AUROC and pixel AUPRO are reported on the test half with bootstrap 95% intervals (1000
resamples over images, seed 0) and, for comparability with published work, on the full official
test set. Before any scoring, the train set is checked against validation and test by path and
by content hash. Per-image scores and maps are cached in data/cache/vision (gitignored), keyed
by the model file's hash. Writes evals/results/vision.json and .md and
data/models/vision/thresholds.json. `make eval-vision` runs it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from evals.safety.run import git_commit
from linecopilot.vision import metrics as M
from linecopilot.vision import threshold as T
from linecopilot.vision.data import SUBSETS, Sample, load_split, overlap, val_test_split

RESULTS = Path(__file__).resolve().parent / "results"
SPLIT_SEED = 0
BOOTSTRAP_N = 1000
REVIEW_SHARE = 0.10
DEFAULT_P = T.DEFAULT_P
FPR_LIMIT = 0.3

ASSUMPTIONS = [
    "Costs are relative. A false reject costs 1 and an escaped defect costs r = 20; defects are "
    "assumed to be p = 2% of items. Both are assumptions, not plant figures; the sensitivity "
    "grid covers r = 5 to 100 and p = 0.5% to 5%.",
    "Rates are per class (share of normals rejected, share of defects passed) and are weighted "
    "by p, so the threshold does not depend on VisA's test mix (two thirds anomalous). Cost per "
    "1000 items is the weighted cost times 1000.",
    "Validation and test are 50/50 halves of the official test split, so each half holds only "
    "25 to 50 normal and 50 anomalous images: intervals are wide and thresholds are noisy.",
    "Images are VisA product photos, not images from the plant; their link to a line is "
    "simulated elsewhere in this project and labelled.",
    "The review band assumes a reviewer decides every image in it correctly and ignores review "
    "effort. Its width is set on validation so that 10% of items, weighted by p, are routed to "
    "review.",
    "Pixel metrics are computed on the 224 x 224 maps and masks, not at the original resolution.",
]

PUBLISHED = {
    "primary": {
        "source": "Zou et al., SPot-the-Difference self-supervised pre-training for anomaly "
        "detection and segmentation (the VisA paper)",
        "url": "https://arxiv.org/html/2207.14315",
        "table": "Table 6, '1-class performance evaluation on VisA and MVTec-AD with "
        "PatchCore', backbone Wide ResNet50, row 'Sup. pre-train', VisA columns",
        "average_image_auroc": 0.924,
        "average_pixel_auroc": 0.984,
        "scope": "average over VisA's 12 classes, one model per class; the table does not "
        "state the input resolution or AUPRO",
    },
    "secondary": {
        "source": "SoftPatch+ (Fully unsupervised anomaly detection with noisy data)",
        "url": "https://arxiv.org/html/2412.20870",
        "table": "Table 3 (image AUROC) and Table 4 (pixel AUROC), 'upperbound' column of the "
        "'No Overlap' setting, which is PatchCore trained on clean normal images, Wide-ResNet50, "
        "10% coreset",
        "caveat": "The test set is that paper's 8%-noise protocol variant, not necessarily the "
        "official 1cls test split, and its VisA input resolution is not stated (it states 256 "
        "resize with 224 centre crop for MVTec AD only).",
        "per_subset": {
            "cashew": {"image_auroc": 0.989, "pixel_auroc": 0.985},
            "chewinggum": {"image_auroc": 0.991, "pixel_auroc": 0.994},
            "fryum": {"image_auroc": 0.954, "pixel_auroc": 0.925},
            "pipe_fryum": {"image_auroc": 0.997, "pixel_auroc": 0.989},
            "macaroni1": {"image_auroc": 0.975, "pixel_auroc": 0.999},
            "macaroni2": {"image_auroc": 0.767, "pixel_auroc": 0.981},
        },
    },
    "matches_our_setup": "partly",
    "setup_note": "Ours: wide_resnet50_2 IMAGENET1K_V1, whole image resized to 224 x 224 without "
    "cropping, layers 2 and 3, coreset up to 10% or 16,384 patches, one model per subset, "
    "official 1cls train. Backbone and one-class protocol match the primary source, whose "
    "figures are averages over 12 classes while ours are averages over the six food subsets, so "
    "the two averages cover different sets of classes. No source found reports PatchCore AUPRO "
    "per class on VisA.",
}

# First run of this eval, before the preprocessing change: shorter side resized to 256 and the
# centre 224 x 224 kept. On macaroni2, 18 of the 100 official-test anomalous images have their
# whole defect outside that crop and 24 have under half of it inside (checked on the original
# masks); other subsets have 0 or 1. Values are from the first run (test split, then the full
# official test split).
FIRST_RUN_CENTRE_CROP = {
    "note": "First run used a resize to 256 and a centre crop to 224, which cut the defect "
    "entirely out of the image for 18 of 100 macaroni2 anomalies (24 had under half inside). "
    "The preprocessing now resizes the whole image to 224 x 224 and the models were refitted. "
    "Image AUROC did not improve on the macaroni subsets (macaroni1 and macaroni2 are lower); "
    "this was not investigated further, and squeezing a wide image into a square, which makes "
    "small defects smaller, is one possible factor.",
    "macaroni2_defects_fully_outside_crop": "18 of 100",
    "per_subset": {
        "cashew": {"test": [0.983, 0.990, 0.922], "official": [0.981, 0.991, 0.917]},
        "chewinggum": {"test": [0.996, 0.988, 0.884], "official": [0.991, 0.983, 0.826]},
        "fryum": {"test": [0.947, 0.926, 0.788], "official": [0.934, 0.932, 0.793]},
        "pipe_fryum": {"test": [0.995, 0.992, 0.912], "official": [0.993, 0.992, 0.924]},
        "macaroni1": {"test": [0.965, 0.989, 0.949], "official": [0.965, 0.991, 0.954]},
        "macaroni2": {"test": [0.695, 0.956, 0.847], "official": [0.725, 0.945, 0.813]},
    },
    "columns": "image AUROC, pixel AUROC, pixel AUPRO",
}


class LeakageError(RuntimeError):
    pass


def _metrics_block(labels, scores, maps, masks, n_boot: int | None) -> dict[str, Any]:
    labels, scores = np.asarray(labels), np.asarray(scores)
    out: dict[str, Any] = {
        "n": int(labels.size),
        "n_normal": int((labels == 0).sum()),
        "n_anomalous": int((labels == 1).sum()),
    }
    img = M.image_auroc(labels, scores)
    pix = M.pixel_auroc(masks, maps)
    pro = M.aupro(list(masks), list(maps), FPR_LIMIT)
    if n_boot is None:
        out.update(image_auroc=img, pixel_auroc=pix, aupro=pro)
        return out
    stats = M.PixelStats(masks, maps)
    n = labels.size

    def w(idx):
        return np.bincount(idx, minlength=n).astype(float)

    for key, value, fn in (
        ("image_auroc", img, lambda i: M.image_auroc(labels[i], scores[i])),
        ("pixel_auroc", pix, lambda i: stats.pixel_auroc(w(i))),
        ("aupro", pro, lambda i: stats.aupro(w(i), FPR_LIMIT)),
    ):
        lo, hi, skipped = M.bootstrap_ci(fn, n, n_boot, 0, return_skipped=True)
        out[key] = {"value": value, "ci95": [lo, hi], "bootstrap_skipped": skipped}
    return out


def threshold_entry(res: dict[str, Any]) -> dict[str, Any]:
    r, p = res["default_r"], res["default_p"]
    row = next(x for x in res["sensitivity"] if x["r"] == r and x["p"] == p)
    band = res["review_band"]["validation"]
    return {
        "r": r,
        "p": p,
        "threshold": row["threshold"],
        "review_lower": band["lower"],
        "review_share_target": band["target_share"],
        "threshold_by_r_p": {f"r={x['r']},p={x['p']}": x["threshold"] for x in res["sensitivity"]},
    }


def evaluate_subset(
    subset: str,
    train: list[Sample],
    test_samples: list[Sample],
    collect: Callable[[list[Sample]], tuple],
    bootstrap_n: int = BOOTSTRAP_N,
) -> dict[str, Any]:
    leaks = overlap(train, test_samples)
    if leaks:
        raise LeakageError(f"{subset}: {len(leaks)} eval images are also in the train set")
    scores, maps, masks, labels = collect(test_samples)
    val_s, test_s = val_test_split(test_samples, SPLIT_SEED)
    pos = {s.image_id: i for i, s in enumerate(test_samples)}
    vi = np.array([pos[s.image_id] for s in val_s])
    ti = np.array([pos[s.image_id] for s in test_s])
    t_sc, t_y = scores[ti], labels[ti]
    v_sc, v_y = scores[vi], labels[vi]
    rows = T.sensitivity((v_sc, v_y), (t_sc, t_y), T.RS, T.PS)
    thr = next(r["threshold"] for r in rows if r["r"] == T.DEFAULT_R and r["p"] == DEFAULT_P)
    band = T.review_band(v_sc, v_y, thr, REVIEW_SHARE, DEFAULT_P)
    return {
        "subset": subset,
        "default_r": T.DEFAULT_R,
        "default_p": DEFAULT_P,
        "leakage": {"train_vs_eval_overlap": 0},
        "split": {
            "seed": SPLIT_SEED,
            "validation_ids": sorted(s.image_id for s in val_s),
            "test_ids": sorted(s.image_id for s in test_s),
        },
        "validation": {"n": int(vi.size), "n_anomalous": int(v_y.sum())},
        "test": _metrics_block(t_y, t_sc, maps[ti], masks[ti], bootstrap_n),
        "official_test": _metrics_block(labels, scores, maps, masks, None),
        "sensitivity": rows,
        "review_band": {
            "validation": band,
            "test": T.band_effect(t_sc, t_y, thr, band["lower"], T.DEFAULT_R, DEFAULT_P),
        },
    }


def make_collector(model_path: Path, cache_dir: Path) -> Callable[[list[Sample]], tuple]:
    """Scores and maps for samples with the saved model, cached by the model file's hash."""
    sha = hashlib.sha256(Path(model_path).read_bytes()).hexdigest()

    def collect(samples: list[Sample]):
        import torch

        from linecopilot.vision.patchcore import PatchCore
        from linecopilot.vision.preprocess import preprocess_image, preprocess_mask

        cache = cache_dir / f"{Path(model_path).stem}.npz"
        ids = np.array([s.image_id for s in samples])
        if cache.exists():
            z = np.load(cache, allow_pickle=False)
            if str(z["model_sha"]) == sha and np.array_equal(z["ids"], ids):
                return z["scores"], z["maps"], z["masks"], z["labels"]
        model = PatchCore.load(Path(model_path))
        scores, maps = [], []
        with torch.no_grad():
            for i in range(0, len(samples), 8):
                batch = torch.stack([preprocess_image(s.image_path) for s in samples[i : i + 8]])
                m = model.score_maps(batch)[:, 0].cpu().numpy().astype(np.float32)
                maps.append(m)
                scores.append(m.reshape(m.shape[0], -1).max(1))
                print(f"  scored {min(i + 8, len(samples))}/{len(samples)}", flush=True)
        scores, maps = np.concatenate(scores), np.concatenate(maps)
        masks = np.stack([preprocess_mask(s.mask_path) for s in samples])
        labels = np.array([s.label for s in samples])
        cache_dir.mkdir(parents=True, exist_ok=True)
        np.savez(
            cache, model_sha=sha, ids=ids, scores=scores, maps=maps, masks=masks, labels=labels
        )
        return scores, maps, masks, labels

    return collect


def _ci(x: dict) -> str:
    lo, hi = x["ci95"]
    return f"{x['value']:.3f} ({lo:.3f} to {hi:.3f})"


def _mean(subs: dict[str, Any], key: str) -> float:
    return float(np.mean([r["official_test"][key] for r in subs.values()]))


def published_lines(doc: dict[str, Any]) -> list[str]:
    p, subs = doc["published"], doc["subsets"]
    a, s = p["primary"], p["secondary"]
    L = [
        f"Primary source: {a['source']}, {a['url']}, {a['table']}. Published PatchCore average "
        f"({a['scope']}): image AUROC {a['average_image_auroc'] * 100:.1f}, pixel AUROC "
        f"{a['average_pixel_auroc'] * 100:.1f}.",
    ]
    if subs:
        L.append(
            f"Ours, mean over the six food subsets on the full official test split: image AUROC "
            f"{_mean(subs, 'image_auroc') * 100:.1f}, pixel AUROC "
            f"{_mean(subs, 'pixel_auroc') * 100:.1f}. These averages cover different sets of "
            "classes (12 published, 6 ours), so the comparison is indicative only."
        )
    L += [
        "",
        f"Setup match: {p['matches_our_setup']}. {p['setup_note']}",
        "",
        f"Per-class reference: {s['source']}, {s['url']}, {s['table']}. {s['caveat']}",
        "",
        "| Subset | Image AUROC (ours, full official test) | Image AUROC (published) "
        "| Pixel AUROC (ours) | Pixel AUROC (published) | Pixel AUPRO (ours) |",
        "|---|---|---|---|---|---|",
    ]
    for name, v in s["per_subset"].items():
        o = subs.get(name, {}).get("official_test")
        ours = (
            (f"{o['image_auroc']:.3f}", f"{o['pixel_auroc']:.3f}", f"{o['aupro']:.3f}")
            if o
            else ("n/a",) * 3
        )
        L.append(
            f"| {name} | {ours[0]} | {v['image_auroc']:.3f} | {ours[1]} "
            f"| {v['pixel_auroc']:.3f} | {ours[2]} |"
        )
    return L


def first_run_lines(doc: dict[str, Any]) -> list[str]:
    f, subs = doc["first_run"], doc["subsets"]
    L = [
        f["note"],
        "",
        f"Before (centre crop) and after (whole image resized), {f['columns']}, "
        "full official test split:",
        "",
        "| Subset | Before | After |",
        "|---|---|---|",
    ]
    for name, v in f["per_subset"].items():
        o = subs.get(name, {}).get("official_test")
        after = (
            f"{o['image_auroc']:.3f} / {o['pixel_auroc']:.3f} / {o['aupro']:.3f}" if o else "n/a"
        )
        b = v["official"]
        L.append(f"| {name} | {b[0]:.3f} / {b[1]:.3f} / {b[2]:.3f} | {after} |")
    return L


def grid_lines(subs: dict[str, Any]) -> list[str]:
    rs = [x["r"] for x in next(iter(subs.values()))["sensitivity"] if x["p"] == T.PS[0]]
    L = [
        "| Subset | p | " + " | ".join(f"r = {r}" for r in rs) + " |",
        "|---|---|" + "---|" * len(rs),
    ]
    for name, res in subs.items():
        for p in T.PS:
            cells = [x for x in res["sensitivity"] if x["p"] == p]
            L.append(
                f"| {name} | {p:.1%} | "
                + " | ".join(f"{x['test']['cost_per_1000']:.1f}" for x in cells)
                + " |"
            )
    return L


def markdown(doc: dict[str, Any]) -> str:
    L = [
        "# Vision eval (PatchCore on VisA food subsets)",
        "",
        f"Date {doc['date']}, commit `{doc['commit']}`. Split seed {SPLIT_SEED}; bootstrap "
        f"{BOOTSTRAP_N} resamples over images, seed 0. Train/eval overlap checked by path and "
        "by content hash before scoring. Images are resized whole to 224 x 224 (no crop).",
        "",
        "Assumptions and caveats:",
        "",
    ]
    L += [f"- {a}" for a in doc["assumptions"]]
    subs = doc["subsets"]
    if subs:
        L += [
            "",
            "## Test split (95% bootstrap interval)",
            "",
            "| Subset | Test images (anomalous) | Image AUROC | Pixel AUROC | Pixel AUPRO |",
            "|---|---|---|---|---|",
        ]
        for s, r in subs.items():
            t = r["test"]
            L.append(
                f"| {s} | {t['n']} ({t['n_anomalous']}) | {_ci(t['image_auroc'])} "
                f"| {_ci(t['pixel_auroc'])} | {_ci(t['aupro'])} |"
            )
        L += [
            "",
            "## Full official test split (for comparison with published work)",
            "",
            "| Subset | Images (anomalous) | Image AUROC | Pixel AUROC | Pixel AUPRO |",
            "|---|---|---|---|---|",
        ]
        for s, r in subs.items():
            o = r["official_test"]
            L.append(
                f"| {s} | {o['n']} ({o['n_anomalous']}) | {o['image_auroc']:.3f} "
                f"| {o['pixel_auroc']:.3f} | {o['aupro']:.3f} |"
            )
        L += [
            "",
            "## Threshold, cost and review band (r = 20, p = 2% defects, relative units)",
            "",
            "Threshold from validation only. Cost per 1000 items = 1000 x ((1 - p) x false "
            "reject rate + p x r x escape rate), on test. Review band: 10% of items, weighted "
            "by p, from validation.",
            "",
            "| Subset | Threshold | Cost per 1000 items | False reject rate | Escape rate "
            "| Items to review per 1000 | Escape rate with review |",
            "|---|---|---|---|---|---|---|",
        ]
        for s, r in subs.items():
            row = next(
                x for x in r["sensitivity"] if x["r"] == r["default_r"] and x["p"] == r["default_p"]
            )
            te, bt = row["test"], r["review_band"]["test"]
            L.append(
                f"| {s} | {row['threshold']:.3f} | {te['cost_per_1000']:.1f} "
                f"| {te['false_reject_rate']:.3f} | {te['escape_rate']:.3f} "
                f"| {bt['review_per_1000']:.0f} | {bt['escape_rate_after']:.3f} |"
            )
        L += ["", "## Sensitivity: test cost per 1000 items by r and p", ""] + grid_lines(subs)
        L += ["", "## Test-set rates for every r and p", ""]
        L += [
            "| Subset | r | p | Threshold | False reject rate | Escape rate |",
            "|---|---|---|---|---|---|",
        ]
        for s, r in subs.items():
            for x in r["sensitivity"]:
                te = x["test"]
                L.append(
                    f"| {s} | {x['r']} | {x['p']:.1%} | {x['threshold']:.3f} "
                    f"| {te['false_reject_rate']:.3f} | {te['escape_rate']:.3f} |"
                )
    L += ["", "## Published comparison", ""] + published_lines(doc)
    L += ["", "## First run with a centre crop", ""] + first_run_lines(doc)
    return "\n".join(L) + "\n"


def write(doc: dict[str, Any], out_dir: Path = RESULTS) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "vision.json"
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    path.with_suffix(".md").write_text(markdown(doc))
    return path


def main(argv: list[str] | None = None) -> int:
    from linecopilot.config import get_settings
    from linecopilot.vision.patchcore import PatchCore

    ap = argparse.ArgumentParser(description="PatchCore vision eval on VisA food subsets.")
    ap.add_argument("--subsets", nargs="*", default=list(SUBSETS))
    args = ap.parse_args(argv)
    settings = get_settings()
    root = settings.data_dir / "visa"
    models = settings.data_dir / "models" / "vision"
    cache_dir = settings.data_dir / "cache" / "vision"
    subsets: dict[str, Any] = {}
    thresholds: dict[str, Any] = {}
    model_info: dict[str, Any] = {}
    for sub in args.subsets:
        print(sub, flush=True)
        train = load_split(root, sub, "train")
        test = load_split(root, sub, "test")
        path = models / f"{sub}.pt"
        meta = PatchCore.load(path, backbone=_NullBackbone()).meta
        if meta.get("train_ids") != [s.image_id for s in train]:
            raise LeakageError(f"{sub}: model was not fitted on the official train normals")
        model_info[sub] = {
            k: meta.get(k)
            for k in ("backbone", "input_size", "crop", "patches_total", "bank_size", "fit_seconds")
        } | {"train_images": len(train)}
        res = evaluate_subset(sub, train, test, make_collector(path, cache_dir))
        subsets[sub] = res
        thresholds[sub] = threshold_entry(res)
        t = res["test"]
        print(
            f"  test image AUROC {t['image_auroc']['value']:.3f} pixel AUROC "
            f"{t['pixel_auroc']['value']:.3f} AUPRO {t['aupro']['value']:.3f}",
            flush=True,
        )
    doc = {
        "date": datetime.now(UTC).date().isoformat(),
        "commit": git_commit(),
        "model": {
            "method": "PatchCore (in-repo), k=1, 3x3 pooling, Gaussian sigma 4, "
            "whole image resized to 224 x 224",
            "per_subset": model_info,
        },
        "assumptions": ASSUMPTIONS,
        "published": PUBLISHED,
        "first_run": FIRST_RUN_CENTRE_CROP,
        "subsets": subsets,
    }
    path = write(doc)
    (models / "thresholds.json").write_text(json.dumps(thresholds, indent=2) + "\n")
    print(f"wrote {path}", file=sys.stderr)
    return 0


class _NullBackbone:
    """Placeholder so reading a model's metadata does not load the 100 MB backbone."""

    def __new__(cls):
        from torch import nn

        m = nn.Sequential()
        m.add_module("layer2", nn.Identity())
        m.add_module("layer3", nn.Identity())
        return m


if __name__ == "__main__":
    sys.exit(main())
