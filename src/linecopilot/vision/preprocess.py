"""The one place images and masks are resized.

Training, evaluation, ONNX export and inference all import from here so the geometry is
identical: the whole image is resized to 224x224 with no centre crop (the aspect ratio changes,
nothing is cut off, so a defect near an edge stays in view). Images use bicubic resampling (PIL)
and ImageNet normalisation; masks use nearest-neighbour so they stay binary. The memory banks
are fitted with this transform: change it and they must be refitted.
"""

from pathlib import Path

import numpy as np
import torch
from PIL import Image

from linecopilot.vision.patchcore import IMAGENET_MEAN, IMAGENET_STD

SIZE = 224


def preprocess_image(path: Path) -> torch.Tensor:
    """Image file -> normalised float tensor [3, 224, 224]."""
    with Image.open(path) as im:
        im = im.convert("RGB").resize((SIZE, SIZE), Image.BICUBIC)
        data = torch.frombuffer(bytearray(im.tobytes()), dtype=torch.uint8)
    x = data.view(SIZE, SIZE, 3).permute(2, 0, 1).float() / 255.0
    mean = torch.tensor(IMAGENET_MEAN).view(3, 1, 1)
    std = torch.tensor(IMAGENET_STD).view(3, 1, 1)
    return (x - mean) / std


def preprocess_mask(path: Path | None) -> np.ndarray:
    """Mask file (or None for a normal image) -> bool array [224, 224] in the image's geometry."""
    if path is None:
        return np.zeros((SIZE, SIZE), dtype=bool)
    with Image.open(path) as im:
        return np.asarray(im.convert("L").resize((SIZE, SIZE), Image.NEAREST)) > 0
