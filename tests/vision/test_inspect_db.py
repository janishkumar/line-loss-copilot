"""`make inspect` end to end on a tiny VisA tree and a tiny ONNX model, and the store rules."""

import json

import numpy as np
import psycopg
import pytest
from psycopg import errors

from linecopilot.vision import inspect as vi
from linecopilot.vision import store
from linecopilot.vision.export import export_onnx
from linecopilot.vision.patchcore import FeatureExtractor, PatchCore
from tests.vision.test_data import _build_tree
from tests.vision.test_patchcore import TinyNet

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def tiny_models(tmp_path_factory):
    """A fitted tiny model exported at the real 224 size, plus thresholds around its scores."""
    import torch

    d = tmp_path_factory.mktemp("models")
    ex = FeatureExtractor(TinyNet(), ("layer2", "layer3"), out_dim=12)
    g = torch.Generator().manual_seed(0)
    model = PatchCore(ex, seed=0).fit([torch.randn(3, 224, 224, generator=g) for _ in range(4)])
    export_onnx(model, d / "cashew.onnx")
    return d


def _thresholds(models_dir, threshold, lower):
    (models_dir / "thresholds.json").write_text(
        json.dumps({"cashew": {"threshold": threshold, "review_lower": lower}})
    )


def _scores(models_dir, root):
    sess = vi._session(models_dir / "cashew.onnx")
    from linecopilot.vision.imaging import preprocess_np

    return [
        float(sess.run(None, {"image": preprocess_np(s.image_path)[None]})[0])
        for s in vi.stream_samples(root, "cashew")
    ]


@pytest.fixture
def tree(tmp_path):
    _build_tree(tmp_path, dup=False)
    return tmp_path


def test_run_scores_decides_writes_heatmaps_and_is_idempotent(
    vision_clean, tiny_models, tree, tmp_path
):
    scores = sorted(_scores(tiny_models, tree))
    assert len(scores) == 4
    # one image per decision: the lowest passes, the next two fall in the band, the top rejects
    thr = (scores[2] + scores[3]) / 2
    lower = (scores[0] + scores[1]) / 2
    _thresholds(tiny_models, thr, lower)
    heat = tmp_path / "heat"
    res = vi.run(vision_clean, tree, tiny_models, heat, subsets=("cashew",), log=lambda m: None)
    assert res["cashew"] == {"pass": 1, "review": 2, "reject": 1, "new": 4}
    rows = vision_clean.execute(
        "SELECT image_id, score, decision, threshold, review_lower, heatmap_path, source, split "
        "FROM vision.inspection ORDER BY inspection_id"
    ).fetchall()
    first_ids = [s.image_id for s in vi.stream_samples(tree, "cashew")]
    assert [r[0] for r in rows] == first_ids  # the seeded stream order, not class-sorted
    for _image_id, score, decision, t, lo, path, source, split in rows:
        assert decision == vi.decide(score, t, lo) and (t, lo) == (thr, lower)
        assert source == "simulated_stream" and split == "test"
        assert (heat / path).is_file() and path.startswith("cashew/")
    # the reject has exactly one quality event, on the simulated station, with a synthetic note
    ev = vision_clean.execute(
        "SELECT q.asset_id, q.source, q.reason_code, q.detail, a.source, q.event_id "
        "FROM synthetic.quality_event q JOIN synthetic.sim_asset a USING (asset_id)"
    ).fetchall()
    assert len(ev) == 1
    assert ev[0][:3] == ("SIM-VIS-cashew", "synthetic", "VISUAL_REJECT")
    assert "SIMULATED" in ev[0][3] and "automatic" in ev[0][3] and ev[0][4] == "synthetic"
    assert "Anomaly" not in ev[0][3] and "Normal" not in ev[0][3] and "Images/" not in ev[0][3]
    assert ev[0][5] >= 9_000_000_000
    # second run: nothing new, no second event
    again = vi.run(vision_clean, tree, tiny_models, heat, subsets=("cashew",), log=lambda m: None)
    assert again["cashew"] == {"pass": 1, "review": 2, "reject": 1, "new": 0}
    assert vision_clean.execute("SELECT count(*) FROM synthetic.quality_event").fetchone()[0] == 1
    assert vision_clean.execute("SELECT count(*) FROM vision.inspection").fetchone()[0] == 4


