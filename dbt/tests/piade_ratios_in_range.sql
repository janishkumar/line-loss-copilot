-- PIADE availability, capped performance (p90/p95/p99), quality and OEE must lie in [0, 1],
-- per shift and per month.
with r as (
    select 'shift' as grain, machine_id, shift_id as id, availability, performance_count_p90,
        performance_count_p95, performance_count_p99, quality, oee, oee_p90, oee_p99
    from {{ ref('piade_shift_oee') }}
    union all
    select 'month', machine_id, month::text, availability, performance_count_p90,
        performance_count_p95, performance_count_p99, quality, oee, oee_p90, oee_p99
    from {{ ref('piade_machine_oee') }}
)
select * from r
where availability not between 0 and 1
   or performance_count_p90 not between 0 and 1
   or performance_count_p95 not between 0 and 1
   or performance_count_p99 not between 0 and 1
   or quality not between 0 and 1
   or oee not between 0 and 1
   or oee_p90 not between 0 and 1
   or oee_p99 not between 0 and 1
