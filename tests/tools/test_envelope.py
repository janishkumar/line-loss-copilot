"""Result envelope helpers (offline)."""

from linecopilot.tools.envelope import CITATION_CAP, Citation, cap_citations


def c(i: int, table: str = "piade_raw", event_id: int | None = None) -> Citation:
    return Citation(
        raw_table=table, source_file="piade/raw_data.csv", raw_row_id=i, event_id=event_id
    )


def test_cap_citations_dedupes_and_counts():
    cites = [c(i) for i in range(55)] + [c(i, event_id=99) for i in range(5)]  # 5 duplicates
    out, total = cap_citations(cites)
    assert CITATION_CAP == 50
    assert len(out) == 50 and total == 55
    assert [x.raw_row_id for x in out] == list(range(50))  # order kept, first wins


def test_cap_citations_distinguishes_tables_and_handles_empty():
    out, total = cap_citations([c(1), c(1, table="brick_oee")])
    assert len(out) == 2 and total == 2
    assert cap_citations([]) == ([], 0)
