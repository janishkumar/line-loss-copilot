"""Anchors and write against the fixture database."""

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


def test_availability_queries_never_read_on_or_after_cutoff(built):
    import linecopilot.synth.anchors as m

    assert "< %(cutoff)s" in m.AVAILABILITY_SQL or "<%(cutoff)s" in m.AVAILABILITY_SQL
    assert "least(" in m.AVAILABILITY_SQL.lower()


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


def test_agent_role_can_select_synthetic_and_plan(built, agent_url):
    import psycopg

    schemas.apply(built)
    with psycopg.connect(agent_url) as c:
        assert c.execute("select count(*) from synthetic.product").fetchone()[0] >= 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("insert into synthetic.stock (material_id, on_hand) values ('x', 1)")