def test_record_review_rules(make_inspection, vision_clean):
    queued = make_inspection(decision="review")
    r = store.record_review(vision_clean, queued, "reject", "ql.a")
    assert r.status == "recorded" and r.quality_event_id
    again = store.record_review(vision_clean, queued, "reject", "ql.a")
    other = store.record_review(vision_clean, queued, "accept", "sup.a")
    assert again.status == other.status == "already_reviewed"
    assert vision_clean.execute("SELECT count(*) FROM vision.review").fetchone()[0] == 1
    assert vision_clean.execute("SELECT count(*) FROM synthetic.quality_event").fetchone()[0] == 1
    row = vision_clean.execute(
        "SELECT decision, reviewer, score_at_review FROM vision.review"
    ).fetchone()
    assert row == ("reject", "ql.a", 0.9)  # the model's score is kept beside the label

    accepted = make_inspection(decision="review")
    assert store.record_review(vision_clean, accepted, "accept", "ql.a").quality_event_id is None
    assert vision_clean.execute("SELECT count(*) FROM synthetic.quality_event").fetchone()[0] == 1

    assert (
        store.record_review(vision_clean, make_inspection(decision="pass"), "reject", "x").status
        == "not_queued"
    )
    auto = make_inspection(decision="reject")
    assert store.record_review(vision_clean, auto, "accept", "x").status == "not_queued"
    assert store.record_review(vision_clean, 999_999_999, "accept", "x").status == "not_found"
    with pytest.raises(ValueError):
        store.record_review(vision_clean, queued, "maybe", "x")


def test_create_quality_event_is_idempotent_per_inspection(make_inspection, vision_clean):
    iid = make_inspection(decision="reject", reject_event=False)
    a, created_a = store.create_quality_event(vision_clean, iid, "automatic")
    b, created_b = store.create_quality_event(vision_clean, iid, "reviewer x")
    assert a == b and created_a and not created_b
    # one station per subset, however many rejects
    store.create_quality_event(vision_clean, make_inspection(decision="reject"), "automatic")
    assert vision_clean.execute("SELECT count(*) FROM synthetic.sim_asset").fetchone()[0] == 1


def test_event_all_unions_real_and_quality_events(make_inspection, vision_clean):
    iid = make_inspection(decision="reject")
    real = vision_clean.execute("SELECT count(*) FROM core.event").fetchone()[0]
    total, synth = vision_clean.execute(
        "SELECT count(*), count(*) FILTER (WHERE is_synthetic) FROM core.event_all"
    ).fetchone()
    assert (total, synth) == (real + 1, 1)
    row = vision_clean.execute(
        "SELECT event_id, event_key, line_id, machine_id, event_type, reason_code, is_synthetic, "
        "source_system, raw_table, product FROM core.event_all WHERE is_synthetic"
    ).fetchone()
    q = vision_clean.execute(
        "SELECT event_id FROM synthetic.quality_event WHERE inspection_id = %s", (iid,)
    ).fetchone()[0]
    assert row == (
        q, f"synthetic.quality_event#{q}", "SIM-VIS-cashew", "SIM-VIS-cashew", "quality",
        "VISUAL_REJECT", True, "simulated_inspection", "synthetic.quality_event", "cashew",
    )  # fmt: skip
    # ids never collide with real events, keys are unique
    keys = vision_clean.execute("SELECT event_key, event_id FROM core.event_all").fetchall()
    assert len({k for k, _ in keys}) == len(keys) == len({i for _, i in keys})
    # real rows are exactly core.event's non-synthetic rows
    assert (
        vision_clean.execute(
            "SELECT count(*) FROM core.event_all WHERE NOT is_synthetic"
        ).fetchone()[0]
        == vision_clean.execute(
            "SELECT count(*) FROM core.event WHERE NOT is_synthetic"
        ).fetchone()[0]
    )


def test_mart_and_dbt_never_read_synthetic_events(vision_clean):
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "dbt"
    banned = ("event_all", "quality_event", "sim_asset", "synthetic.")
    sources = [
        f
        for sub in ("models", "seeds", "macros", "tests", "snapshots", "analyses")
        if (root / sub).is_dir()
        for f in (root / sub).rglob("*")
        if f.suffix in (".sql", ".yml", ".yaml") and f.is_file()
    ]
    assert sources
    for f in sources:
        text = f.read_text()
        assert not any(b in text for b in banned), f
    # and no mart relation depends on them in the database
    deps = vision_clean.execute(
        "SELECT DISTINCT n.nspname, c.relname FROM pg_depend d "
        "JOIN pg_rewrite r ON r.oid = d.objid JOIN pg_class c ON c.oid = r.ev_class "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_class t ON t.oid = d.refobjid "
        "WHERE t.relname IN ('event_all', 'quality_event', 'sim_asset') AND n.nspname = 'mart'"
    ).fetchall()
    assert deps == []


