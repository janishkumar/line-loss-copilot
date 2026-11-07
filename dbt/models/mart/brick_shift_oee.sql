-- Brick availability recomputed from the stop log, joined to the published per-shift values
-- (design 5.4, 5.5). The only published input to availability_calc is planned time.
--
-- Stop time: stops whose StopType counts in OEE (everything except
-- "Planned - Not included in OEE"), each interval clipped to its shift date's local day
-- [00:00, 24:00) Europe/Nicosia, then merged with range_agg so overlapping stops count once.
-- stop_s_sum is the plain sum of the same clipped intervals, kept to show the overlap effect.
-- Stop time outside the nominal 07:15-16:00 window is reported, not excluded.
with stop as (
    select
        e.shift_id,
        split_part(e.shift_id, ':', 2)::date as shift_date,
        e.start_ts,
        e.end_ts,
        e.stop_type <> 'Planned - Not included in OEE' as in_oee
    from {{ ref('event') }} e
    where e.source_system = 'brick'
      and e.event_type = 'stop'
),
stop_date as (
    -- Every date with a logged stop, in OEE or not, so no-production days are not dropped.
    select distinct shift_id, shift_date from stop
),
bounded as (
    select
        shift_id,
        shift_date,
        in_oee,
        start_ts,
        end_ts,
        tstzrange(
            greatest(start_ts, shift_date::timestamp at time zone 'Europe/Nicosia'),
            least(end_ts, (shift_date + 1)::timestamp at time zone 'Europe/Nicosia')
        ) as day_r,
        tstzrange(
            (shift_date + time '07:15') at time zone 'Europe/Nicosia',
            (shift_date + time '16:00') at time zone 'Europe/Nicosia'
        ) as nominal_r
    from stop
    -- A stop wholly outside its own date (not seen in the data) adds no time, but its date
    -- still appears through stop_date.
    where start_ts < (shift_date + 1)::timestamp at time zone 'Europe/Nicosia'
      and end_ts > shift_date::timestamp at time zone 'Europe/Nicosia'
),
per_stop as (
    select
        shift_id,
        in_oee,
        day_r,
        extract(epoch from upper(day_r) - lower(day_r)) as clipped_s,
        extract(epoch from end_ts - start_ts) as full_s,
        extract(epoch from upper(day_r) - lower(day_r))
            - coalesce(extract(epoch from upper(day_r * nominal_r) - lower(day_r * nominal_r)), 0)
            as outside_nominal_s
    from bounded
),
stop_shift as (
    select
        shift_id,
        count(*) filter (where in_oee) as n_stops_in_oee,
        range_agg(day_r) filter (where in_oee) as stop_mr,
        coalesce(sum(clipped_s) filter (where in_oee), 0) as stop_s_sum,
        coalesce(sum(clipped_s) filter (where not in_oee), 0) as stop_s_not_included,
        coalesce(sum(full_s - clipped_s) filter (where in_oee), 0) as stop_s_clipped_off,
        count(*) filter (where in_oee and outside_nominal_s > 0) as stops_outside_nominal,
        coalesce(sum(outside_nominal_s) filter (where in_oee), 0) as stop_s_outside_nominal
    from per_stop
    group by 1
),
stop_union as (
    select
        d.shift_id,
        d.shift_date,
        coalesce(s.n_stops_in_oee, 0) as n_stops_in_oee,
        coalesce(s.stop_s_sum, 0) as stop_s_sum,
        coalesce(s.stop_s_not_included, 0) as stop_s_not_included,
        coalesce(s.stop_s_clipped_off, 0) as stop_s_clipped_off,
        coalesce(s.stops_outside_nominal, 0) as stops_outside_nominal,
        coalesce(s.stop_s_outside_nominal, 0) as stop_s_outside_nominal,
        (
            select coalesce(sum(extract(epoch from upper(r) - lower(r))), 0)
            from unnest(s.stop_mr) as r
        ) as stop_s_union
    from stop_date d
    left join stop_shift s using (shift_id)
),
stop_period as (
    select shift_date, min(period) as period
    from {{ ref('stg_brick_downtime') }}
    group by 1
),
published as (
    select * from {{ ref('brick_shift_published') }} where date_row = 1
),
joined as (
    select
        coalesce(p.shift_id, u.shift_id) as shift_id,
        coalesce(p.shift_date, u.shift_date) as shift_date,
        coalesce(p.period, sp.period) as period,
        coalesce(u.stop_s_union, 0) as stop_s_union,
        coalesce(u.stop_s_sum, 0) as stop_s_sum,
        coalesce(u.stop_s_not_included, 0) as stop_s_not_included,
        coalesce(u.stop_s_clipped_off, 0) as stop_s_clipped_off,
        coalesce(u.stops_outside_nominal, 0) as stops_outside_nominal,
        coalesce(u.stop_s_outside_nominal, 0) as stop_s_outside_nominal,
        p.planned_s as planned_s_published,
        p.planned_s - p.good_production_s - p.slow_production_s as stop_s_implied_pub,
        p.availability as availability_pub,
        p.performance as performance_pub,
        p.quality as quality_pub,
        p.oee as oee_pub,
        case
            when p.shift_id is null then 'no_published'
            when coalesce(u.n_stops_in_oee, 0) = 0 then 'no_stops'
            else 'matched'
        end as match_status
    from published p
    full outer join stop_union u on u.shift_id = p.shift_id
    left join stop_period sp on sp.shift_date = coalesce(p.shift_date, u.shift_date)
),
calc as (
    select
        *,
        1 - stop_s_union / nullif(planned_s_published, 0) as availability_calc
    from joined
)
select
    shift_id,
    shift_date,
    period,
    stop_s_union,
    stop_s_sum,
    stop_s_not_included,
    stop_s_clipped_off,
    stops_outside_nominal,
    stop_s_outside_nominal,
    planned_s_published,
    stop_s_implied_pub,
    availability_calc,
    availability_pub,
    availability_calc - availability_pub as availability_gap,
    performance_pub,
    quality_pub,
    availability_calc * performance_pub * quality_pub as oee_calc_with_pub_pq,
    oee_pub,
    availability_calc * performance_pub * quality_pub - oee_pub as oee_gap,
    match_status
from calc
