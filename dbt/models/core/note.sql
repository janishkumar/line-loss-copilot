-- One row per brick stop with a non-blank operator note. Text is verbatim.
select
    row_number() over (order by e.event_id)::bigint as note_id,
    e.event_id,
    d.note as original_text,
    case
        when d.note ~ '[Ͱ-Ͽἀ-῿]' then 'el'
        else 'latin'
    end as language,
    e.raw_table,
    d.source_row as raw_row_id,
    d.source_file
from {{ ref('stg_brick_downtime') }} d
join {{ ref('event') }} e
    on e.raw_table = 'brick_downtime' and e.source_file = d.source_file
       and e.event_key = d.source_file || '#' || d.source_row::text
where d.note is not null
