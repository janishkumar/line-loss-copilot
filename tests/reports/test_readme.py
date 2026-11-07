import json
import shutil
from pathlib import Path

from linecopilot.reports import readme as rd
from linecopilot.reports.readme import render_readme


def test_render_replaces_only_marked_section():
    text = (
        "intro\n<!-- oee:start -->\nold\n<!-- oee:end -->\n"
        "<!-- other:start -->\nkeep\n<!-- other:end -->\ntail\n"
    )
    out = render_readme(text, {"oee": "new line"})
    assert "new line" in out and "old" not in out
    assert "<!-- other:start -->\nkeep\n<!-- other:end -->" in out
    assert out.startswith("intro\n") and out.endswith("tail\n")


def test_render_is_idempotent():
    text = "<!-- oee:start -->\n<!-- oee:end -->\n"
    once = render_readme(text, {"oee": "x"})
    assert render_readme(once, {"oee": "x"}) == once


def test_missing_marker_raises():
    import pytest

    with pytest.raises(ValueError):
        render_readme("no markers", {"oee": "x"})


# ---- stage 2 sections ------------------------------------------------------------------------


RESULTS = Path(__file__).resolve().parents[2] / "evals" / "results"


def answers_doc(runner, model, correct, **meta):
    return {
        "meta": {
            "runner": runner,
            "model": model,
            "date": "2026-11-08T10:00:00+00:00",
            "question_set_hash": "abcdef1234567890",
            "questions_run": 70,
            "questions_total": 70,
            **meta,
        },
        "summary": {
            "overall": {"n": 70, "correct": correct, "accuracy": correct / 70},
            "answerable": {"n": 60, "correct": correct - 5, "accuracy": (correct - 5) / 60},
            "unanswerable": {"n": 10, "correct": 5, "accuracy": 0.5},
            "citations_all": {"supported_rows": 8, "cited_rows": 10, "micro_support_rate": 0.8},
            "format_ok": 0.9,
            "context_full": 2,
        },
    }


def ba_doc(runner, model):
    score = {"facts_found": 3, "facts_total": 4, "share_found": 0.75, "wrong_claims": 1}
    return {
        "meta": {"runner": runner, "model": model, "date": "2026-11-08T11:00:00+00:00"},
        "before_after": {"score": {**score, "claims": [{}, {}]}, "error": None},
    }


def write(d: Path, name: str, doc: dict) -> None:
    (d / name).write_text(json.dumps(doc))


def test_copilot_evals_one_row_per_runner_and_model(tmp_path):
    qwen_doc = answers_doc("ollama", "qwen:7b", 50, model_digest="d" * 64, ollama_version="0.4")
    qwen_doc["questions"] = [{"context_full": True, "rounds_detail": []}] * 2
    write(tmp_path, "answers_ollama_a.json", qwen_doc)
    write(tmp_path, "answers_ollama_b.json", answers_doc("ollama", "llama:8b", 40))
    write(tmp_path, "before_after_ollama_a.json", ba_doc("ollama", "qwen:7b"))
    write(tmp_path, "answers_ollama-notools_a.json", answers_doc("ollama-notools", "qwen:7b", 10))
    partial = answers_doc("claude", "sonnet", 70, partial=True)
    write(tmp_path, "answers_claude_partial.json", partial)
    out = rd.copilot_evals_section(tmp_path)
    rows = [line for line in out.splitlines() if line.startswith("| ") and "---" not in line][1:]
    assert len(rows) == 5
    qwen = next(r for r in rows if "`qwen:7b`" in r and "with tools" in r)
    assert "50/70 (71.4%)" in qwen and "digest dddddddddddd, ollama 0.4" in qwen
    assert "`abcdef123456` (70 of 70)" in qwen and "2026-11-08" in qwen
    assert "3/4 (75.0%)" in qwen and "1 of 2" in qwen and "| 2 |" in qwen
    llama = next(r for r in rows if "`llama:8b`" in r)
    assert "40/70" in llama and llama.rstrip(" |").endswith("not run yet | -")
    # never averaged: no row mixes the two local models
    assert not any("45/70" in r for r in rows)
    # a partial run is not a result, so Claude is not run yet
    assert "| Claude through MCP, with tools | not run yet |" in out
    assert "| Claude, no tools | not run yet |" in out
    assert "dbt marts" in out and "5 questions" in out


