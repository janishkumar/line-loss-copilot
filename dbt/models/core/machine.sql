select
    machine_id,
    line_id,
    source_system,
    min(start_ts) as first_ts,
    max(end_ts) as last_ts,
    count(*) as event_count
from {{ ref('event') }}
where machine_id is not null
group by machine_id, line_id, source_system
