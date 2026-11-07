-- Brick is one line; each PIADE machine is its own line (R13). Source timezone recorded here.
select
    line_id,
    source_system,
    case source_system when 'brick' then 'Europe/Nicosia' else 'UTC' end as source_timezone,
    min(start_ts) as first_ts,
    max(end_ts) as last_ts,
    count(*) as event_count
from {{ ref('event') }}
group by line_id, source_system