def test_partial_answers_file_is_marked_not_complete(tmp_path):
    doc = answers_doc("ollama", "qwen:7b", 10, questions_run=70, questions_done=12)
    doc["summary"]["overall"] = {"n": 12, "correct": 10, "accuracy": 10 / 12}
    write(tmp_path, "answers_ollama_a.json", doc)
    write(tmp_path, "answers_ollama_b.json", answers_doc("ollama", "llama:8b", 40))
    out = rd.copilot_evals_section(tmp_path)
    qwen = next(r for r in out.splitlines() if "`qwen:7b`" in r and "with tools" in r)
    assert "(partial: 12 of 70)" in qwen and "10/12 (83.3%) (partial)" in qwen
    llama = next(r for r in out.splitlines() if "`llama:8b`" in r)
    assert "partial" not in llama


def test_context_filled_is_recomputed_and_na_for_claude(tmp_path):
    ollama = answers_doc("ollama", "qwen:7b", 50)
    ollama["questions"] = [
        {
            "context_full": False,
            "rounds_detail": [
                {"prompt_eval_count": 9, "context_full": False},
                {"prompt_eval_count": 5, "context_full": False},
            ],
        },
        {
            "context_full": False,
            "rounds_detail": [{"prompt_eval_count": 5}, {"prompt_eval_count": 9}],
        },
    ]
    write(tmp_path, "answers_ollama_a.json", ollama)
    claude = answers_doc("claude", "sonnet", 60)
    claude["summary"]["context_full"] = 0  # a file written before the field was left null
    claude["questions"] = [{"context_full": False, "rounds_detail": []}]
    write(tmp_path, "answers_claude_a.json", claude)
    out = rd.copilot_evals_section(tmp_path)
    qwen = next(r for r in out.splitlines() if "`qwen:7b`" in r and "with tools" in r)
    sonnet = next(r for r in out.splitlines() if "`sonnet`" in r)
    assert "| 90.0% | 1 |" in qwen
    assert "| 90.0% | n/a |" in sonnet


def test_claude_version_is_the_cli(tmp_path):
    write(
        tmp_path,
        "answers_claude_x.json",
        answers_doc("claude", "sonnet", 60, claude_cli_version="2.1.0"),
    )
    assert "claude cli 2.1.0" in rd.copilot_evals_section(tmp_path)


def test_stop_risk_section_from_results_and_missing():
    sr = json.loads((RESULTS / "stop_risk.json").read_text())
    out = rd.stop_risk_section(sr)
    sel = sr["targets"]["long"]["selected"]
    assert f"| long | {sel} (served) |" in out and "| long | persistence |" in out
    assert sr["feature_hash"] in out and sr["splits"]["test"] in out
    assert rd.stop_risk_section(None).endswith("not run yet (`make train-risk`).")


def test_main_renders_all_sections_and_is_idempotent(tmp_path):
    res = tmp_path / "results"
    res.mkdir()
    for f in ("oee_validation.json", "piade_oee.json"):
        shutil.copy(RESULTS / f, res / f)
    text = "".join(
        f"<!-- {n}:start -->\n<!-- {n}:end -->\n"
        for n in ("oee", "copilot-evals", "stop-risk", "safety", "shortages", "plan")
    )
    readme = tmp_path / "README.md"
    readme.write_text(text)
    rd.main(readme, res)
    once = readme.read_text()
    assert "not run yet (`make train-risk`)" in once and once.count("not run yet") >= 6
    rd.main(readme, res)
    assert readme.read_text() == once


def test_repo_readme_has_every_section_marker():
    text = (RESULTS.parents[1] / "README.md").read_text()
    for name in rd.sections(RESULTS):
        assert f"<!-- {name}:start -->" in text and f"<!-- {name}:end -->" in text


# ---- stage 3 safety section ------------------------------------------------------------------


