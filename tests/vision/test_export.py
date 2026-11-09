import onnx
import pytest

from linecopilot.vision import export as E
from linecopilot.vision.patchcore import FeatureExtractor, PatchCore
from tests.vision.test_patchcore import TinyNet, _anomaly, _normals


def _fitted(out_dim: int | None = 12) -> PatchCore:
    ex = FeatureExtractor(TinyNet(), ("layer2", "layer3"), out_dim=out_dim)
    return PatchCore(ex, seed=0).fit(_normals(10))


def test_export_matches_torch(tmp_path):
    m = _fitted()
    path = tmp_path / "m.onnx"
    E.export_onnx(m, path, size=64)
    onnx.checker.check_model(str(path))
    imgs = [_anomaly(), *_normals(3, seed=5)]
    res = E.parity(m, path, imgs)
    assert res["n"] == 4
    assert res["max_rel_score_diff"] <= 1e-3
    assert res["max_abs_map_diff"] < 1e-3


def test_export_non_divisible_channel_reduction(tmp_path):
    # 24 channels reduced to 10: adaptive pooling with uneven windows
    m = _fitted(out_dim=10)
    path = tmp_path / "m.onnx"
    E.export_onnx(m, path, size=64)
    assert E.parity(m, path, [_anomaly()])["max_rel_score_diff"] <= 1e-3


def test_parity_fails_loudly(tmp_path):
    m = _fitted()
    path = tmp_path / "m.onnx"
    E.export_onnx(m, path, size=64)
    m.bank = m.bank + 1.0  # torch model drifts from the exported graph
    with pytest.raises(E.ParityError):
        E.parity(m, path, [_anomaly()])


def test_export_requires_fitted_model(tmp_path):
    ex = FeatureExtractor(TinyNet(), ("layer2", "layer3"), out_dim=12)
    with pytest.raises(RuntimeError):
        E.export_onnx(PatchCore(ex), tmp_path / "x.onnx", size=64)


def test_benchmark_structure(tmp_path):
    m = _fitted()
    path = tmp_path / "m.onnx"
    E.export_onnx(m, path, size=64)
    r = E.benchmark(path, threads=1, runs=5, warmup=2, size=64)
    assert r["threads"] == 1 and r["runs"] == 5 and r["warmup"] == 2
    assert 0 < r["p50_ms"] <= r["p95_ms"] <= r["max_ms"]
    t = E.benchmark_torch(m, threads=1, runs=3, warmup=1, size=64)
    assert 0 < t["p50_ms"] <= t["p95_ms"]


def test_machine_info_fields():
    info = E.machine_info()
    assert info["onnxruntime"] and info["cpu_count"] >= 1 and "cpu" in info


def test_parity_gates_map_difference(tmp_path):
    m = _fitted()
    path = tmp_path / "m.onnx"
    E.export_onnx(m, path, size=64)
    with pytest.raises(E.ParityError):
        E.parity(m, path, [_anomaly()], map_tol=0.0)


def test_benchmark_preprocess(tmp_path):
    from PIL import Image

    p = tmp_path / "a.png"
    Image.new("RGB", (40, 30), (10, 20, 30)).save(p)
    r = E.benchmark_preprocess([p], runs=3)
    assert r["runs"] == 3 and 0 < r["p50_ms"] <= r["p95_ms"]
