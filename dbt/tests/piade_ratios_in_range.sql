-- PIADE availability, capped performance, quality and OEE must lie in [0, 1].
select machine_id, shift_id, availability, performance_count_p95, quality, oee
from {{ ref('piade_shift_oee') }}
where availability not between 0 and 1
   or performance_count_p95 not between 0 and 1
   or quality not between 0 and 1
   or oee not between 0 and 1
