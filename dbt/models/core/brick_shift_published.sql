-- Published per-shift values: reference only, never used as computed output.
-- shift_id repeats where the file has two rows for one date; date_row separates them.
select
    'brick:' || shift_date::text as shift_id,
    row_number() over (partition by shift_date order by source_file, source_row) as date_row,
    shift_date,
    period,
    oee,
    availability,
    performance,
    quality,
    planned_s,
    good_production_s,
    slow_production_s,
    ideal_qty,
    planned_stops_s,
    unplanned_stops_s,
    good_qty,
    total_qty,
    source_file,
    source_row,
    true as is_reference
from {{ ref('stg_brick_oee') }}
