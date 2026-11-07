-- Estimated ideal rate per PIADE machine (packages per hour; design 5.4). PIADE states no
-- ideal rate, so it is a percentile of `speed` over production rows. Rows with speed 0 are
-- left out of the percentiles (no running speed recorded); n_speed_zero counts them.
-- p95 is the headline; p90 and p99 are the sensitivity cases. max_speed caps the glitch rule.
select
    machine_id,
    percentile_cont(0.90) within group (order by speed) filter (where speed > 0) as p90,
    percentile_cont(0.95) within group (order by speed) filter (where speed > 0) as p95,
    percentile_cont(0.99) within group (order by speed) filter (where speed > 0) as p99,
    max(speed) as max_speed,
    count(*) filter (where speed > 0) as n_production_rows,
    count(*) filter (where speed = 0 or speed is null) as n_speed_zero
from {{ ref('stg_piade_raw') }}
where source_state = 'production'
group by 1
