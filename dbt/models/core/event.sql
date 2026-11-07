-- One standard event table for both lines (design 5.3). Deterministic event_id (R11).
with brick_stop as (
    select
        'brick' as source_system,
        'brick_downtime' as raw_table,
        d.source_file,
        d.source_row,
        'brick' as line_id,
        null::text as machine_id,
        'stop' as event_type,
        m.state,
        d.start_ts,
        d.end_ts,
        (extract(epoch from d.end_ts - d.start_ts))::numeric as duration_s,
        'brick:' || d.shift_date::text as shift_id,
        d.stop_group as reason_code,
        d.stop as reason_text,
        null::text as alarm_code,
        d.product,
        null::numeric as qty_in,
        null::numeric as qty_out,
        null::numeric as qty_good,
        null::numeric as qty_reject,
        d.location,
        d.stop_type
    from {{ ref('stg_brick_downtime') }} d
    join {{ ref('state_map') }} m on m.source_system = 'brick' and m.source_state = 'stop'
),
brick_oee as (
    select
        'brick' as source_system,
        'brick_oee' as raw_table,
        o.source_file,
        o.source_row,
        'brick' as line_id,
        null::text as machine_id,
        'production_count' as event_type,
        null::text as state,
        s.shift_start as start_ts,
        s.shift_end as end_ts,
        (extract(epoch from s.shift_end - s.shift_start))::numeric as duration_s,
        s.shift_id,
        null::text as reason_code,
        null::text as reason_text,
        null::text as alarm_code,
        null::text as product,
        null::numeric as qty_in,
        o.total_qty as qty_out,
        o.good_qty as qty_good,
        o.total_qty - o.good_qty as qty_reject,
        null::text as location,
        null::text as stop_type
    from {{ ref('stg_brick_oee') }} o
    join {{ ref('shift') }} s on s.shift_id = 'brick:' || o.shift_date::text
),
piade as (
    select
        'piade' as source_system,
        'piade_raw' as raw_table,
        p.source_file,
        p.source_row,
        p.machine_id as line_id,
        p.machine_id,
        'state_interval' as event_type,
        coalesce(m.state, 'unknown') as state,
        p.start_ts,
        p.end_ts,
        p.elapsed_ms / 1000.0 as duration_s,
        'piade:' || p.machine_id || ':' || to_char(
            to_timestamp(floor((extract(epoch from p.start_ts) - 21600) / 28800) * 28800 + 21600)
                at time zone 'UTC', 'YYYY-MM-DD"T"HH24') as shift_id,
        null::text as reason_code,
        null::text as reason_text,
        p.alarm as alarm_code,
        null::text as product,
        null::numeric as qty_in,
        null::numeric as qty_out,
        null::numeric as qty_good,
        null::numeric as qty_reject,
        null::text as location,
        null::text as stop_type
    from {{ ref('stg_piade_raw') }} p
    left join {{ ref('state_map') }} m on m.source_system = 'piade' and m.source_state = p.source_state
),
unioned as (
    select * from brick_stop
    union all select * from brick_oee
    union all select * from piade
)
select
    row_number() over (
        order by source_system, raw_table, source_file, source_row, event_type
    )::bigint as event_id,
    source_file || '#' || source_row::text as event_key,
    source_system,
    line_id,
    machine_id,
    event_type,
    state,
    start_ts,
    end_ts,
    duration_s,
    shift_id,
    reason_code,
    reason_text,
    alarm_code,
    product,
    qty_in,
    qty_out,
    qty_good,
    qty_reject,
    raw_table,
    source_file,
    array[source_row]::int[] as raw_row_ids,
    false as is_synthetic,
    location,
    stop_type
from unioned
