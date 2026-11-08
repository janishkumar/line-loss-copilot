"""PatchCore anomaly detector (Roth et al., 2022), implemented in this repo.

Steps: frozen ImageNet backbone -> layer2 and layer3 feature maps -> 3x3 average pooling ->
layer3 upsampled to layer2 resolution and concatenated -> channel reduction by adaptive
average pooling (as in the reference code) -> greedy k-center coreset (selected on a random
projection) as the memory bank -> distance to the nearest bank patch per location -> map
upsampled to the input size and Gaussian-smoothed -> image score is the map maximum.

Deviations from the paper, on purpose: no re-weighting of the image score by neighbour
density; feature aggregation is plain 3x3 average pooling on each layer (the reference
adaptive-pools each layer to the embedding size first, here only the concatenation is
reduced). Everything after feature extraction is plain torch so it can be exported to ONNX.
"""

import math
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
SIGMA = 4.0
CORESET_CAP = 16_384
CORESET_FRACTION = 0.10
PROJECTION_DIM = 128


class _Stop(Exception):
    """Raised from the last hook so layers after it are never computed."""


class FeatureExtractor(nn.Module):
    """Pooled, concatenated, channel-reduced patch features from a frozen backbone."""

    def __init__(
        self,
        backbone: nn.Module,
        layers: Sequence[str] = ("layer2", "layer3"),
        out_dim: int | None = 1024,
    ) -> None:
        super().__init__()
        self.backbone = backbone.eval()
        for p in self.backbone.parameters():
            p.requires_grad_(False)
        self.layers = tuple(layers)
        self.out_dim = out_dim
        self._grabbed: dict[str, torch.Tensor] = {}
        modules = dict(self.backbone.named_modules())
        for name in self.layers:
            modules[name].register_forward_hook(self._hook(name))

    def _hook(self, name: str):
        def hook(_m, _inp, out):
            self._grabbed[name] = out
            if name == self.layers[-1]:
                raise _Stop

        return hook

    @torch.no_grad()
    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, tuple[int, int]]:
        """Returns (patches [B*h*w, D], (h, w)) for a normalised batch [B, 3, H, W]."""
        self._grabbed = {}
        try:
            self.backbone(x)
        except _Stop:
            pass
        maps = [F.avg_pool2d(self._grabbed[n], 3, stride=1, padding=1) for n in self.layers]
        h, w = maps[0].shape[-2:]
        maps = [
            m
            if m.shape[-2:] == (h, w)
            else F.interpolate(m, (h, w), mode="bilinear", align_corners=False)
            for m in maps
        ]
        feats = torch.cat(maps, dim=1)  # [B, C, h, w]
        b, c = feats.shape[:2]
        flat = feats.permute(0, 2, 3, 1).reshape(-1, c)
        if self.out_dim is not None and self.out_dim != c:
            flat = F.adaptive_avg_pool1d(flat.unsqueeze(1), self.out_dim).squeeze(1)
        return flat.contiguous(), (h, w)


def greedy_coreset(
    feats: torch.Tensor, n: int, seed: int = 0, proj_dim: int = PROJECTION_DIM
) -> torch.Tensor:
    """Indices of an approximate k-center greedy subset, selected in a random projection."""
    total, dim = feats.shape
    n = min(n, total)
    g = torch.Generator().manual_seed(seed)
    if dim > proj_dim:
        proj = torch.randn(dim, proj_dim, generator=g) / math.sqrt(proj_dim)
        pts = feats @ proj
    else:
        pts = feats
    first = int(torch.randint(total, (1,), generator=g))
    chosen = [first]
    sq = (pts * pts).sum(1)
    # |p - c|^2 = |p|^2 - 2 p.c + |c|^2 as a matrix-vector product: one pass over the points
    mind = (sq - 2 * (pts @ pts[first]) + sq[first]).clamp_min_(0)
    buf = torch.empty_like(mind)
    for _ in range(n - 1):
        nxt = int(torch.argmax(mind))
        chosen.append(nxt)
        torch.mv(pts, pts[nxt], out=buf)
        buf.mul_(-2).add_(sq).add_(sq[nxt]).clamp_min_(0)
        torch.minimum(mind, buf, out=mind)
    return torch.tensor(chosen, dtype=torch.long)


def gaussian_kernel(sigma: float = SIGMA, truncate: float = 4.0) -> torch.Tensor:
    radius = int(truncate * sigma + 0.5)
    x = torch.arange(-radius, radius + 1, dtype=torch.float32)
    k = torch.exp(-0.5 * (x / sigma) ** 2)
    return k / k.sum()


