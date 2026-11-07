-- Plan outputs (schedules, replays, shortage reports) over synthetic orders on real capacity.
-- Every table carries `is_synthetic boolean not null default true`: orders are synthetic, capacity
-- and replayed stops are real.
-- The agent role may read this schema; only the owner writes. Safe to run repeatedly.
CREATE SCHEMA IF NOT EXISTS plan;

-- One row per algorithm per `make plan` run; `label` ties the rows of one run together.
CREATE TABLE IF NOT EXISTS plan.plan_run (
    plan_run_id serial PRIMARY KEY,
    generation_id int,
    algorithm text NOT NULL,
    status text NOT NULL,
    solver_status text,
    stop_reason text,
    objective double precision,
    bound double precision,
    kpis jsonb NOT NULL,
    label text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    is_synthetic boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS plan.assignment (
    plan_run_id int NOT NULL REFERENCES plan.plan_run ON DELETE CASCADE,
    order_id text NOT NULL,
    machine_id text NOT NULL,
    start_at timestamptz NOT NULL,
    end_at timestamptz NOT NULL,
    setup_min int NOT NULL,
    is_synthetic boolean NOT NULL DEFAULT true,
    PRIMARY KEY (plan_run_id, order_id)
);

CREATE TABLE IF NOT EXISTS plan.blocked (
    plan_run_id int NOT NULL REFERENCES plan.plan_run ON DELETE CASCADE,
    order_id text NOT NULL,
    reason text NOT NULL,
    is_synthetic boolean NOT NULL DEFAULT true,
    PRIMARY KEY (plan_run_id, order_id)
);

-- The plan executed against real PIADE stops in one 14-day window. `machine_stats` holds, per
-- machine, the realised stopped share and the share of the window with no data.
CREATE TABLE IF NOT EXISTS plan.replay_result (
    plan_run_id int NOT NULL REFERENCES plan.plan_run ON DELETE CASCADE,
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    kpis jsonb NOT NULL,
    machine_stats jsonb NOT NULL DEFAULT '{}',
    is_synthetic boolean NOT NULL DEFAULT true,
    PRIMARY KEY (plan_run_id, window_start)
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'linecopilot_agent') THEN
        GRANT USAGE ON SCHEMA plan TO linecopilot_agent;
        GRANT SELECT ON ALL TABLES IN SCHEMA plan TO linecopilot_agent;
        ALTER DEFAULT PRIVILEGES FOR ROLE linecopilot IN SCHEMA plan
            GRANT SELECT ON TABLES TO linecopilot_agent;
    END IF;
END
$$;
