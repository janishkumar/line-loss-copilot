"""Fit one PatchCore memory bank per VisA subset on the official 1cls train normals.

Artifacts go to data/models/vision/<subset>.pt (gitignored) and carry the train image ids and
content hashes so later evaluation can assert there is no overlap. Training refuses to run if
any validation or test image is also in the training set, by path or by content hash.
"""

import sys
import time
from pathlib import Path

import torch
from PIL import Image
from torch import nn

from linecopilot.config import get_settings
from linecopilot.vision.data import SUBSETS, Sample, content_hash, load_split, overlap
from linecopilot.vision.patchcore import (
    IMAGENET_MEAN,
    IMAGENET_STD,
    FeatureExtractor,
    PatchCore,
    default_backbone,
)

RESIZE = 256
CROP = 224
SEED = 0


class LeakageError(RuntimeError):
    pass


def preprocess(path: Path) -> torch.Tensor:
    """Resize the short side to 256, centre-crop 224, ImageNet-normalise: [3, 224, 224]."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        scale = RESIZE / min(w, h)
        im = im.resize((max(round(w * scale), CROP), max(round(h * scale), CROP)), Image.BICUBIC)
        w, h = im.size
        left, top = (w - CROP) // 2, (h - CROP) // 2
        im = im.crop((left, top, left + CROP, top + CROP))
        data = torch.frombuffer(bytearray(im.tobytes()), dtype=torch.uint8)
    x = data.view(CROP, CROP, 3).permute(2, 0, 1).float() / 255.0
    mean = torch.tensor(IMAGENET_MEAN).view(3, 1, 1)
    std = torch.tensor(IMAGENET_STD).view(3, 1, 1)
    return (x - mean) / std


class Trained:
    def __init__(self, path: Path, model: PatchCore) -> None:
        self.path = path
        self.model = model


def train_subset(
    subset: str,
    train: list[Sample],
    held_out: list[Sample],
    out_dir: Path,
    backbone: nn.Module | None = None,
    out_dim: int | None = 1024,
    device: str = "cpu",
) -> Trained:
    leaks = overlap(train, held_out)
    if leaks:
        raise LeakageError(f"{subset}: {len(leaks)} validation/test images are in the train set")
    hashes = [content_hash(s.image_path) for s in train]
    extractor = FeatureExtractor(backbone or default_backbone(), ("layer2", "layer3"), out_dim)
    extractor.to(device)
    model = PatchCore(extractor, seed=SEED, device=device)
    model.fit(
        (preprocess(s.image_path) for s in train),
        meta={
            "subset": subset,
            "train_ids": [s.image_id for s in train],
            "train_hashes": hashes,
            "backbone": "wide_resnet50_2 IMAGENET1K_V1" if backbone is None else "injected",
            "resize": RESIZE,
            "crop": CROP,
        },
    )
    path = Path(out_dir) / f"{subset}.pt"
    model.save(path)
    return Trained(path, model)


def main(subsets: tuple[str, ...] = SUBSETS) -> int:
    settings = get_settings()
    root = settings.data_dir / "visa"
    out_dir = settings.data_dir / "models" / "vision"
    torch.manual_seed(SEED)
    print(f"torch {torch.__version__}, device cpu, threads {torch.get_num_threads()}")
    for subset in subsets:
        train = load_split(root, subset, "train")
        test = load_split(root, subset, "test")
        start = time.perf_counter()
        res = train_subset(subset, train, test, out_dir)
        m = res.model.meta
        print(
            f"{subset}: {len(train)} train images, {m['patches_total']} patches, "
            f"bank {m['bank_size']}, fit {m['fit_seconds']:.0f}s, "
            f"total {time.perf_counter() - start:.0f}s -> {res.path}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
