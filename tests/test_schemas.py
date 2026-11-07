"""The schemas outside dbt (enrich, ml) apply cleanly, twice."""

import pytest

from linecopilot import schemas

pytestmark = pytest.mark.db


def test_apply_is_idempotent(built):
    assert schemas.apply(built) == [f.name for f in schemas.FILES]
    assert schemas.apply(built) == [f.name for f in schemas.FILES]
    found = {
        r[0]
        for r in built.execute(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name IN ('enrich', 'ml')"
        )
    }
    assert found == {"enrich", "ml"}
    assert built.execute("SELECT enrich.fold('ΆΒΓ')").fetchone()[0] == "αβγ"
    assert built.execute("SELECT to_regclass('ml.stop_risk_score')").fetchone()[0] is not None


def test_files_exist():
    assert all(f.exists() for f in schemas.FILES)
