select e.event_id from {{ ref('event') }} e
left join {{ ref('shift') }} s using (shift_id)
where s.shift_id is null
