"""Render README sections from evals/results/*.json. `make report` runs this."""

from __future__ import annotations

import json
import re
from pathlib import Path

from linecopilot.reports.oee_validation import PERIODS, RESULTS, _pct, _pts


def render_readme(readme_text: str, sections: dict[str, str]) -> str:
    """Replace the content between <!-- name:start --> and <!-- name:end --> for each section."""
    out = readme_text
    for name, body in sections.items():
        pat = re.compile(
            rf"(<!-- {re.escape(name)}:start -->\n).*?(<!-- {re.escape(name)}:end -->)", re.S
        )
        if not pat.search(out):
            raise ValueError(f"README has no markers for section {name!r}")
        repl = body.rstrip("\n") + "\n"
        out = pat.sub(lambda m, repl=repl: m.group(1) + repl + m.group(2), out, count=1)
    return out


def oee_section(val: dict, piade: list[dict]) -> str:
    L: list[str] = []
    L += [
        "### Brick line: recomputed availability against published",
        "",
        "Availability is recomputed from the stop log (planned time minus the union of in-OEE "
        "stop intervals, clipped to the date). Planned time is the one published input. "
        "Gap = recomputed minus published, in percentage points, over every shift with both "
        "stops and a published row. Nothing is filtered.",
        "",
        "| Period | Window | Matched shifts | Mean abs gap | Median abs gap | Max abs gap | Within 2 pts | Within 5 pts | Mean signed |",  # noqa: E501
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for p in PERIODS:
        s, g, w = val["periods"][p], val["periods"][p]["availability"], val["windows"][p]
        L.append(
            f"| {p} | {w['first']} to {w['last']} | {s['n_matched']} | {_pts(g['mean_abs'])} pts "
            f"| {_pts(g['median_abs'])} pts | {_pts(g['max_abs'])} pts "
            f"| {_pct(g['share_within_2pts'])} | {_pct(g['share_within_5pts'])} "
            f"| {_pts(g['mean_signed'])} pts |"
        )
    L += [""]
    for p in PERIODS:
        s = val["periods"][p]
        L.append(
            f"- {p}: {s['n_published']} published shifts, {s['n_matched']} matched, "
            f"{s['n_no_stops']} with no stops, {s['n_no_published']} stop-only days with no "
            "published row (shown, not dropped)."
        )
    L += [
        "",
        "Breakdown chosen after seeing the gaps (the 9 h threshold was picked once the "
        "October block stood out, so read it as explanation, not as a better headline):",
        "",
        "| Period | Planned-day length | Shifts | Mean abs gap | Median abs gap |",
        "|---|---|---|---|---|",
    ]
    for p in PERIODS:
        for key, name in (("planned_over_9h", "over 9 h"), ("planned_9h_or_less", "9 h or less")):
            g = val["post_hoc_split"][p][key]
            L.append(
                f"| {p} | {name} | {g['n']} | {_pts(g['mean_abs'])} pts "
                f"| {_pts(g['median_abs'])} pts |"
            )
    L += [
        "",
        "### Brick line: full OEE with published performance and quality",
        "",
        "Availability is recomputed; performance and quality are the published values (the "
        "files hold no event-level counts to recompute them from). The published P and Q enter "
        "this comparison as given. Same shifts and windows as above.",
        "",
        "| Period | Window | Matched shifts | Mean abs gap | Median abs gap | Max abs gap | Within 2 pts | Within 5 pts |",  # noqa: E501
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in PERIODS:
        s, g, w = val["periods"][p], val["periods"][p]["oee"], val["windows"][p]
        L.append(
            f"| {p} | {w['first']} to {w['last']} | {g['n']} | {_pts(g['mean_abs'])} pts "
            f"| {_pts(g['median_abs'])} pts | {_pts(g['max_abs'])} pts "
            f"| {_pct(g['share_within_2pts'])} | {_pct(g['share_within_5pts'])} |"
        )
    L += [
        "",
        "### PIADE: OEE per machine over full coverage",
        "",
        "Each machine is its own line. Time-weighted: seconds and counts are summed, then ratios "
        "computed. Windows are each machine's first to last assumed shift (UTC). The ideal rate "
        "is estimated from `speed`, so OEE is shown at p90, p95 (headline) and p99. P is "
        "count-based; time-based P is the cross-check.",
        "",
        "| Machine | Window | Planned h | A | P count (p95) | P time | Q | OEE p90 | OEE p95 | OEE p99 |",  # noqa: E501
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in piade:
        L.append(
            f"| {r['machine_id']} | {r['first_shift']} to {r['last_shift']} "
            f"| {r['planned_h']:,.0f} "
            f"| {r['a']:.3f} | {r['p_count_p95']:.3f} | {r['p_time']:.3f} | {r['q']:.3f} "
            f"| {r['oee_p90']:.3f} | {r['oee_p95']:.3f} | {r['oee_p99']:.3f} |"
        )
    L += [
        "",
        "These PIADE figures have no published value to check against; they are computed, not "
        "validated. Brick and PIADE numbers are never combined.",
        "",
        "Assumptions:",
        "",
        "- PIADE shifts are 3 x 8 h in UTC from 06:00, because the data gives no site timezone.",
        "- Idle counts as planned time; scheduled downtime does not.",
        "- P uses total input (`pi`) over ideal rate times run hours, with the ideal rate a "
        "percentile of observed set speed.",
        "- Q is output over input, capped at 1 per shift.",
        "- Counters are end-aligned (a reading belongs to the row it ends); resets and glitches "
        "are dropped.",
        "- Shifts with a counter glitch on a run row, or run time with no input counted, are "
        "left out of count-based P and Q; A and time-based P keep them.",
        "- Brick planned time and, in the OEE comparison, published P and Q are published inputs.",
        "",
        "Details and the reasoning behind each choice are in `docs/data-notes.md`. "
        "Regenerate with `make validate-oee && make report`.",
    ]
    return "\n".join(L)


def main(readme: Path = Path("README.md"), results: Path = RESULTS) -> None:
    val = json.loads((results / "oee_validation.json").read_text(encoding="utf-8"))
    piade = json.loads((results / "piade_oee.json").read_text(encoding="utf-8"))
    text = readme.read_text(encoding="utf-8")
    readme.write_text(render_readme(text, {"oee": oee_section(val, piade)}), encoding="utf-8")


if __name__ == "__main__":
    main()
