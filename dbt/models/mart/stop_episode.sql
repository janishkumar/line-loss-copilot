-- One row per stop episode, the unit the loss tools rank and chain.
--
-- Brick: one episode per stop-log row (core.event stop). reason is the stop group,
-- reason_detail the stop name; a failure is stop group FAILURE.
--
-- PIADE: maximal runs of state 'stopped' intervals per machine, where a stopped interval
-- that starts at most 5 s after the previous stopped interval ended joins its episode
-- (gaps and islands over stopped intervals only, so a running blip of up to 5 s between two
-- stops does not split them). Times come from mart.piade_interval_counts, so an interval that
-- overlaps an earlier one is clipped there and no second counts twice. duration_s is the sum
-- of the intervals' seconds, not end - start, so the seconds between them are not counted.
-- reason is the alarm of the first interval ('NO_ALARM' if blank); every episode counts as
-- a failure (the data has no failure flag). idle and scheduled downtime are not stops.
with brick as (
    select
        'brick' as source_system,
        e.line_id,
        e.machine_id,
        e.start_ts,
        e.end_ts,
        e.duration_s,
        e.shift_id,
        e.reason_code as reason,
        e.reason_text as reason_detail,
        e.location,
        e.product,
        '{}'::text[] as alarm_codes,
        e.stop_type,
        coalesce(e.stop_type <> 'Planned - Not included in OEE', true) as in_oee,
        coalesce(e.reason_code = 'FAILURE', false) as is_failure,
        array[e.event_id]::bigint[] as event_ids
    from {{ ref('event') }} e
    where e.source_system = 'brick'
      and e.event_type = 'stop'
),
piade_stopped as (
    select
        i.event_id,
        i.machine_id,
        e.line_id,
        e.shift_id,
        e.alarm_code,
        i.source_row,
        i.start_ts,
        i.end_ts,
        i.start_ts_source,
        i.duration_s,
        -- Latest end among the earlier stopped intervals of the machine.
        max(i.end_ts) over (
            partition by i.machine_id order by i.start_ts_source, i.source_row
            rows between unbounded preceding and 1 preceding
        ) as prev_end
    from {{ ref('piade_interval_counts') }} i
    join {{ ref('event') }} e on e.event_id = i.event_id
    where e.state = 'stopped'
),
piade_islands as (
    select
        *,
        sum(case when prev_end is null or start_ts > prev_end + interval '5 seconds' then 1 else 0 end)
            over (
                partition by machine_id order by start_ts_source, source_row
                rows between unbounded preceding and current row
            ) as island
    from piade_stopped
),
piade as (
    select
        'piade' as source_system,
        min(line_id) as line_id,
        machine_id,
        min(start_ts) as start_ts,
        max(end_ts) as end_ts,
        sum(duration_s) as duration_s,
        (array_agg(shift_id order by start_ts_source, source_row))[1] as shift_id,
        coalesce((array_agg(alarm_code order by start_ts_source, source_row))[1], 'NO_ALARM')
            as reason,
        null::text as reason_detail,
        null::text as location,
        null::text as product,
        coalesce(
            array_agg(distinct alarm_code) filter (where alarm_code is not null), '{}'
        )::text[] as alarm_codes,
        null::text as stop_type,
        true as in_oee,
        true as is_failure,
        array_agg(event_id order by start_ts_source, source_row)::bigint[] as event_ids
    from piade_islands
    group by machine_id, island
),
unioned as (
    select * from brick
    union all
    select * from piade
)
select
    -- The first event of the episode: stable across rebuilds, unique since every stop event
    -- belongs to exactly one episode.
    event_ids[1] as episode_id,
    source_system,
    line_id,
    machine_id,
    start_ts,
    end_ts,
    duration_s::numeric as duration_s,
    shift_id,
    reason,
    reason_detail,
    location,
    product,
    alarm_codes,
    stop_type,
    in_oee,
    is_failure,
    event_ids
from unioned
