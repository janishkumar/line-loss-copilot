-- Splitting intervals across shifts must neither lose nor add time.
with iv as (
    select machine_id, sum(duration_s) as s from {{ ref('piade_interval_counts') }} group by 1
),
sh as (
    select machine_id, sum(planned_s + scheduled_s) as s
    from {{ ref('piade_shift_oee') }} group by 1
)
select iv.machine_id, iv.s, sh.s
from iv full outer join sh using (machine_id)
where abs(coalesce(iv.s, 0) - coalesce(sh.s, 0)) > 1e-3
