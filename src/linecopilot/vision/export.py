"""ONNX export of the PatchCore scorer, parity with PyTorch, and CPU latency.

One graph per subset. Input: the preprocessed float tensor [1, 3, S, S] (resize and ImageNet
normalisation stay outside the graph and come from `vision.preprocess`, so training, eval and
inference share one geometry). Outputs: (score [], map [1, 1, S, S]). The memory bank is a
constant initializer.

The export uses the legacy TorchScript exporter (`dynamo=False`), which torch 2.15 (the pinned
version) still ships; a later torch may require porting to the dynamo exporter.

The graph is the same scorer as `PatchCore.score_maps`, with two exact rewrites so it exports:
- channel reduction (adaptive average pooling over channels) becomes a fixed matrix, built by
  applying the same adaptive pool to an identity matrix;
- nearest-neighbour distance uses ||a||^2 - 2ab + ||b||^2 (clamped at 0, one sqrt after the
  minimum) instead of `torch.cdist`. The PyTorch scorer still uses cdist, so `parity` measures
  any numeric difference between the two forms.
The Gaussian blur is `patchcore.smooth`, a fixed separable conv, shared by both paths.
"""

from __future__ import annotations

import os
import platform
import statistics
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

from linecopilot.vision.patchcore import PatchCore, smooth
from linecopilot.vision.preprocess import SIZE

OPSET = 17
PARITY_TOL = 1e-3
MAP_TOL = 1e-3  # absolute, on the anomaly map


class ParityError(AssertionError):
    pass


def _reduction_matrix(c: int, out_dim: int | None) -> torch.Tensor | None:
    if out_dim is None or out_dim == c:
        return None
    # adaptive_avg_pool1d is linear, so applying it to the identity gives its matrix [c, out]
    return F.adaptive_avg_pool1d(torch.eye(c).unsqueeze(1), out_dim).squeeze(1)


class Scorer(nn.Module):
    """The PatchCore scoring path as one exportable module."""

    def __init__(self, model: PatchCore, size: int = SIZE) -> None:
        super().__init__()
        self.size = size
        if model.bank is None:
            raise RuntimeError("model is not fitted")
        ex = model.extractor
        self.backbone = ex.backbone
        self.layers = ex.layers
        bank = model.bank.detach().float().cpu().contiguous()
        self.register_buffer("bank_sq", (bank**2).sum(1))
        self.register_buffer("bank_t", bank.t().contiguous())
        self.register_buffer("reduce", None)
        self.out_dim = ex.out_dim

    def set_channels(self, c: int) -> None:
        mat = _reduction_matrix(c, self.out_dim)
        if mat is not None:
            self.register_buffer("reduce", mat)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        grabbed: dict[str, torch.Tensor] = {}
        for name, module in self.backbone.named_children():
            x = module(x)
            if name in self.layers:
                grabbed[name] = x
                if name == self.layers[-1]:
                    break
        maps = [F.avg_pool2d(grabbed[n], 3, stride=1, padding=1) for n in self.layers]
        h, w = maps[0].shape[-2], maps[0].shape[-1]
        maps = [
            m if i == 0 else F.interpolate(m, (h, w), mode="bilinear", align_corners=False)
            for i, m in enumerate(maps)
        ]
        feats = torch.cat(maps, dim=1)
        flat = feats.permute(0, 2, 3, 1).reshape(h * w, -1)
        if self.reduce is not None:
            flat = flat @ self.reduce
        d2 = (flat * flat).sum(1, keepdim=True) - 2.0 * (flat @ self.bank_t) + self.bank_sq
        mins = d2.min(dim=1).values.clamp_min(0.0).sqrt()
        amap = mins.reshape(1, 1, h, w)
        amap = F.interpolate(amap, (self.size, self.size), mode="bilinear", align_corners=False)
        amap = smooth(amap)
        return amap.max(), amap


@torch.no_grad()
def export_onnx(model: PatchCore, path: Path, size: int = SIZE) -> Path:
    """Write the full scorer to `path`; preprocessing stays outside the graph."""
    scorer = Scorer(model, size).eval()
    dummy = torch.zeros(1, 3, size, size)
    scorer.set_channels(_concat_channels(model, dummy))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        scorer,
        (dummy,),
        str(path),
        input_names=["image"],
        output_names=["score", "map"],
        opset_version=OPSET,
        dynamo=False,
    )
    return path


