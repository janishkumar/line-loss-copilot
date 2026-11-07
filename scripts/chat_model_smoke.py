"""Smoke test of local chat models: 8 fixed questions that each need one or two tools.

For every model, each question scores one point each for: every tool call valid (known tool,
JSON arguments that pass validation), the expected tool(s) called, and a final answer with an
`ANSWER:` line. The model with the most points wins; ties go to the faster model. Runs live
against Ollama and the loaded database, so it takes a few minutes.

Usage: PYTHONPATH=src uv run python scripts/chat_model_smoke.py [--models a b]
Writes evals/results/chat_model_smoke.json.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from linecopilot.chat.loop import run_chat
from linecopilot.chat.ollama import OllamaClient
from linecopilot.config import get_settings

OUT = Path(__file__).resolve().parents[1] / "evals" / "results" / "chat_model_smoke.json"
CANDIDATES = ["qwen2.5:7b-instruct", "llama3.1:8b-instruct-q4_K_M"]
PROMPTS: list[tuple[str, str, list[str]]] = [
    (
        "pareto_s1",
        "What was the top stop reason by lost time on machine s_1 in March 2021?",
        ["loss_pareto"],
    ),
    ("oee_brick", "What was the OEE of the brick line in October 2025?", ["get_oee"]),
    ("mttr_s2", "What was the MTTR of machine s_2 in 2021?", ["reliability"]),
    ("notes_valves", "Find operator notes that mention valves.", ["search_notes"]),
    (
        "list_machines",
        "Which lines and machines are loaded, and what dates do they cover?",
        ["list_assets"],
    ),
    ("risk_s4", "What is the long-stop risk for machine s_4 at 2021-11-15 08:00?", ["stop_risk"]),
    (
        "compare_brick",
        "Compare the brick line's stop time between September to December 2025 and January "
        "to April 2026.",
        ["compare_periods"],
    ),
    (
        "events_then_mtbf",
        "Which PIADE machine has the most events loaded, and what is its MTBF over its whole "
        "coverage?",
        ["list_assets", "reliability"],
    ),
]
BAD_CALL = ("unknown tool", "invalid arguments", "arguments were not valid JSON", "arguments must")
ANSWER_LINE = re.compile(r"ANSWER:\s*\S")  # own line or trailing; the UI hides both


def score_one(conn, client: OllamaClient, prompt: str, expected: list[str]) -> dict:
    t0 = time.perf_counter()
    try:
        res = run_chat(conn, client, [{"role": "user", "content": prompt}])
    except Exception as e:  # a model that breaks the loop scores zero on that prompt
        return {
            "error": f"{type(e).__name__}: {e}",
            "wall_s": round(time.perf_counter() - t0, 1),
            "valid_tool_json": False,
            "correct_tool": False,
            "answer_present": False,
            "points": 0,
        }
    wall = time.perf_counter() - t0
    names = [c.name for c in res.tool_calls]
    valid = bool(names) and not any((c.missing or "").startswith(BAD_CALL) for c in res.tool_calls)
    correct = all(e in names for e in expected)
    answered = bool(ANSWER_LINE.search(res.answer))
    return {
        "valid_tool_json": valid,
        "correct_tool": correct,
        "answer_present": answered,
        "points": int(valid) + int(correct) + int(answered),
        "wall_s": round(wall, 1),
        "rounds": res.rounds,
        "tool_calls": [c.model_dump() for c in res.tool_calls],
        "cited_event_ids": res.cited_event_ids,
        "unsupported_cited_ids": res.unsupported_cited_ids,
        "answer": res.answer[:600],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=CANDIDATES)
    args = ap.parse_args()
    s = get_settings()
    models = []
    with psycopg.connect(s.database_url, autocommit=True) as conn:
        for model in args.models:
            client = OllamaClient(s.ollama_url, model)
            digest = next((m.get("digest") for m in client.tags() if m.get("name") == model), None)
            results = []
            for pid, prompt, expected in PROMPTS:
                r = score_one(conn, client, prompt, expected)
                print(f"{model} {pid}: {r['points']}/3 in {r['wall_s']} s", flush=True)
                results.append({"id": pid, "prompt": prompt, "expected_tools": expected, **r})
            client.close()
            models.append(
                {
                    "model": model,
                    "digest": digest,
                    "points": sum(r["points"] for r in results),
                    "max_points": 3 * len(PROMPTS),
                    "wall_s_total": round(sum(r["wall_s"] for r in results), 1),
                    "results": results,
                }
            )
    chosen = min(models, key=lambda m: (-m["points"], m["wall_s_total"]))["model"]
    out = {
        "generated_at": datetime.now(UTC).date().isoformat(),
        "ollama_url": s.ollama_url,
        "rule": "most points (valid tool JSON + expected tool + ANSWER line, per prompt); "
        "ties go to the lower total wall time",
        "chosen": chosen,
        "models": models,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for m in models:
        print(f"{m['model']}: {m['points']}/{m['max_points']}, {m['wall_s_total']} s")
    print(f"chosen: {chosen}")


if __name__ == "__main__":
    main()
