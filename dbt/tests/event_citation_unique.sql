select raw_table, source_file, raw_row_ids[1], event_type, count(*)
from {{ ref('event') }}
group by 1, 2, 3, 4 having count(*) > 1
