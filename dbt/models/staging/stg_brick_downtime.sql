-- Brick stop log: raw text cast to types. Local times are Europe/Nicosia (R12).
select
    source_file,
    source_row,
    period,
    shift_date::date as shift_date,
    nullif(trim(product), '') as product,
    nullif(trim(stop_group), '') as stop_group,
    nullif(trim(stop), '') as stop,
    nullif(trim(stop_type), '') as stop_type,
    case when trim(coalesce(location, '')) in ('', '-') then null else trim(location) end as location,
    case when trim(coalesce(note, '')) in ('', '-') then null else note end as note,
    start_local::timestamp as start_local,
    end_local::timestamp as end_local,
    (start_local::timestamp at time zone 'Europe/Nicosia') as start_ts,
    (end_local::timestamp at time zone 'Europe/Nicosia') as end_ts,
    duration_min::numeric as duration_min
from raw.brick_downtime
