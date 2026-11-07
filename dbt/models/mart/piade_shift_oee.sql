-- PIADE OEE per machine and assumed shift (design 5.4). Each machine is its own line (R13).
--
-- Shifts: 3 x 8 h UTC from 06:00 (assumed calendar, same slots as core.shift). An interval
-- that crosses a shift boundary is split by time share; its seconds and its counter deltas
-- are split in the same proportion.
--
-- planned_s   = all states except scheduled_downtime (state_map.is_planned)
-- run_s       = production + performance_loss (state_map.is_run)
-- input_qty   = valid pi deltas on run rows; output_qty = valid po deltas on run rows
-- availability          = run_s / planned_s
-- performance_count_pXX = input_qty / (ideal rate pXX x run hours), capped at 1; the
--                         uncapped p95 value is kept and n_capped flags a capped shift
-- performance_time      = production_s / run_s (cross-check, no ideal rate needed)
-- quality               = output_qty / input_qty, capped at 1 (quality_raw kept,
--                         n_quality_capped flags it). Output can exceed input within one
--                         shift when packages counted in late in the previous shift come out
--                         in this one; the excess is small (median 0.07% on capped shifts).
-- oee                   = availability x performance_count_p95 x quality (p90, p99 alongside)
--
-- Performance counts total input (pi), not good output, and quality is output / input, as
-- in design 5.4, so rejected packages lower quality only and are not counted twice.
--
-- Capping uses case, not least(): least() ignores nulls and would turn a null into 1.
--
-- quality_reason says why the counts are incomplete: 'pi_glitch' or 'po_glitch' when a
-- counter delta on a run row in the shift was dropped as a glitch, 'no_input' when no input
-- was counted (including shifts that ran but whose counter never moved). With any reason,
-- quality, count-based performance and oee are null. A shift that was planned but never ran
-- has availability 0 and oee 0.
with iv as (
    select
        c.*,
        floor((extract(epoch from c.start_ts) - 21600) / 28800)::bigint as first_slot,
        greatest(
            floor((extract(epoch from c.start_ts) - 21600) / 28800),
            ceil((extract(epoch from c.end_ts) - 21600) / 28800) - 1
        )::bigint as last_slot
    from {{ ref('piade_interval_counts') }} c
),
piece as (
    select
        iv.*,
        to_timestamp(g.slot * 28800 + 21600) as shift_start,
        to_timestamp(g.slot * 28800 + 21600 + 28800) as shift_end
    from iv
    cross join lateral generate_series(iv.first_slot, iv.last_slot) as g(slot)
),
shared as (
    select
        machine_id,
        'piade:' || machine_id || ':'
            || to_char(shift_start at time zone 'UTC', 'YYYY-MM-DD"T"HH24') as shift_id,
        shift_start,
        shift_end,
        source_state,
        is_planned,
        is_run,
        pi_flag,
        po_flag,
        case
            when end_ts > start_ts then
                extract(epoch from least(end_ts, shift_end) - greatest(start_ts, shift_start))
                / extract(epoch from end_ts - start_ts)
            else 1
        end as share,
        duration_s,
        pi_delta,
        po_delta
    from piece
),
agg as (
    select
        machine_id,
        shift_id,
        shift_start,
        shift_end,
        count(*) as n_pieces,
        coalesce(sum(duration_s * share) filter (where is_planned), 0) as planned_s,
        coalesce(sum(duration_s * share) filter (where is_run), 0) as run_s,
        coalesce(sum(duration_s * share) filter (where source_state = 'production'), 0)
            as production_s,
        coalesce(sum(duration_s * share) filter (where source_state = 'performance_loss'), 0)
            as perf_loss_s,
        coalesce(sum(duration_s * share) filter (where source_state = 'downtime'), 0)
            as downtime_s,
        coalesce(sum(duration_s * share) filter (where source_state = 'idle'), 0) as idle_s,
        coalesce(sum(duration_s * share) filter (where not is_planned), 0) as scheduled_s,
        coalesce(sum(pi_delta * share) filter (where is_run), 0) as input_qty,
        coalesce(sum(po_delta * share) filter (where is_run), 0) as output_qty,
        count(*) filter (where is_run and pi_flag = 'glitch') as n_pi_glitch_run,
        count(*) filter (where is_run and po_flag = 'glitch') as n_po_glitch_run,
        count(*) filter (where is_run and (pi_flag = 'reset' or po_flag = 'reset'))
            as n_reset_run
    from shared
    group by 1, 2, 3, 4
),
ratio as (
    select
        a.*,
        r.p90,
        r.p95,
        r.p99,
        case
            when a.n_pi_glitch_run > 0 then 'pi_glitch'
            when a.n_po_glitch_run > 0 then 'po_glitch'
            when a.input_qty = 0 then 'no_input'
        end as quality_reason,
        a.run_s / nullif(a.planned_s, 0) as availability,
        a.production_s / nullif(a.run_s, 0) as performance_time
    from agg a
    join {{ ref('piade_ideal_rate') }} r using (machine_id)
),
perf as (
    select
        *,
        case when quality_reason is null
            then input_qty / nullif(p95 * run_s / 3600.0, 0) end as p95_raw,
        case when quality_reason is null
            then input_qty / nullif(p90 * run_s / 3600.0, 0) end as p90_raw,
        case when quality_reason is null
            then input_qty / nullif(p99 * run_s / 3600.0, 0) end as p99_raw,
        case when quality_reason is null then output_qty / input_qty end as quality_raw
    from ratio
),
capped as (
    select
        *,
        (case when p95_raw > 1 then 1 else p95_raw end) as performance_count_p95,
        (case when p90_raw > 1 then 1 else p90_raw end) as performance_count_p90,
        (case when p99_raw > 1 then 1 else p99_raw end) as performance_count_p99,
        (case when quality_raw > 1 then 1 else quality_raw end) as quality
    from perf
)
select
    machine_id,
    shift_id,
    shift_start,
    shift_end,
    planned_s,
    run_s,
    production_s,
    perf_loss_s,
    downtime_s,
    idle_s,
    scheduled_s,
    output_qty,
    input_qty,
    availability,
    performance_count_p95,
    performance_count_p90,
    performance_count_p99,
    p95_raw as performance_count_p95_raw,
    performance_time,
    quality,
    quality_raw,
    case when availability = 0 then 0
         else availability * performance_count_p95 * quality end as oee,
    case when availability = 0 then 0
         else availability * performance_count_p90 * quality end as oee_p90,
    case when availability = 0 then 0
         else availability * performance_count_p99 * quality end as oee_p99,
    coalesce((p95_raw > 1)::int, 0) as n_capped,
    coalesce((p90_raw > 1)::int, 0) as n_capped_p90,
    coalesce((p99_raw > 1)::int, 0) as n_capped_p99,
    coalesce((quality_raw > 1)::int, 0) as n_quality_capped,
    quality_reason,
    n_pi_glitch_run,
    n_po_glitch_run,
    n_reset_run,
    n_pieces
from capped
