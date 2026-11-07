-- Published per-shift OEE rows (reference values), raw text cast to types.
select
    source_file,
    source_row,
    period,
    shift_date::date as shift_date,
    nullif(oee, '')::numeric as oee,
    nullif(availability, '')::numeric as availability,
    nullif(performance, '')::numeric as performance,
    nullif(quality, '')::numeric as quality,
    nullif(good_production_s, '')::numeric as good_production_s,
    nullif(slow_production_s, '')::numeric as slow_production_s,
    nullif(planned_s, '')::numeric as planned_s,
    nullif(ideal_qty, '')::numeric as ideal_qty,
    nullif(planned_stops_s, '')::numeric as planned_stops_s,
    nullif(unplanned_stops_s, '')::numeric as unplanned_stops_s,
    nullif(good_qty, '')::numeric as good_qty,
    nullif(total_qty, '')::numeric as total_qty
from raw.brick_oee