def smooth(maps: torch.Tensor, sigma: float = SIGMA) -> torch.Tensor:
    """Separable Gaussian blur of [B, 1, H, W] with reflect padding."""
    k = gaussian_kernel(sigma).to(maps)
    r = k.numel() // 2
    pad = min(r, maps.shape[-1] - 1, maps.shape[-2] - 1)
    x = F.pad(maps, (pad, pad, pad, pad), mode="reflect") if pad else maps
    if pad != r:  # image smaller than the kernel: fall back to replicate padding
        x = F.pad(maps, (r, r, r, r), mode="replicate")
    x = F.conv2d(x, k.view(1, 1, 1, -1))
    return F.conv2d(x, k.view(1, 1, -1, 1))


class PatchCore:
    def __init__(
        self,
        extractor: FeatureExtractor,
        seed: int = 0,
        coreset_fraction: float = CORESET_FRACTION,
        coreset_cap: int = CORESET_CAP,
        batch_size: int = 16,
        device: str = "cpu",
    ) -> None:
        self.extractor = extractor
        self.seed = seed
        self.coreset_fraction = coreset_fraction
        self.coreset_cap = coreset_cap
        self.batch_size = batch_size
        self.device = device
        self.bank: torch.Tensor | None = None
        self.meta: dict[str, Any] = {}

    def _features(self, images: Iterable[torch.Tensor]) -> torch.Tensor:
        out: list[torch.Tensor] = []
        batch: list[torch.Tensor] = []

        def flush() -> None:
            if batch:
                feats, _ = self.extractor(torch.stack(batch).to(self.device))
                out.append(feats.cpu())
                batch.clear()

        for img in images:
            batch.append(img)
            if len(batch) == self.batch_size:
                flush()
        flush()
        return torch.cat(out)

    def fit(
        self, images: Iterable[torch.Tensor], meta: dict[str, Any] | None = None
    ) -> "PatchCore":
        start = time.perf_counter()
        feats = self._features(images)
        n = min(int(feats.shape[0] * self.coreset_fraction), self.coreset_cap)
        idx = greedy_coreset(feats, max(n, 1), seed=self.seed)
        self.bank = feats[idx].clone()  # float32, full dimension
        self.meta = dict(meta or {})
        self.meta.update(
            patches_total=int(feats.shape[0]),
            bank_size=int(self.bank.shape[0]),
            fit_seconds=time.perf_counter() - start,
            device=self.device,
        )
        return self

    @torch.no_grad()
    def score_maps(self, batch: torch.Tensor) -> torch.Tensor:
        """Smoothed anomaly maps [B, 1, H, W] for a normalised batch [B, 3, H, W]."""
        if self.bank is None:
            raise RuntimeError("model is not fitted")
        feats, (h, w) = self.extractor(batch.to(self.device))
        bank = self.bank.to(feats)
        mins = torch.cat([torch.cdist(c, bank).min(dim=1).values for c in feats.split(4096)])
        amap = mins.reshape(-1, 1, h, w)
        amap = F.interpolate(amap, batch.shape[-2:], mode="bilinear", align_corners=False)
        return smooth(amap)

    def score(self, image: torch.Tensor) -> tuple[float, np.ndarray]:
        amap = self.score_maps(image.unsqueeze(0))[0, 0]
        return float(amap.max()), amap.cpu().numpy()

    def save(self, path: Path) -> None:
        if self.bank is None:
            raise RuntimeError("model is not fitted")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        config = {
            "layers": self.extractor.layers,
            "out_dim": self.extractor.out_dim,
            "seed": self.seed,
            "coreset_fraction": self.coreset_fraction,
            "coreset_cap": self.coreset_cap,
            "sigma": SIGMA,
        }
        torch.save({"bank": self.bank, "config": config, "meta": self.meta}, path)

    @classmethod
    def load(
        cls, path: Path, backbone: nn.Module | None = None, device: str = "cpu"
    ) -> "PatchCore":
        art = torch.load(path, map_location="cpu", weights_only=False)
        cfg = art["config"]
        if backbone is None:
            backbone = default_backbone()
        ex = FeatureExtractor(backbone, cfg["layers"], cfg["out_dim"])
        model = cls(ex, cfg["seed"], cfg["coreset_fraction"], cfg["coreset_cap"], device=device)
        model.extractor.to(device)
        model.bank = art["bank"]
        model.meta = art["meta"]
        return model


def default_backbone() -> nn.Module:
    """torchvision wide_resnet50_2, IMAGENET1K_V1 weights (downloaded once to the torch cache)."""
    from torchvision.models import Wide_ResNet50_2_Weights, wide_resnet50_2

    return wide_resnet50_2(weights=Wide_ResNet50_2_Weights.IMAGENET1K_V1).eval()
