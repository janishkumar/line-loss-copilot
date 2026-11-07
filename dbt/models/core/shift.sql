-- Brick: one derived shift per date, 07:15 to 16:00 local widened to cover that date's stops.
-- PIADE: assumed 3 x 8 h UTC calendar (06:00, 14:00, 22:00) from each machine's first to last interval.
with brick_dates as (
    select shift_date from {{ ref('stg_brick_oee') }}
    union
    select shift_date from {{ ref('stg_brick_downtime') }}
),
brick_stops as (
    select shift_date, min(start_ts) as first_start, max(end_ts) as last_end
    from {{ ref('stg_brick_downtime') }}
    group by 1
),
brick as (
    select
        'brick:' || d.shift_date::text as shift_id,
        'brick' as line_id,
        least(
            (d.shift_date + time '07:15') at time zone 'Europe/Nicosia',
            coalesce(s.first_start, (d.shift_date + time '07:15') at time zone 'Europe/Nicosia')
        ) as shift_start,
        greatest(
            (d.shift_date + time '16:00') at time zone 'Europe/Nicosia',
            coalesce(s.last_end, (d.shift_date + time '16:00') at time zone 'Europe/Nicosia')
        ) as shift_end,
        'derived' as source
    from brick_dates d
    left join brick_stops s using (shift_date)
),
piade_cov as (
    select
        machine_id,
        floor((extract(epoch from min(start_ts)) - 21600) / 28800) as first_slot,
        -- Last slot covers the end of the last interval, so a split never lands outside it.
        greatest(
            floor((extract(epoch from max(start_ts)) - 21600) / 28800),
            ceil((extract(epoch from max(end_ts)) - 21600) / 28800) - 1
        ) as last_slot
    from {{ ref('stg_piade_raw') }}
    group by 1
),
piade as (
    select
        'piade:' || c.machine_id || ':'
            || to_char(to_timestamp(g.slot * 28800 + 21600) at time zone 'UTC', 'YYYY-MM-DD"T"HH24') as shift_id,
        c.machine_id as line_id,
        to_timestamp(g.slot * 28800 + 21600) as shift_start,
        to_timestamp(g.slot * 28800 + 21600 + 28800) as shift_end,
        'assumed_calendar' as source
    from piade_cov c
    cross join lateral generate_series(c.first_slot::bigint, c.last_slot::bigint) as g(slot)
)
select * from brick
union all
select * from piade
