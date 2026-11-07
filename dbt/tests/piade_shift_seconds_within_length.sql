-- After overlap clipping, a shift can hold at most its own length in seconds.
select machine_id, shift_id, planned_s + scheduled_s as total_s
from {{ ref('piade_shift_oee') }}
where planned_s + scheduled_s > extract(epoch from shift_end - shift_start) + 1e-3
