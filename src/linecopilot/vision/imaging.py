"""Torch-free image helpers for the inspection stream.

`make inspect` scores with ONNX Runtime and the API never loads PyTorch, so the preprocessing the
stream uses lives here in numpy. It reproduces `vision.preprocess.preprocess_image` (whole image
resized to 224 x 224 with PIL bicubic, scaled to 0..1, ImageNet mean and std); a test compares the
two on real-shaped input. Heatmap overlays are drawn here too.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

SIZE = 224
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
OVERLAY_SIZE = 448


def preprocess_np(path: Path) -> np.ndarray:
    """Image file -> normalised float32 array [3, 224, 224] (same values as preprocess_image)."""
    with Image.open(path) as im:
        rgb = im.convert("RGB").resize((SIZE, SIZE), Image.BICUBIC)
        arr = np.asarray(rgb, dtype=np.uint8)
    x = arr.astype(np.float32).transpose(2, 0, 1) / np.float32(255.0)
    mean = np.asarray(IMAGENET_MEAN, dtype=np.float32).reshape(3, 1, 1)
    std = np.asarray(IMAGENET_STD, dtype=np.float32).reshape(3, 1, 1)
    return ((x - mean) / std).astype(np.float32)


def overlay(image_path: Path, amap: np.ndarray, threshold: float) -> Image.Image:
    """The resized image with the anomaly map drawn over it.

    The colour scale is fixed by the subset's threshold (transparent at or below half the
    threshold, full red-yellow at one and a half times it), so overlays are comparable between
    images of one subset: a bright area means the same score everywhere.
    """
    with Image.open(image_path) as im:
        base = im.convert("RGB").resize((SIZE, SIZE), Image.BICUBIC)
    lo, hi = 0.5 * threshold, 1.5 * threshold
    v = np.clip((np.asarray(amap, dtype=np.float32) - lo) / max(hi - lo, 1e-9), 0.0, 1.0)
    colour = np.stack(
        [np.clip(2 * v, 0, 1), np.clip(2 * v - 1, 0, 1), np.zeros_like(v)], axis=-1
    )  # red, then yellow
    alpha = (0.65 * v)[..., None]
    mixed = (1 - alpha) * (np.asarray(base, dtype=np.float32) / 255.0) + alpha * colour
    out = Image.fromarray((np.clip(mixed, 0, 1) * 255).astype(np.uint8))
    return out.resize((OVERLAY_SIZE, OVERLAY_SIZE), Image.BICUBIC)