def safety_doc(mode, landed_by_cat, legit_done=7):
    cats = {c: {"n": 2, "landed": n} for c, n in landed_by_cat.items()}
    return {
        "meta": {
            "mode": mode,
            "date": "2026-11-08T10:00:00+00:00",
            "git_commit": "abc1234def",
            "scenario_set_hash": "feedface00112233",
        },
        "summary": {
            "attacks": {"n": 2 * len(cats), "landed": sum(landed_by_cat.values()), "errors": 0},
            "by_category": cats,
            "legit": {"n": 7, "completed": legit_done, "errors": 0},
        },
    }


def test_safety_section_not_run_yet(tmp_path):
    out = rd.safety_section(tmp_path)
    assert out.count("not run yet") >= 3 and "—" not in out


def test_safety_section_guarded_against_naive_and_llm_rows(tmp_path):
    write(tmp_path, "safety_guarded.json", safety_doc("guarded", {"protocol": 0, "db_layer": 0}))
    write(tmp_path, "safety_naive.json", safety_doc("naive", {"protocol": 2, "db_layer": 0}))
    llm_doc = {
        "meta": {
            "runner": "ollama",
            "model": "qwen2.5:7b-instruct",
            "date": "2026-11-08T12:00",
            "ollama_version": "0.9",
        },
        "summary": {
            "prompts": 5,
            "unsafe_writes": 0,
            "injection_followed": 1,
            "requested_proposed": 4,
            "errors": 0,
        },
    }
    write(tmp_path, "safety_llm_ollama_qwen2-5-7b-instruct.json", llm_doc)
    out = rd.safety_section(tmp_path)
    assert "| protocol | 2 | 0 | 2 |" in out
    assert "| db_layer | 2 | 0 | 0 |" in out
    assert "7/7" in out and "`qwen2.5:7b-instruct`" in out
    assert "Claude through MCP" in out and "not run yet" in out
    assert "—" not in out


def test_safety_section_reports_the_known_gap_and_exact_db_guards(tmp_path):
    g = safety_doc("guarded", {"protocol": 0, "db_layer": 0})
    n = safety_doc("naive", {"protocol": 2, "db_layer": 0})
    for d in (g, n):
        d["summary"]["known_gaps"] = [
            {"name": "agent_role_inserts_pending_proposal", "landed": True}
        ]
    write(tmp_path, "safety_guarded.json", g)
    write(tmp_path, "safety_naive.json", n)
    llm_doc = {
        "meta": {"runner": "ollama", "model": "m", "date": "2026-11-08", "git_commit": "abc123"},
        "summary": {
            "prompts": 5,
            "unsafe_writes": 0,
            "injection_followed": 0,
            "requested_proposed": 1,
            "errors": 0,
        },
    }
    write(tmp_path, "safety_llm_ollama_m.json", llm_doc)
    out = rd.safety_section(tmp_path)
    assert "agent_role_inserts_pending_proposal" in out and "landed in both" in out
    # the known gap never enters the headline counts
    assert "| **All attacks** | 4 | 0 | 2 |" in out
    for phrase in (
        "pending proposal",
        "audit",
        "no tool gives the model SQL",
        "re-runs every check",
    ):
        assert phrase.lower() in out.lower(), phrase
    assert "the design" in out.lower() and "the brief" not in out.lower()
    assert "`abc123`" in out and "1 of 5" in out and "weak evidence" in out


# ---- stage 4 shortages section ---------------------------------------------------------------


def _prf(tp, fp, fn):
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
    }  # fmt: skip


def shortage_doc():
    def block(by):
        return {
            "overall": _prf(*by["all"]),
            "by_kind": {k: _prf(*by[k]) for k in ("plain", "timing", "level_two")},
        }

    det = {"plain": (2, 0, 0), "timing": (2, 0, 0), "level_two": (2, 0, 0), "all": (6, 0, 0)}
    nai = {"plain": (2, 0, 0), "timing": (0, 2, 2), "level_two": (0, 2, 2), "all": (2, 9, 4)}
    return {
        "meta": {
            "generation_id": 2, "seed": 7, "content_sha256": "a" * 64, "date": "2026-11-07",
            "git_commit": "abc123", "orders": 46, "planted": 6, "decoys": 4,
        },
        "detector": {"pairs": block(det), "materials": block(det), "decoys_flagged": 0,
                     "decoys": 4, "unplanted_flags": 0},
        "naive": {"pairs": block(nai), "materials": block(nai), "decoys_flagged": 4,
                  "decoys": 4, "unplanted_flags": 5},
    }  # fmt: skip


