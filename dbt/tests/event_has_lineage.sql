select event_id from {{ ref('event') }}
where raw_row_ids is null or cardinality(raw_row_ids) = 0
