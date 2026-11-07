-- PIADE intervals: UTC timestamps, counters and speed cast to numbers. Blank alarm becomes null.
select
    source_file,
    source_row,
    machine_id,
    nullif(trim(alarm), '') as alarm,
    state as source_state,
    start_utc::timestamptz as start_ts,
    end_utc::timestamptz as end_ts,
    elapsed_ms::numeric as elapsed_ms,
    nullif(pi, '')::numeric as pi,
    nullif(po, '')::numeric as po,
    nullif(speed, '')::numeric as speed,
    start_raw,
    end_raw
from raw.piade_raw
