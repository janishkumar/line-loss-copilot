"""Print PIADE OEE per machine over its full coverage, from the dbt marts.

Time-weighted from mart.piade_machine_oee (sums of seconds and counts, ratios recomputed),
plus counter reset and glitch counts from mart.piade_interval_counts. Run `make dbt` first.

Usage: PYTHONPATH=src uv run python scripts/piade_oee_summary.py
"""

from __future__ import annotations

import pandas as pd

from linecopilot.config import get_settings
from linecopilot.db import connect

SUMMARY = """
with m as (
    select
        machine_id,
        min(month) as first_month,
        max(month) as last_month,
        sum(n_shifts) as n_shifts,
        sum(n_shifts_counts_excluded) as n_shifts_counts_excluded,
        sum(planned_s) as planned_s,
        sum(run_s) as run_s,
        sum(production_s) as production_s,
        sum(run_s_counted) as run_s_counted,
        sum(input_qty) as input_qty,
        sum(output_qty) as output_qty,
        sum(n_capped) as n_capped,
        sum(n_capped_p90) as n_capped_p90,
        sum(n_capped_p99) as n_capped_p99,
        sum(n_quality_capped) as n_quality_capped
    from mart.piade_machine_oee
    group by 1
),
c as (
    select
        machine_id,
        count(*) filter (where pi_flag = 'reset') as pi_resets,
        count(*) filter (where po_flag = 'reset') as po_resets,
        count(*) filter (where pi_flag = 'glitch') as pi_glitches,
        count(*) filter (where po_flag = 'glitch') as po_glitches,
        count(*) filter (where pi_flag = 'glitch' and is_run) as pi_glitches_run
    from mart.piade_interval_counts
    group by 1
),
z as (
    select
        machine_id,
        count(*) filter (where quality_reason in ('pi_glitch', 'po_glitch')) as n_glitch_shifts,
        sum(run_s) filter (where quality_reason in ('pi_glitch', 'po_glitch')) / 3600.0
            as glitch_run_h,
        count(*) filter (where quality_reason = 'no_input' and run_s > 0) as n_zero_input_run,
        coalesce(sum(run_s) filter (where quality_reason = 'no_input' and run_s > 0), 0)
            / 3600.0 as zero_input_run_h
    from mart.piade_shift_oee
    group by 1
),
o as (
    select machine_id, count(*) filter (where clipped_s > 0) as n_clipped,
        sum(clipped_s) / 3600.0 as clipped_h
    from mart.piade_interval_counts
    group by 1
)
select
    m.machine_id,
    m.first_month,
    m.last_month,
    m.n_shifts,
    round(m.planned_s / 3600.0) as planned_h,
    m.run_s / m.planned_s as a,
    m.input_qty / (r.p95 * m.run_s_counted / 3600.0) as p_count_p95,
    m.input_qty / (r.p90 * m.run_s_counted / 3600.0) as p_count_p90,
    m.input_qty / (r.p99 * m.run_s_counted / 3600.0) as p_count_p99,
    m.production_s / m.run_s as p_time,
    m.output_qty / m.input_qty as q,
    m.run_s / m.planned_s * m.input_qty / (r.p95 * m.run_s_counted / 3600.0)
        * m.output_qty / m.input_qty as oee_p95,
    m.run_s / m.planned_s * m.input_qty / (r.p90 * m.run_s_counted / 3600.0)
        * m.output_qty / m.input_qty as oee_p90,
    m.run_s / m.planned_s * m.input_qty / (r.p99 * m.run_s_counted / 3600.0)
        * m.output_qty / m.input_qty as oee_p99,
    m.run_s / m.planned_s * m.production_s / m.run_s * m.output_qty / m.input_qty as oee_time,
    m.n_capped,
    m.n_capped_p90,
    m.n_capped_p99,
    m.n_quality_capped,
    m.n_shifts_counts_excluded,
    1 - m.run_s_counted / m.run_s as run_share_excluded,
    c.pi_resets,
    c.po_resets,
    c.pi_glitches,
    c.po_glitches,
    c.pi_glitches_run,
    z.n_glitch_shifts,
    z.glitch_run_h,
    z.n_zero_input_run,
    z.zero_input_run_h,
    o.n_clipped,
    o.clipped_h,
    r.p90,
    r.p95,
    r.p99,
    r.max_speed,
    r.n_speed_zero
from m
join c using (machine_id)
join z using (machine_id)
join o using (machine_id)
join mart.piade_ideal_rate r using (machine_id)
order by 1
"""


def main() -> None:
    with connect(get_settings().database_url) as conn:
        cur = conn.execute(SUMMARY)
        cols = [d.name for d in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols).set_index("machine_id")
    for col in df.columns:
        if col not in ("first_month", "last_month"):
            df[col] = pd.to_numeric(df[col])
    pd.set_option("display.width", 200)
    print(df.T.to_string(float_format=lambda v: f"{v:.4f}"))


if __name__ == "__main__":
    main()
