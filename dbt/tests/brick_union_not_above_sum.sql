-- Merging overlapping stop intervals can only shrink stop time, never grow it.
select shift_id, stop_s_union, stop_s_sum
from {{ ref('brick_shift_oee') }}
where stop_s_union > stop_s_sum + 1e-6
