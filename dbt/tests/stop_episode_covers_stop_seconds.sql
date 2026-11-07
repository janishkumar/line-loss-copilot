-- PIADE: per machine, episode seconds equal the stopped intervals' seconds in core.event less
-- what mart.piade_interval_counts clipped off overlapping intervals.
-- Brick: one episode per stop event.
with ep as (
    select machine_id, sum(duration_s) as s, count(*) as n
    from {{ ref('stop_episode') }}
    where source_system = 'piade'
    group by 1
),
ev as (
    select e.machine_id, sum(e.duration_s - coalesce(i.clipped_s, 0)) as s
    from {{ ref('event') }} e
    left join {{ ref('piade_interval_counts') }} i on i.event_id = e.event_id
    where e.source_system = 'piade' and e.state = 'stopped'
    group by 1
),
brick as (
    select
        (select count(*) from {{ ref('stop_episode') }} where source_system = 'brick') as n_ep,
        (select count(*) from {{ ref('event') }}
         where source_system = 'brick' and event_type = 'stop') as n_ev
)
select coalesce(ep.machine_id, ev.machine_id) as asset, ep.s as episode_s, ev.s as event_s
from ep full outer join ev using (machine_id)
where abs(coalesce(ep.s, 0) - coalesce(ev.s, 0)) > 1e-3
union all
select 'brick', n_ep, n_ev
from brick
where n_ep <> n_ev