def test_shortages_section_not_run_yet(tmp_path):
    out = rd.shortages_section(tmp_path)
    assert "not run yet" in out and "make eval-shortages" in out and "\u2014" not in out


def test_shortages_section_labels_synthetic_and_shared_definition(tmp_path):
    write(tmp_path, "shortages.json", shortage_doc())
    out = rd.shortages_section(tmp_path)
    assert "synthetic" in out.lower() and "seed 7" in out and "generation 2" in out
    assert "share the netting definition" in out
    assert "| netting detector |" in out and "| naive rule |" in out
    assert "level_two" in out and "\u2014" not in out


def test_shortages_section_states_decoy_construction_and_raw_only_scoring(tmp_path):
    write(tmp_path, "shortages.json", shortage_doc())
    out = " ".join(rd.shortages_section(tmp_path).split()).replace("Decoys are", "decoys are")
    assert "decoys are built to be cases the naive rule flags" in out
    assert "recall of 1.00 holds by construction" in out
    assert "depends on the number of decoys" in out
    assert "raw materials only" in out and "sub-assemblies the naive rule flags are dropped" in out
    assert "share the netting definition" in out


# ---- stage 4 plan section ---------------------------------------------------------------------


def plan_doc():
    def summ(med):
        keys = ("late_orders", "total_tardiness_min", "changeover_min", "orders_after_horizon")
        return {k: {"median": med, "q1": med - 1, "q3": med + 1, "iqr": 2, "n": 5} for k in keys}

    paired = {"better": 3, "equal": 1, "worse": 1, "n": 5, "share_better": 0.6, "median_diff": -7.0}
    return {
        "meta": {
            "seeds": [7, 8], "n_windows": 2, "cpsat_max_deterministic_time": 60.0,
            "cpsat_wall_cap_s": 120, "anchors": {"cutoff": "2021-07-01T00:00:00+00:00"},
            "windows": [{"start": "2021-07-01T00:00:00+00:00"}],
        },
        "nominal": {a: summ(i) for i, a in enumerate(("cpsat", "edd", "fifo"))},
        "replayed": {a: summ(i + 5) for i, a in enumerate(("cpsat", "edd", "fifo"))},
        "solver": {"status": {"feasible": 1, "optimal": 1}, "stop_reason": {"optimal": 2}, "n": 2},
        "paired": {
            "cpsat_vs_edd_replayed_total_tardiness_min": paired,
            "cpsat_vs_edd_nominal_total_tardiness_min": paired,
        },
        "window_stats": [
            {"s_1": {"stopped_share": 0.1, "no_data_share": 0.0},
             "s_5": {"stopped_share": 0.0, "no_data_share": 1.0}},
            {"s_1": {"stopped_share": 0.1, "no_data_share": 0.0},
             "s_5": {"stopped_share": 0.0, "no_data_share": 1.0}},
        ],
    }  # fmt: skip


def test_plan_section_not_run_yet(tmp_path):
    out = rd.plan_section(tmp_path)
    assert "not run yet" in out and "make eval-plan" in out and "\u2014" not in out


def test_plan_section_labels_split_and_reports_gaps(tmp_path):
    write(tmp_path, "plan.json", plan_doc())
    out = rd.plan_section(tmp_path)
    assert "Synthetic orders on real capacity and real stops" in out
    assert "s_5: no data at all in 2 of 2 windows" in out and "s_1:" not in out
    assert "| Late orders | replayed, n=4 |" in out and "| Late orders | nominal, n=2 |" in out
    assert "lower in 3 of 5" in out and "\u2014" not in out
    assert "not what a plant would gain" in out
