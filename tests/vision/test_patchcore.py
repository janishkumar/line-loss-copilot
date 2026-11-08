import numpy as np
import pytest
import torch
from torch import nn

from linecopilot.vision.patchcore import FeatureExtractor, PatchCore, greedy_coreset


class TinyNet(nn.Module):
    """Stand-in for wide_resnet50_2: same layer names, random weights, tiny."""

    def __init__(self) -> None:
        super().__init__()
        torch.manual_seed(0)
        self.layer2 = nn.Sequential(nn.Conv2d(3, 8, 3, stride=4, padding=1), nn.ReLU())
        self.layer3 = nn.Sequential(nn.Conv2d(8, 16, 3, stride=2, padding=1), nn.ReLU())
        self.layer4 = nn.Sequential(nn.Conv2d(16, 4, 1))  # must never run

    def forward(self, x):
        return self.layer4(self.layer3(self.layer2(x)))


def _normals(n: int, seed: int = 0) -> list[torch.Tensor]:
    g = torch.Generator().manual_seed(seed)
    return [torch.randn(3, 64, 64, generator=g) * 0.3 for _ in range(n)]


def _anomaly(seed: int = 99) -> torch.Tensor:
    img = _normals(1, seed)[0].clone()
    img[:, 20:44, 20:44] = 4.0  # white square
    return img


def _model(**kw) -> PatchCore:
    ex = FeatureExtractor(TinyNet(), ("layer2", "layer3"), out_dim=12)
    return PatchCore(ex, seed=0, **kw)


def test_extractor_shape_and_skips_later_layers():
    ex = FeatureExtractor(TinyNet(), ("layer2", "layer3"), out_dim=12)
    feats, hw = ex(torch.zeros(2, 3, 64, 64))
    assert hw == (16, 16)
    assert feats.shape == (2 * 16 * 16, 12)


def test_anomaly_scores_above_normals():
    m = _model().fit(_normals(12))
    normal_scores = [m.score(x)[0] for x in _normals(6, seed=7)]
    score, amap = m.score(_anomaly())
    assert score > max(normal_scores)
    assert amap.shape == (64, 64)
    assert amap[32, 32] > amap[2, 2]


def test_coreset_cap_and_fraction():
    m = _model(coreset_fraction=0.1, coreset_cap=50).fit(_normals(12))  # 12*256 patches
    assert m.bank.shape == (50, 12)
    m2 = _model(coreset_fraction=0.01, coreset_cap=10_000).fit(_normals(12))
    assert m2.bank.shape[0] == int(12 * 256 * 0.01)


def test_greedy_coreset_picks_spread_points():
    g = torch.Generator().manual_seed(0)
    pts = torch.cat([torch.randn(200, 4, generator=g) * 0.01, torch.tensor([[50.0] * 4])])
    idx = greedy_coreset(pts, 2, seed=0)
    assert len(set(idx.tolist())) == 2
    assert 200 in idx.tolist()  # the outlier is the farthest point


def test_deterministic():
    a = _model().fit(_normals(8))
    b = _model().fit(_normals(8))
    assert torch.equal(a.bank, b.bank)
    assert a.score(_anomaly())[0] == b.score(_anomaly())[0]


def test_save_load_round_trip(tmp_path):
    m = _model().fit(_normals(8), meta={"train_ids": ["a", "b"]})
    path = tmp_path / "m.pt"
    m.save(path)
    loaded = PatchCore.load(path, backbone=TinyNet())
    assert loaded.meta["train_ids"] == ["a", "b"]
    s1, map1 = m.score(_anomaly())
    s2, map2 = loaded.score(_anomaly())
    assert s1 == s2
    assert np.array_equal(map1, map2)


def test_score_before_fit_raises():
    with pytest.raises(RuntimeError):
        _model().score(_anomaly())


def test_two_extractors_share_one_backbone():
    bb = TinyNet()
    e1 = FeatureExtractor(bb, ("layer2", "layer3"), out_dim=12)
    e2 = FeatureExtractor(bb, ("layer2", "layer3"), out_dim=12)
    x = torch.randn(2, 3, 64, 64)
    f1, _ = e1(x)
    f2, _ = e2(x)
    assert torch.equal(f1, f2)
    assert not bb._forward_hooks and all(not m._forward_hooks for m in bb.modules())
    assert bb(x).shape[1] == 4  # plain forward still runs layer4


def test_six_models_load_on_one_backbone(tmp_path):
    bb = TinyNet()
    paths = []
    for i in range(6):
        m = PatchCore(FeatureExtractor(bb, out_dim=12), seed=i).fit(_normals(4, seed=i))
        paths.append((tmp_path / f"s{i}.pt", m.score(_anomaly())[0]))
        m.save(paths[-1][0])
    loaded = [PatchCore.load(p, backbone=bb) for p, _ in paths]
    for model, (_, expected) in zip(loaded, paths, strict=True):
        assert model.score(_anomaly())[0] == expected


def test_layers_must_be_in_network_order():
    with pytest.raises(ValueError):
        FeatureExtractor(TinyNet(), ("layer3", "layer2"))
    with pytest.raises(ValueError):
        FeatureExtractor(TinyNet(), ("layer2", "nope"))


def test_smooth_handles_image_smaller_than_kernel():
    from linecopilot.vision.patchcore import smooth

    out = smooth(torch.ones(1, 1, 8, 8))
    assert out.shape == (1, 1, 8, 8)
    assert torch.allclose(out, torch.ones_like(out), atol=1e-5)
