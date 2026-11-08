"""The one place images and masks are resized and cropped.

Training, evaluation, ONNX export and inference all import from here so the geometry is
identical: the short side is resized to 256 and the centre 224x224 is kept. Images use bicubic
resampling (PIL) and ImageNet normalisation; masks use nearest-neighbour so they stay binary.
This differs from torchvision's Resize(256) (bilinear, antialiased); the memory banks were fitted
with this transform, so keep it unchanged or refit.
"""

from pathlib import Path

import numpy as np
import torch
from PIL import Image

from linecopilot.vision.patchcore import IMAGENET_MEAN, IMAGENET_STD

RESIZE = 256
CROP = 224


def _resize_crop(im: Image.Image, resample: int) -> Image.Image:
    w, h = im.size
    scale = RESIZE / min(w, h)
    im = im.resize((max(round(w * scale), CROP), max(round(h * scale), CROP)), resample)
    w, h = im.size
    left, top = (w - CROP) // 2, (h - CROP) // 2
    return im.crop((left, top, left + CROP, top + CROP))


def preprocess_image(path: Path) -> torch.Tensor:
    """Image file -> normalised float tensor [3, 224, 224]."""
    with Image.open(path) as im:
        im = _resize_crop(im.convert("RGB"), Image.BICUBIC)
        data = torch.frombuffer(bytearray(im.tobytes()), dtype=torch.uint8)
    x = data.view(CROP, CROP, 3).permute(2, 0, 1).float() / 255.0
    mean = torch.tensor(IMAGENET_MEAN).view(3, 1, 1)
    std = torch.tensor(IMAGENET_STD).view(3, 1, 1)
    return (x - mean) / std


def preprocess_mask(path: Path | None) -> np.ndarray:
    """Mask file (or None for a normal image) -> bool array [224, 224] in the image's geometry."""
    if path is None:
        return np.zeros((CROP, CROP), dtype=bool)
    with Image.open(path) as im:
        return np.asarray(_resize_crop(im.convert("L"), Image.NEAREST)) > 0
