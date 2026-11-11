"""Offline parts of `make inspect`: decisions, names, ordering, missing artifacts."""

import json

import pytest

from linecopilot.vision import inspect as vi
from linecopilot.vision.data import SUBSETS
from tests.vision.test_data import _build_tree


def test_decide_edges():
    assert vi.decide(0.88, 0.88, 0.87) == "reject"  # >= threshold, as in the evaluation
    assert vi.decide(0.8799, 0.88, 0.87) == "review"
    assert vi.decide(0.87, 0.88, 0.87) == "review"
    assert vi.decide(0.8699, 0.88, 0.87) == "pass"
    assert vi.decide(0.8799, 0.88, None) == "pass"  # no band: nothing goes to review


def test_heatmap_names_are_flat_unique_and_safe():
    a = vi.heatmap_name("cashew/Data/Images/Anomaly/000.JPG")
    b = vi.heatmap_name("cashew/Data/Images/Normal/000.JPG")
    assert a != b and a.endswith(".png") and "/" not in a and ".." not in a
    evil = vi.heatmap_name("x/../../etc/passwd")
    assert "/" not in evil and ".." not in evil


def test_stream_is_the_test_half_in_a_fixed_order(tmp_path):
    _build_tree(tmp_path, dup=False)
    first = [s.image_id for s in vi.stream_samples(tmp_path, "cashew")]
    again = [s.image_id for s in vi.stream_samples(tmp_path, "cashew")]
    assert first == again == sorted(first)
    assert len(first) == 4  # 8 official test images, half of each class
    assert all("Images/" in i for i in first)


def test_missing_dataset_thresholds_and_model_are_clear_errors(tmp_path):
    with pytest.raises(vi.InspectError, match="make eval-vision"):
        vi.run(None, tmp_path, tmp_path, tmp_path / "h")
    (tmp_path / "thresholds.json").write_text(json.dumps({}))
    with pytest.raises(vi.InspectError, match="make train-vision"):
        vi.run(None, tmp_path, tmp_path, tmp_path / "h", subsets=("cashew",))
    with pytest.raises(vi.InspectError, match="make data-visa"):
        vi.stream_samples(tmp_path / "nowhere", "cashew")
    assert set(SUBSETS) >= {"cashew"}
