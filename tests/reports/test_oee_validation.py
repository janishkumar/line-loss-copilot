from linecopilot.reports.oee_validation import gap_stats, summarise_rows


def test_gap_stats_on_known_rows():
    s = gap_stats([0.01, -0.03, 0.10])
    assert s["n"] == 3
    assert round(s["mean_abs"], 4) == 0.0467
    assert round(s["median_abs"], 4) == 0.03
    assert s["max_abs"] == 0.10
    assert round(s["share_within_2pts"], 4) == round(1 / 3, 4)
    assert round(s["share_within_5pts"], 4) == round(2 / 3, 4)
    assert round(s["mean_signed"], 4) == 0.0267


def test_gap_stats_empty_is_none_not_zero():
    s = gap_stats([])
    assert s["n"] == 0 and s["mean_abs"] is None


def row(shift, period, status, gap=None, ogap=None, planned=30000):
    return {
        "shift_id": shift,
        "period": period,
        "match_status": status,
        "availability_gap": gap,
        "oee_gap": ogap,
        "planned_s_published": planned,
    }


def test_unmatched_reported_not_dropped():
    rows = [
        row("brick:2025-10-01", "before", "matched", 0.01, 0.02),
        row("brick:2025-10-02", "before", "no_stops", None, None),
        row("brick:2026-03-25", "after", "no_published", None, None, None),
    ]
    out = summarise_rows(rows)
    assert out["before"]["n_published"] == 2
    assert out["before"]["n_matched"] == 1
    assert out["before"]["n_no_stops"] == 1
    assert out["after"]["n_no_published"] == 1
    assert out["after"]["n_published"] == 0
    assert out["after"]["availability"]["n"] == 0
