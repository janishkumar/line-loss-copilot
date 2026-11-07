-- PIADE counter deltas per interval, one row per core.event state interval.
--
-- pi and po are running counters. A reading belongs to the end of its row, so the delta
-- x[i] - x[i-1] is attributed to row i (end alignment). scripts/probe_piade_counts.py chose
-- it: 94 to 98% of valid po counts land on run rows, against 69 to 89% for start alignment.
-- The start-aligned delta x[i+1] - x[i] is kept in *_delta_start for comparison only.
--
-- Rule: negative delta = reset, delta > 3 x max_speed x row hours = glitch; both null.
-- Rows are ordered by start time, then file row, within each machine. A delta that spans a
-- gap between rows is attributed to the later row like any other.
--
-- Overlaps: an interval that starts before an earlier interval of the same machine has ended
-- (by start order) has its start clipped to that end, so no second is counted twice.
-- start_ts_source and duration_s_source keep the logged values; clipped_s is what was cut
-- (a fully covered interval keeps its counter delta and gets duration 0). The glitch limit
-- uses the logged duration.
with iv as (
    select
        e.event_id,
        e.event_key,
        e.source_file,
        p.source_row,
        e.machine_id,
        p.source_state,
        m.is_planned,
        m.is_run,
        e.start_ts,
        e.end_ts,
        e.duration_s,
        p.pi,
        p.po,
        p.speed
    from {{ ref('event') }} e
    join {{ ref('stg_piade_raw') }} p
        on p.source_file = e.source_file and p.source_row = e.raw_row_ids[1]
    join {{ ref('state_map') }} m
        on m.source_system = 'piade' and m.source_state = p.source_state
    where e.source_system = 'piade'
      and e.event_type = 'state_interval'
),
prev as (
    select
        iv.*,
        max(iv.end_ts) over (
            partition by iv.machine_id order by iv.start_ts, iv.source_row
            rows between unbounded preceding and 1 preceding
        ) as prev_end
    from iv
),
clipped as (
    select
        prev.*,
        least(greatest(start_ts, coalesce(prev_end, start_ts)), end_ts) as start_clip
    from prev
),
raw_delta as (
    select
        iv.*,
        3 * r.max_speed * iv.duration_s / 3600.0 as glitch_limit,
        iv.pi - lag(iv.pi) over w as pi_raw,
        iv.po - lag(iv.po) over w as po_raw,
        lead(iv.pi) over w - iv.pi as pi_raw_start,
        lead(iv.po) over w - iv.po as po_raw_start
    from clipped iv
    join {{ ref('piade_ideal_rate') }} r using (machine_id)
    window w as (partition by iv.machine_id order by iv.start_ts, iv.source_row)
)
select
    event_id,
    event_key,
    source_file,
    source_row,
    machine_id,
    source_state,
    is_planned,
    is_run,
    start_clip as start_ts,
    end_ts,
    case
        when start_clip > start_ts then extract(epoch from end_ts - start_clip)
        else duration_s
    end as duration_s,
    start_ts as start_ts_source,
    duration_s as duration_s_source,
    case
        when start_clip > start_ts then duration_s - extract(epoch from end_ts - start_clip)
        else 0
    end as clipped_s,
    pi,
    po,
    speed,
    glitch_limit,
    {{ counter_delta('pi_raw', 'glitch_limit') }} as pi_delta,
    {{ counter_delta('po_raw', 'glitch_limit') }} as po_delta,
    {{ counter_flag('pi_raw', 'glitch_limit') }} as pi_flag,
    {{ counter_flag('po_raw', 'glitch_limit') }} as po_flag,
    {{ counter_delta('pi_raw_start', 'glitch_limit') }} as pi_delta_start,
    {{ counter_delta('po_raw_start', 'glitch_limit') }} as po_delta_start
from raw_delta