MART_COUNTS = (
    "SELECT (SELECT count(*) FROM mart.brick_shift_oee), "
    "(SELECT count(*) FROM mart.stop_episode), "
    "(SELECT count(*) FROM mart.piade_shift_oee), (SELECT count(*) FROM core.event)"
)


def test_mart_numbers_unchanged_by_quality_events(make_inspection, vision_clean):
    before = vision_clean.execute(MART_COUNTS).fetchone()
    make_inspection(decision="reject")
    after = vision_clean.execute(MART_COUNTS).fetchone()
    assert before == after


def test_agent_can_read_but_never_write_vision_or_synthetic_events(
    make_inspection, agent_url, vision_clean
):
    iid = make_inspection(decision="review")
    with psycopg.connect(agent_url, autocommit=True) as agent:
        assert agent.execute("SELECT count(*) FROM vision.inspection").fetchone()[0] == 1
        assert agent.execute("SELECT count(*) FROM core.event_all").fetchone()[0] > 0
        assert agent.execute("SELECT count(*) FROM synthetic.sim_asset").fetchone()[0] == 0
        statements = [
            f"INSERT INTO vision.review (inspection_id, decision, reviewer, score_at_review) "
            f"VALUES ({iid}, 'reject', 'copilot-agent', 0.9)",
            "UPDATE vision.inspection SET decision = 'pass'",
            "DELETE FROM vision.inspection",
            "INSERT INTO vision.inspection (subset, image_id, score, decision, threshold) "
            "VALUES ('cashew', 'x', 1, 'reject', 1)",
            "INSERT INTO synthetic.sim_asset (asset_id, subset, name) "
            "VALUES ('SIM-VIS-x', 'x', 'x')",
            "INSERT INTO synthetic.quality_event (asset_id, inspection_id, detail) "
            f"VALUES ('SIM-VIS-cashew', {iid}, 'x')",
            "DELETE FROM synthetic.quality_event",
            "SELECT nextval('synthetic.quality_event_seq')",
        ]
        for sql in statements:
            with pytest.raises(errors.InsufficientPrivilege):
                agent.execute(sql)
    assert vision_clean.execute("SELECT decision FROM vision.inspection").fetchone() == ("review",)


def test_ids_start_in_their_own_range(make_inspection, vision_clean):
    make_inspection(decision="reject")
    (eid,) = vision_clean.execute("SELECT event_id FROM synthetic.quality_event").fetchone()
    (top,) = vision_clean.execute("SELECT max(event_id) FROM core.event").fetchone()
    assert eid >= 9_000_000_000 > top
    assert np.isfinite(eid)


def test_core_event_has_no_synthetic_rows(vision_clean):
    """core.event_all keeps only NOT is_synthetic rows of core.event; pin that nothing is hidden."""
    assert vision_clean.execute(
        "SELECT count(*) FROM core.event WHERE is_synthetic IS NOT FALSE"
    ).fetchone() == (0,)


def test_rerun_warns_when_stored_thresholds_differ(vision_clean, tiny_models, tree, tmp_path):
    scores = sorted(_scores(tiny_models, tree))
    thr = (scores[2] + scores[3]) / 2
    _thresholds(tiny_models, thr, (scores[0] + scores[1]) / 2)
    heat = tmp_path / "heat"
    msgs: list[str] = []
    vi.run(vision_clean, tree, tiny_models, heat, subsets=("cashew",), log=msgs.append)
    assert not any("warning" in m for m in msgs)
    _thresholds(tiny_models, thr + 0.5, None)
    msgs.clear()
    vi.run(vision_clean, tree, tiny_models, heat, subsets=("cashew",), log=msgs.append)
    warn = [m for m in msgs if m.startswith("warning")]
    assert len(warn) == 1 and "4 stored inspection(s)" in warn[0]
    # rows keep what they were decided with
    assert (
        vision_clean.execute(
            "SELECT count(*) FROM vision.inspection WHERE threshold = %s", (thr,)
        ).fetchone()[0]
        == 4
    )


def test_quality_event_detail_has_only_the_bare_file_name(make_inspection, vision_clean):
    iid = make_inspection(
        decision="reject", reject_event=False, image="cashew/Data/Images/Normal/123.JPG"
    )
    store.create_quality_event(vision_clean, iid, "automatic")
    detail = vision_clean.execute("SELECT detail FROM synthetic.quality_event").fetchone()[0]
    assert "123.JPG" in detail and "Normal" not in detail and "Anomaly" not in detail
    assert "Images/" not in detail
