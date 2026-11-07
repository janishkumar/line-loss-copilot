"""Citation support: unit counts here; ground-truth evidence on the test db in test_truth_db."""

from evals.citations import CitationCheck, check, summarize


def test_citation_support_counts():
    evidence = {1, 2, 3}
    checks = [
        check("A [event:1] [event:2]\nANSWER: x", evidence),  # all supported
        check("B [event:1, 9]\nANSWER: y", evidence),  # one of two
        check("C\nANSWER: z", evidence),  # none cited
        check("D [event:9]\nANSWER: NOT_AVAILABLE", set()),  # NA: anything cited is unsupported
    ]
    assert [c.cited for c in checks] == [[1, 2], [1, 9], [], [9]]
    assert [c.supported for c in checks] == [[1, 2], [1], [], []]
    assert checks[1].unsupported == [9]
    s = summarize(checks)
    assert s["cited_rows"] == 5 and s["supported_rows"] == 3
    assert s["micro_support_rate"] == 3 / 5
    assert s["share_fully_supported"] == 1 / 4
    assert s["share_no_citations"] == 1 / 4


def test_summary_empty():
    s = summarize([CitationCheck([], [])])
    assert s["micro_support_rate"] is None and s["share_no_citations"] == 1.0
    assert summarize([])["answers"] == 0
