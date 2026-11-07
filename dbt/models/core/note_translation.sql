-- Empty by design in stage 1; stage 2 fills it with machine translations.
select
    null::bigint as note_id,
    null::text as translated_text,
    null::text as model_name,
    null::timestamptz as created_at,
    true as machine_translated
where false
