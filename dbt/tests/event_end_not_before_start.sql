select event_id from {{ ref('event') }} where end_ts < start_ts
