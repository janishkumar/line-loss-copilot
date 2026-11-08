"""Vision eval maths and rendering on generated arrays; no images, no backbone."""

from pathlib import Path

import numpy as np
import pytest

from evals import vision as ev
from linecopilot.vision.data import Sample


def samples(n_norm=8, n_anom=8, subset="toy"):
    out = []
    for i in range(n_norm):
        out.append(Sample(subset, "test", 0, Path(f"/x/n{i}.jpg"), None, f"{subset}/n{i}.jpg"))
    for i in range(n_anom):
        out.append(
            Sample(
                subset, "test", 1, Path(f"/x/a{i}.jpg"), Path(f"/x/a{i}.png"), f"{subset}/a{i}.jpg"
            )
        )
    return out


def fake_collect(smp):
    rng = np.random.default_rng(0)
    n = len(smp)
    labels = np.array([s.label for s in smp])
    masks = np.zeros((n, 16, 16), bool)
    maps = rng.normal(size=(n, 16, 16)).astype(np.float32)
    for i, y in enumerate(labels):
        if y:
            masks[i, 4:9, 4:9] = True
            maps[i, 4:9, 4:9] += 3
    return maps.reshape(n, -1).max(1), maps, masks, labels


def test_evaluate_subset_structure(monkeypatch):
    monkeypatch.setattr(ev, "overlap", lambda train, others: [])
    res = ev.evaluate_subset("toy", [], samples(), fake_collect, bootstrap_n=30)
    t = res["test"]
    assert t["n"] == 8 and res["validation"]["n"] == 8 and res["official_test"]["n"] == 16
    for key in ("image_auroc", "pixel_auroc", "aupro"):
        lo, hi = t[key]["ci95"]
        assert lo <= t[key]["value"] <= hi or lo <= hi
        assert 0.0 <= t[key]["value"] <= 1.0
    assert res["official_test"]["image_auroc"] > 0.9
    assert [r["r"] for r in res["sensitivity"]] == [5, 10, 20, 50, 100]
    assert res["default_r"] == 20 and "lower" in res["review_band"]["validation"]
    assert res["leakage"] == {"train_vs_eval_overlap": 0}
    ids = res["split"]
    assert set(ids["validation_ids"]).isdisjoint(ids["test_ids"])


def test_leakage_stops_the_eval(monkeypatch):
    s = samples()
    monkeypatch.setattr(ev, "overlap", lambda train, others: others[:1])
    with pytest.raises(ev.LeakageError):
        ev.evaluate_subset("toy", s[:1], s, fake_collect, bootstrap_n=5)


def test_thresholds_entry():
    monkey = {
        "default_r": 20,
        "sensitivity": [{"r": 20, "threshold": 1.5}],
        "review_band": {"validation": {"lower": 1.0, "target_share": 0.1}},
    }
    e = ev.threshold_entry(monkey)
    assert e["threshold"] == 1.5 and e["review_lower"] == 1.0 and e["r"] == 20


def test_markdown_and_published_have_citation():
    doc = {
        "date": "2026-01-01",
        "commit": "abc",
        "model": {},
        "assumptions": ev.ASSUMPTIONS,
        "subsets": {},
        "published": ev.PUBLISHED,
    }
    md = ev.markdown(doc)
    assert "arxiv.org/html/2512.21459" in md and "Table 8" in md
    assert ev.PUBLISHED["matches_our_setup"] is False
