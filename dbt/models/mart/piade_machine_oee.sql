-- PIADE OEE per machine and calendar month (UTC, by shift start). Time-weighted: seconds and
-- counts are summed over shifts and the ratios recomputed, never averaged.
--
-- Count-based performance and quality use only shifts whose counts are complete
-- (quality_reason not 'pi_glitch' or 'po_glitch'); run_s_counted is the run time behind them.
-- Monthly count-based performance is capped at 1; n_capped is the number of capped shifts
-- (p95) in the month, month_capped flags the month value itself. Quality is capped at 1 the
-- same way (n_quality_capped counts capped shifts).
with s as (
    select
        *,
        quality_reason is distinct from 'pi_glitch'
            and quality_reason is distinct from 'po_glitch' as counts_ok
    from {{ ref('piade_shift_oee') }}
),
agg as (
    select
        machine_id,
        (date_trunc('month', shift_start at time zone 'UTC'))::date as month,
        count(*) as n_shifts,
        count(*) filter (where not counts_ok) as n_shifts_counts_excluded,
        sum(planned_s) as planned_s,
        sum(run_s) as run_s,
        sum(production_s) as production_s,
        sum(perf_loss_s) as perf_loss_s,
        sum(downtime_s) as downtime_s,
        sum(idle_s) as idle_s,
        sum(scheduled_s) as scheduled_s,
        sum(run_s) filter (where counts_ok) as run_s_counted,
        sum(input_qty) filter (where counts_ok) as input_qty,
        sum(output_qty) filter (where counts_ok) as output_qty,
        sum(n_capped) as n_capped,
        sum(n_capped_p90) as n_capped_p90,
        sum(n_capped_p99) as n_capped_p99,
        sum(n_quality_capped) as n_quality_capped
    from s
    group by 1, 2
),
ratio as (
    select
        a.*,
        a.run_s / nullif(a.planned_s, 0) as availability,
        a.production_s / nullif(a.run_s, 0) as performance_time,
        a.input_qty / nullif(r.p95 * a.run_s_counted / 3600.0, 0) as p95_raw,
        a.input_qty / nullif(r.p90 * a.run_s_counted / 3600.0, 0) as p90_raw,
        a.input_qty / nullif(r.p99 * a.run_s_counted / 3600.0, 0) as p99_raw,
        a.output_qty / nullif(a.input_qty, 0) as quality_raw
    from agg a
    join {{ ref('piade_ideal_rate') }} r using (machine_id)
),
capped as (
    -- case, not least(): least() ignores nulls and would turn a null into 1.
    select
        *,
        case when p95_raw > 1 then 1 else p95_raw end as p95_c,
        case when p90_raw > 1 then 1 else p90_raw end as p90_c,
        case when p99_raw > 1 then 1 else p99_raw end as p99_c,
        case when quality_raw > 1 then 1 else quality_raw end as quality
    from ratio
)
select
    machine_id,
    month,
    n_shifts,
    n_shifts_counts_excluded,
    planned_s,
    run_s,
    production_s,
    perf_loss_s,
    downtime_s,
    idle_s,
    scheduled_s,
    run_s_counted,
    input_qty,
    output_qty,
    availability,
    p95_c as performance_count_p95,
    p90_c as performance_count_p90,
    p99_c as performance_count_p99,
    p95_raw as performance_count_p95_raw,
    performance_time,
    quality,
    quality_raw,
    case when availability = 0 then 0 else availability * p95_c * quality end as oee,
    case when availability = 0 then 0 else availability * p90_c * quality end as oee_p90,
    case when availability = 0 then 0 else availability * p99_c * quality end as oee_p99,
    n_capped,
    n_capped_p90,
    n_capped_p99,
    n_quality_capped,
    coalesce(p95_raw > 1, false) as month_capped
from capped
