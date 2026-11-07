select raw_table, source_file, raw_row_id, count(*)
from {{ ref('note') }}
group by 1, 2, 3 having count(*) > 1
