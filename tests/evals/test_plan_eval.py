"""Plan eval maths on fakes, and a tiny end-to-end run with the solver on a toy problem."""

import pytest

from evals import plan as ev


def k(late, tard, co=0, after=0):
    return {
        "late_orders": late,
        "total_tardiness_min": tard,
        "changeover_min": co,
        "orders_after_horizon": after,
    }


def test_quartiles_and_summarise():
    assert ev.quartiles([5]) == (5, 5, 5)
    assert ev.quartiles([1, 2, 3, 4, 5]) == (3, 2, 4)
    s = ev.summarise([k(1, 10), k(3, 30), k(5, 50)])
    assert s["late_orders"] == {"median": 3, "q1": 2, "q3": 4, "iqr": 2, "n": 3}
    assert s["total_tardiness_min"]["median"] == 30
    with pytest.raises(ValueError):
        ev.quartiles([])


def test_paired():
    p = ev.paired([1, 5, 3, 2], [2, 5, 1, 9])
    assert (p["n"], p["better"], p["equal"], p["worse"]) == (4, 2, 1, 1)
    assert p["share_better"] == 0.5 and p["share_not_worse"] == 0.75
    assert p["median_diff"] == pytest.approx(-0.5)
    assert p["mean_diff"] == pytest.approx(-1.5)
    with pytest.raises(ValueError):
        ev.paired([1], [1, 2])


def fake_cases():
    def case(nom, reps, status="OPTIMAL", stop="optimal"):
        return {
            "nominal": nom,
            "replays": reps,
            "status": status,
            "solver_status": status,
            "stop_reason": stop,
        }

    return {
        7: {
            "cpsat": case(k(1, 10), [k(0, 0), k(2, 40)]),
            "edd": case(k(2, 30), [k(1, 5), k(2, 40)]),
            "edd_batch": case(k(2, 20), [k(1, 2), k(2, 41)]),
            "fifo": case(k(4, 90), [k(3, 70), k(4, 80)]),
        },
        8: {
            "cpsat": case(k(0, 0), [k(1, 3), k(1, 9)], "FEASIBLE", "deterministic_time"),
            "edd": case(k(1, 5), [k(1, 3), k(0, 0)]),
            "edd_batch": case(k(1, 5), [k(1, 3), k(0, 1)]),
            "fifo": case(k(3, 50), [k(2, 20), k(2, 30)]),
        },
        9: {
            "cpsat": case(k(1, 4), [k(1, 4), k(1, 4)], "fallback_edd", "deterministic_time"),
            "edd": case(k(1, 4), [k(1, 4), k(1, 4)]),
            "edd_batch": case(k(1, 4), [k(1, 4), k(1, 4)]),
            "fifo": case(k(2, 8), [k(2, 8), k(2, 8)]),
        },
    }


def test_evaluate_on_fake_cases():
    r = ev.evaluate(fake_cases())
    assert r["solver"]["status"] == {"optimal": 1, "feasible": 1, "fallback_edd": 1}
    assert r["solver"]["stop_reason"] == {"optimal": 1, "deterministic_time": 2}
    assert r["nominal"]["cpsat"]["late_orders"]["median"] == 1
    assert r["replayed"]["edd"]["total_tardiness_min"]["n"] == 6
    # replayed cpsat tardiness minus edd: [-5, 0, 0, 9, 0, 0]
    p = r["paired"]["cpsat_vs_edd_replayed_total_tardiness_min"]
    assert (p["better"], p["equal"], p["worse"]) == (1, 4, 1)
    p = r["paired"]["cpsat_vs_fifo_nominal_late_orders"]
    assert p["share_better"] == 1.0
    # replayed cpsat minus edd_batch tardiness: [-2, 0... ] by hand: -2 -1 0 +8 0 0
    p = r["paired"]["cpsat_vs_edd_batch_replayed_total_tardiness_min"]
    assert (p["better"], p["equal"], p["worse"]) == (2, 3, 1)
    assert r["replayed"]["edd_batch"]["total_tardiness_min"]["n"] == 6


def test_markdown_mentions_synthetic_real_split_and_windows():
    doc = {
        "meta": {
            "seeds": [7, 8, 9], "n_windows": 2, "date": "d", "git_commit": "c", "seconds": 1.0,
            "cpsat_max_deterministic_time": 60, "cpsat_wall_cap_s": 120,
            "windows": [{"start": "2021-07-01T00:00:00+00:00", "end": "x"}, {"start": "2021-07-15T00:00:00+00:00", "end": "y"}],  # noqa: E501
            "anchors": {"cutoff": "2021-07-01T00:00:00+00:00", "availability": {"s_1": 0.9}},
            "seed_meta": {7: {"orders": 46, "scheduled": 40, "blocked": 6, "load_factor": 0.9, "content_sha256": "a" * 64}},  # noqa: E501
        },
        "window_stats": [{"s_1": {"stopped_share": 0.1, "stopped_share_of_covered": 0.1, "no_data_share": 0.0}}, {"s_1": {"stopped_share": 0.2, "stopped_share_of_covered": 0.4, "no_data_share": 0.5}}],  # noqa: E501
        **ev.evaluate(fake_cases()),
    }  # fmt: skip
    md = ev.markdown(doc)
    assert "synthetic orders on real capacity and real stops" in md.lower()
    assert "40.0% / 50.0%" in md and "covered time" in md and "no PIADE data" in md
    assert "brick line" in md and "CP-SAT vs EDD_BATCH" in md
    assert "CP-SAT vs EDD" in md
