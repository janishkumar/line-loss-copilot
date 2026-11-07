"""Anchors and write against the fixture database."""

from datetime import UTC, datetime

import psycopg
import pytest

from linecopilot import schemas
from linecopilot.synth.anchors import CUTOFF, load_anchors
from linecopilot.synth.generate import content_hash, generate, write

pytestmark = pytest.mark.db


def test_anchors_from_fixture_db(built):
    a = load_anchors(built)
    assert set(a.rates) and set(a.rates) == set(a.availability)
    assert all(r > 0 for r in a.rates.values())
    assert all(0 < v <= 1 for v in a.availability.values())
    assert a.changeover_same_family_min > 0
    assert a.changeover_cross_family_min >= a.changeover_same_family_min
    # every machine records where its availability came from
    assert set(a.sources["availability_window"]) == set(a.availability)
    assert CUTOFF.isoformat().startswith("2021-07-01")


def _depends_only_on_pre_cutoff(db_url, built, cutoff):
    """Anchors on the full database with this cutoff equal anchors on a copy with every row on
    or after the cutoff deleted (in a rolled-back transaction)."""
    full = load_anchors(built, cutoff)
    with psycopg.connect(db_url) as c:
        # PIADE rows only: the brick changeover anchor is a different process and period
        c.execute(
            "delete from core.event where source_system = 'piade' and start_ts >= %s", (cutoff,)
        )
        c.execute(
            "delete from mart.stop_episode where source_system = 'piade' and start_ts >= %s",
            (cutoff,),
        )
        c.execute("delete from mart.piade_interval_counts where start_ts >= %s", (cutoff,))
        trimmed = load_anchors(c, cutoff)
        c.rollback()
    # The trimmed copy has lost machine ids that only appear later; those are fallbacks in the
    # full run. Everything both runs know must be identical.
    for m in trimmed.rates:
        assert full.rates[m] == trimmed.rates[m]
        assert full.availability[m] == trimmed.availability[m]
        assert full.sources["availability_stats"][m] == trimmed.sources["availability_stats"][m]
    assert full.changeover_same_family_min == trimmed.changeover_same_family_min
    return full, trimmed


def test_anchors_depend_only_on_rows_before_the_cutoff(built, db_url):
    cutoff = datetime(2020, 1, 1, 14, 0, tzinfo=UTC)
    full, trimmed = _depends_only_on_pre_cutoff(db_url, built, cutoff)
    later, _ = _depends_only_on_pre_cutoff(db_url, built, datetime(2021, 7, 1, tzinfo=UTC))
    assert later.rates != full.rates or later.availability != full.availability


def test_machine_without_pre_cutoff_data_gets_median_fallback(built, db_url):
    # s_3 only has data from 2020-01-02, so a cutoff on 2020-01-02 leaves it with none
    cutoff = datetime(2020, 1, 2, tzinfo=UTC)
    full, trimmed = _depends_only_on_pre_cutoff(db_url, built, cutoff)
    assert "s_3" in full.availability and "s_3" in full.rates
    others = sorted(v for m, v in full.availability.items() if m != "s_3")
    med = (others[(len(others) - 1) // 2] + others[len(others) // 2]) / 2
    assert full.availability["s_3"] == pytest.approx(med)
    assert "fallback" in full.sources["availability_window"]["s_3"]
    assert "fallback" in full.sources["rate_basis"]["s_3"]


def test_availability_denominator_is_covered_time_and_shares_recorded(built):
    a = load_anchors(built, datetime(2020, 1, 2, tzinfo=UTC))
    s = a.sources["availability_stats"]["s_1"]
    # s_1 on 2020-01-01 fixture: stopped and covered seconds from the intervals
    assert s["covered_s"] > 0
    assert a.availability["s_1"] == pytest.approx(1 - s["stopped_s"] / s["covered_s"])
    assert 0 <= s["idle_share"] < 1 and 0 <= s["gap_share"] < 1


def test_write_replaces_rows_and_records_generation(built):
    schemas.apply(built)
    a = load_anchors(built)
    data = generate(a, 7)
    gid = write(built, data, a, 7)
    gid2 = write(built, data, a, 7)
    assert gid2 > gid
    assert built.execute("select count(*) from synthetic.customer_order").fetchone()[0] == len(
        data.customer_order
    )
    gen = built.execute(
        "select seed, content_sha256, anchors from synthetic.generation where generation_id=%s",
        (gid2,),
    ).fetchone()
    assert gen[0] == 7 and gen[1] == content_hash(data)
    assert gen[2]["rates"] == a.rates and "load_factor" in gen[2]
    assert built.execute("select count(*) from synthetic.generation").fetchone()[0] >= 2
    for t in (
        "product", "machine_capability", "machine_rate", "changeover", "customer_order",
        "material", "bom", "stock", "receipt", "planted_shortage", "generation",
    ):  # fmt: skip
        n = built.execute(f"select count(*) from synthetic.{t} where source <> 'synthetic'")
        assert n.fetchone()[0] == 0, t


def test_agent_can_read_synthetic_but_not_the_answer_key(built, agent_url):
    schemas.apply(built)
    with psycopg.connect(agent_url) as c:
        assert c.execute("select count(*) from synthetic.product").fetchone()[0] >= 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("insert into synthetic.stock (material_id, on_hand) values ('x', 1)")


def test_planted_shortage_hidden_from_agent_across_reapply(built, agent_url):
    schemas.apply(built)
    schemas.apply(built)
    with psycopg.connect(agent_url) as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("select * from synthetic.planted_shortage")
        c.rollback()
        c.execute("select count(*) from synthetic.customer_order")
    # the owner (the eval) still reads it
    built.execute("select count(*) from synthetic.planted_shortage")