def _concat_channels(model: PatchCore, dummy: torch.Tensor) -> int:
    ex = model.extractor
    x = dummy
    total = 0
    for name, module in ex.backbone.named_children():
        x = module(x)
        if name in ex.layers:
            total += x.shape[1]
            if name == ex.layers[-1]:
                break
    return total


def _session(path: Path, threads: int = 1):
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])


def parity(
    model: PatchCore,
    onnx_path: Path,
    images: Sequence[torch.Tensor],
    map_tol: float = MAP_TOL,
) -> dict[str, Any]:
    """Compare PyTorch and ONNX score and map on real preprocessed images; raise if off."""
    sess = _session(onnx_path)
    rel, mdiff, srel_abs = [], [], []
    for img in images:
        score_t, map_t = model.score(img)
        score_o, map_o = sess.run(None, {"image": img.unsqueeze(0).numpy()})
        score_o = float(score_o)
        rel.append(abs(score_t - score_o) / max(abs(score_t), 1e-12))
        srel_abs.append(abs(score_t - score_o))
        mdiff.append(float(np.abs(map_t - map_o[0, 0]).max()))
    out = {
        "n": len(images),
        "max_rel_score_diff": max(rel),
        "max_abs_score_diff": max(srel_abs),
        "max_abs_map_diff": max(mdiff),
        "tolerance": PARITY_TOL,
        "map_tolerance": map_tol,
    }
    if out["max_rel_score_diff"] > PARITY_TOL or out["max_abs_map_diff"] > map_tol:
        raise ParityError(f"ONNX score differs from PyTorch: {out}")
    return out


def _percentiles(ms: list[float]) -> dict[str, float]:
    s = sorted(ms)
    p95 = s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]
    return {
        "p50_ms": statistics.median(s),
        "p95_ms": p95,
        "mean_ms": statistics.fmean(s),
        "max_ms": s[-1],
    }


def benchmark(
    onnx_path: Path, threads: int = 1, runs: int = 200, warmup: int = 20, size: int = SIZE
) -> dict[str, Any]:
    """ONNX Runtime CPU latency, batch 1; warm-up runs are excluded.

    Input is one fixed random tensor: the graph's cost does not depend on pixel values.
    """
    sess = _session(onnx_path, threads)
    x = np.random.default_rng(0).standard_normal((1, 3, size, size)).astype(np.float32)
    for _ in range(warmup):
        sess.run(None, {"image": x})
    times = []
    for _ in range(runs):
        t = time.perf_counter()
        sess.run(None, {"image": x})
        times.append((time.perf_counter() - t) * 1000)
    return {"threads": threads, "runs": runs, "warmup": warmup, **_percentiles(times)}


@torch.no_grad()
def benchmark_torch(
    model: PatchCore, threads: int = 1, runs: int = 200, warmup: int = 20, size: int = SIZE
) -> dict[str, Any]:
    """PyTorch CPU latency of `PatchCore.score` with the same protocol, for context."""
    prev = torch.get_num_threads()
    torch.set_num_threads(threads)
    try:
        x = torch.randn(3, size, size, generator=torch.Generator().manual_seed(0))
        for _ in range(warmup):
            model.score(x)
        times = []
        for _ in range(runs):
            t = time.perf_counter()
            model.score(x)
            times.append((time.perf_counter() - t) * 1000)
    finally:
        torch.set_num_threads(prev)
    return {"threads": threads, "runs": runs, "warmup": warmup, **_percentiles(times)}


def benchmark_preprocess(paths: Sequence[Path], runs: int = 50) -> dict[str, Any]:
    """Time of `preprocess_image` (decode, resize, normalise), measured separately."""
    from linecopilot.vision.preprocess import preprocess_image

    times = []
    for i in range(runs):
        t = time.perf_counter()
        preprocess_image(paths[i % len(paths)])
        times.append((time.perf_counter() - t) * 1000)
    return {"runs": runs, **_percentiles(times)}


def machine_info() -> dict[str, Any]:
    import onnxruntime

    cpu = platform.processor() or platform.machine()
    try:
        cpu = (
            subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            or cpu
        )
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "cpu": cpu,
        "cpu_count": os.cpu_count() or 1,
        "platform": platform.platform(),
        "onnxruntime": onnxruntime.__version__,
        "torch": torch.__version__,
        "opset": OPSET,
    }
