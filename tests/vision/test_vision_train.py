from pathlib import Path

import pytest
import torch
from PIL import Image
from torch import nn

from linecopilot.vision import train as vt
from linecopilot.vision.data import Sample


class TinyNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        torch.manual_seed(0)
        self.layer2 = nn.Sequential(nn.Conv2d(3, 8, 3, stride=4, padding=1), nn.ReLU())
        self.layer3 = nn.Sequential(nn.Conv2d(8, 16, 3, stride=2, padding=1), nn.ReLU())

    def forward(self, x):
        return self.layer3(self.layer2(x))


def _img(path: Path, color: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (300, 300), (color, color, color)).save(path, format="PNG")
    return path


def _sample(root: Path, name: str, split: str, color: int, label: int = 0) -> Sample:
    return Sample("cashew", split, label, _img(root / name, color), None, name)


def test_train_subset_saves_artifact_with_ids_and_hashes(tmp_path):
    train = [_sample(tmp_path, f"t{i}.png", "train", 100 + i) for i in range(4)]
    test = [_sample(tmp_path, "x.png", "test", 10, 1)]
    out = vt.train_subset("cashew", train, test, tmp_path / "m", backbone=TinyNet(), out_dim=8)
    art = torch.load(out.path, weights_only=False)
    assert art["meta"]["train_ids"] == [s.image_id for s in train]
    assert len(art["meta"]["train_hashes"]) == 4
    assert art["meta"]["bank_size"] == art["bank"].shape[0]
    assert art["meta"]["fit_seconds"] >= 0
    assert art["meta"]["device"] == "cpu"


def test_train_refuses_on_overlap(tmp_path):
    train = [_sample(tmp_path, f"t{i}.png", "train", 100 + i) for i in range(3)]
    dup = Sample("cashew", "test", 0, train[0].image_path, None, "other-name.png")
    with pytest.raises(vt.LeakageError):
        vt.train_subset("cashew", train, [dup], tmp_path / "m", backbone=TinyNet(), out_dim=8)
    assert not (tmp_path / "m" / "cashew.pt").exists()


def test_preprocess_resizes_and_crops(tmp_path):
    t = vt.preprocess(_img(tmp_path / "a.png", 128))
    assert t.shape == (3, 224, 224)
