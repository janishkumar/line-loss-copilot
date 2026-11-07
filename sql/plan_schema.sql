-- Plan outputs (schedules, replays, shortage reports) over synthetic orders on real capacity.
-- Tables added by later stage 4 tasks carry `is_synthetic boolean not null default true`.
-- The agent role may read this schema; only the owner writes. Safe to run repeatedly.
CREATE SCHEMA IF NOT EXISTS plan;

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
