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
FPR_LIMIT = 0.3

ASSUMPTIONS = [
    "Costs are relative: a false reject costs 1 and an escaped defect costs r. r = 20 is an "
    "assumption, not a measured plant figure; the sensitivity table shows r = 5 to 100.",
    "Validation and test are 50/50 halves of the official test split; each half holds only "
    "dozens of images per class, so intervals are wide and the threshold is noisy.",
    "The test halves are two thirds anomalous (VisA's official test mix), far above a plant's "
    "defect rate. False reject rate and escape rate are per class and transfer; cost per 1000 "
    "images and the cost-optimal threshold do not, and at a real defect rate the cost would be "
    "dominated by false rejects.",
    "Images are VisA product photos, not images from the plant; their link to a line is "
    "simulated elsewhere in this project and labelled.",
    "The review band assumes a reviewer decides every image in it correctly and ignores review "
    "effort.",
]

PUBLISHED = {
    "matches_our_setup": False,
    "source": "CCAD: Compressed Global Feature Conditioned Anomaly Detection",
    "url": "https://arxiv.org/html/2512.21459",
    "table": "Table 8 (Appendix D.2, VisA), 'AUROC (Class-level; Pixel-level) comparison with "
    "SOTA methods on VisA', column PatchCore, single-class setting",
    "metrics": "image AUROC and pixel AUROC (AUPRO is not reported there)",
    "setup": "Third-party re-run of PatchCore using an LDM (AutoEncoderKL) encoder, 256 x 256 "
    "input and a 1000-sample memory bank (the paper's Table 22). Ours: wide_resnet50_2 "
    "IMAGENET1K_V1, resize 256, centre crop 224, layers 2 and 3, coreset up to 10% or 16,384 "
    "patches. Backbone, crop and coreset differ, so this is a loose reference, not a like for "
    "like comparison. Several of its figures (macaroni2 image AUROC 0.472) look weak against "
    "other PatchCore reports, which I could not verify from a fetched table.",
    "per_subset": {
        "cashew": {"image_auroc": 0.851, "pixel_auroc": 0.777},
        "chewinggum": {"image_auroc": 0.925, "pixel_auroc": 0.921},
        "fryum": {"image_auroc": 0.769, "pixel_auroc": 0.885},
        "pipe_fryum": {"image_auroc": 0.901, "pixel_auroc": 0.920},
        "macaroni1": {"image_auroc": 0.785, "pixel_auroc": 0.944},
        "macaroni2": {"image_auroc": 0.472, "pixel_auroc": 0.936},
    },
    "note": "The VisA paper (arXiv 2207.14315) does not report PatchCore, so no AUPRO figure for "
    "PatchCore on VisA was found in a source I could fetch and read.",
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

    out["image_auroc"] = {
        "value": img,
        "ci95": M.bootstrap_ci(lambda i: M.image_auroc(labels[i], scores[i]), n, n_boot, 0),
    }
    out["pixel_auroc"] = {
        "value": pix,
        "ci95": M.bootstrap_ci(lambda i: stats.pixel_auroc(w(i)), n, n_boot, 0),
    }
    out["aupro"] = {
        "value": pro,
        "ci95": M.bootstrap_ci(lambda i: stats.aupro(w(i), FPR_LIMIT), n, n_boot, 0),
    }
    return out


def threshold_entry(res: dict[str, Any]) -> dict[str, Any]:
    r = res["default_r"]
    per_r = {str(row["r"]): row["threshold"] for row in res["sensitivity"]}
    band = res["review_band"]["validation"]
    return {
        "r": r,
        "threshold": per_r[str(r)],
        "review_lower": band["lower"],
        "review_share_target": band["target_share"],
        "threshold_by_r": per_r,
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
    rows = T.sensitivity((v_sc, v_y), (t_sc, t_y), T.RS)
    thr = next(r["threshold"] for r in rows if r["r"] == T.DEFAULT_R)
    band = T.review_band(v_sc, v_y, thr, REVIEW_SHARE)
    return {
        "subset": subset,
        "default_r": T.DEFAULT_R,
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
            "test": T.band_effect(t_sc, t_y, thr, band["lower"], T.DEFAULT_R),
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


def markdown(doc: dict[str, Any]) -> str:
    L = [
        "# Vision eval (PatchCore on VisA food subsets)",
        "",
        f"Date {doc['date']}, commit `{doc['commit']}`. Split seed {SPLIT_SEED}; bootstrap "
        f"{BOOTSTRAP_N} resamples over images, seed 0. Train/eval overlap checked by path and "
        "by content hash before scoring.",
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
            "## Threshold, cost and review band (r = 20 default, relative units)",
            "",
            "Threshold from validation only. Cost per 1000 images = (false rejects + r x "
            "escapes) / images x 1000, on test.",
            "",
            "| Subset | Threshold | Cost per 1000 | False reject rate | Escape rate | "
            "Review band share (test) | Escapes avoided in band |",
            "|---|---|---|---|---|---|---|",
        ]
        for s, r in subs.items():
            row = next(x for x in r["sensitivity"] if x["r"] == r["default_r"])
            te, bt = row["test"], r["review_band"]["test"]
            L.append(
                f"| {s} | {row['threshold']:.3f} | {te['cost_per_1000']:.0f} "
                f"| {te['false_reject_rate']:.3f} | {te['escape_rate']:.3f} "
                f"| {bt['share_to_review']:.3f} | {bt['escapes_avoided']} of {bt['escapes_before']} |"  # noqa: E501
            )
        L += ["", "## Sensitivity to r (test)", ""]
        L += [
            "| Subset | r | Threshold | Cost per 1000 | False reject rate | Escape rate |",
            "|---|---|---|---|---|---|",
        ]
        for s, r in subs.items():
            for x in r["sensitivity"]:
                te = x["test"]
                L.append(
                    f"| {s} | {x['r']} | {x['threshold']:.3f} | {te['cost_per_1000']:.0f} "
                    f"| {te['false_reject_rate']:.3f} | {te['escape_rate']:.3f} |"
                )
    p = doc["published"]
    L += [
        "",
        "## Published comparison",
        "",
        f"Source: {p['source']}, {p['url']}, {p['table']}. Metrics: {p['metrics']}.",
        "",
        f"Setup match with ours: {'yes' if p['matches_our_setup'] else 'no'}. {p['setup']}",
        "",
        p["note"],
        "",
        "| Subset | Published image AUROC | Ours (full official test) | Published pixel AUROC "
        "| Ours (full official test) |",
        "|---|---|---|---|---|",
    ]
    for s, v in p["per_subset"].items():
        o = subs.get(s, {}).get("official_test")
        ours_i = f"{o['image_auroc']:.3f}" if o else "n/a"
        ours_p = f"{o['pixel_auroc']:.3f}" if o else "n/a"
        L.append(f"| {s} | {v['image_auroc']:.3f} | {ours_i} | {v['pixel_auroc']:.3f} | {ours_p} |")
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
            for k in ("backbone", "resize", "crop", "patches_total", "bank_size", "fit_seconds")
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
            "method": "PatchCore (in-repo), k=1, 3x3 pooling, Gaussian sigma 4",
            "per_subset": model_info,
        },
        "assumptions": ASSUMPTIONS,
        "published": PUBLISHED,
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
