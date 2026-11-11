"""`make inspect`: score a simulated stream of held-out test images and store the decisions.

For each subset, in the fixed order of `SUBSETS`, the official test images that fall in the
test half of the stratified validation/test split (seed 0, the split the threshold was kept
away from) are scored in image_id order with that subset's ONNX graph:

    score >= threshold                      -> reject  (a simulated quality event is created)
    review_lower <= score < threshold       -> review  (waits in the review queue)
    otherwise                               -> pass

A heatmap overlay PNG goes to data/vision/heatmaps/. Rows are unique per (subset, image_id), so
a second run leaves everything already stored alone. The images are real VisA photographs; the
stream, the station and the quality events are simulated and synthetic. This module needs
onnxruntime and PIL but not PyTorch, and nothing the API imports depends on it.

    python -m linecopilot.vision.inspect
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import psycopg

from linecopilot.config import get_settings
from linecopilot.vision import store
from linecopilot.vision.data import SUBSETS, Sample, load_split, val_test_split
from linecopilot.vision.imaging import overlay, preprocess_np

SPLIT_SEED = 0
DECISIONS = ("pass", "review", "reject")


class InspectError(RuntimeError):
    """A missing artifact or dataset; the message says which and what to run."""


def decide(score: float, threshold: float, review_lower: float | None) -> str:
    if score >= threshold:
        return "reject"
    if review_lower is not None and score >= review_lower:
        return "review"
    return "pass"


def heatmap_name(image_id: str) -> str:
    """A flat, unique, filesystem-safe file name from the image id (path separators removed)."""
    stem = image_id.rsplit(".", 1)[0] if "." in image_id.rsplit("/", 1)[-1] else image_id
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem.replace("/", "__"))
    return f"{safe}.png"


def load_thresholds(models_dir: Path) -> dict[str, Any]:
    path = Path(models_dir) / "thresholds.json"
    if not path.exists():
        raise InspectError(f"{path} is missing: run `make eval-vision` first")
    return json.loads(path.read_text())


def _session(path: Path):
    import onnxruntime as ort

    return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])


def stream_samples(root: Path, subset: str) -> list[Sample]:
    """The subset's test-half images, in a fixed (image_id) order."""
    if not (Path(root) / "1cls.csv").exists():
        raise InspectError(f"{root}/1cls.csv is missing: run `make data-visa` first")
    _, test = val_test_split(load_split(root, subset, "test"), SPLIT_SEED)
    return sorted(test, key=lambda s: s.image_id)


def run(
    conn: psycopg.Connection,
    root: Path,
    models_dir: Path,
    heat_dir: Path,
    subsets: tuple[str, ...] = SUBSETS,
    make_session: Callable[[Path], Any] = _session,
    log: Callable[[str], None] = print,
) -> dict[str, dict[str, int]]:
    """Score every subset's stream; returns {subset: {decision: count, 'new': n}} read from
    the database after the run (so a repeat run reports the same totals, with new = 0)."""
    thresholds = load_thresholds(models_dir)
    heat_dir = Path(heat_dir)
    heat_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict[str, int]] = {}
    for subset in subsets:
        onnx = Path(models_dir) / f"{subset}.onnx"
        entry = thresholds.get(subset)
        if not onnx.exists() or entry is None:
            raise InspectError(
                f"{subset}: {'model ' + str(onnx) if not onnx.exists() else 'thresholds.json'} "
                "is missing: run `make train-vision`, `make eval-vision` and `make export-vision`"
            )
        thr, lower = float(entry["threshold"]), entry.get("review_lower")
        lower = None if lower is None else float(lower)
        samples = stream_samples(root, subset)
        have = {
            r[0]
            for r in conn.execute(
                "SELECT image_id FROM vision.inspection WHERE subset = %s", (subset,)
            )
        }
        todo = [s for s in samples if s.image_id not in have]
        sess = make_session(onnx) if todo else None
        new = 0
        for s in todo:
            x = preprocess_np(s.image_path)[None]
            score, amap = sess.run(None, {"image": x})
            score = float(score)
            decision = decide(score, thr, lower)
            name = f"{subset}/{heatmap_name(s.image_id)}"
            target = heat_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            overlay(s.image_path, np.asarray(amap)[0, 0], thr).save(target, format="PNG")
            with conn.transaction():
                iid = store.insert_inspection(
                    conn,
                    subset=subset,
                    image_id=s.image_id,
                    score=score,
                    decision=decision,
                    threshold=thr,
                    review_lower=lower,
                    heatmap_path=name,
                )
                if iid is not None:
                    new += 1
                    if decision == "reject":
                        store.create_quality_event(conn, iid, "automatic")
        counts = dict(
            conn.execute(
                "SELECT decision, count(*) FROM vision.inspection WHERE subset = %s GROUP BY 1",
                (subset,),
            ).fetchall()
        )
        out[subset] = {d: counts.get(d, 0) for d in DECISIONS} | {"new": new}
        log(
            f"{subset}: {len(samples)} images, new {new}, "
            + ", ".join(f"{d} {out[subset][d]}" for d in DECISIONS)
        )
    return out


def main() -> int:
    settings = get_settings()
    root = settings.data_dir / "visa"
    models = settings.data_dir / "models" / "vision"
    heat = settings.data_dir / "vision" / "heatmaps"
    try:
        with psycopg.connect(settings.database_url, autocommit=True) as conn:
            run(conn, root, models, heat)
    except InspectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
