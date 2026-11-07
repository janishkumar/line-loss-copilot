-- Synthetic demo overlay: users and the injected-note demo row. Safe to run repeatedly.
-- Everything here is synthetic and badged as such in the app; mart.* never reads it.
CREATE SCHEMA IF NOT EXISTS demo;

CREATE TABLE IF NOT EXISTS demo.app_user (
    user_id text PRIMARY KEY,
    display_name text NOT NULL,
    role text NOT NULL CHECK (role IN (
        'operator', 'shift_supervisor', 'planner', 'quality_lead', 'plant_manager', 'agent')),
    source text NOT NULL DEFAULT 'synthetic'
);

INSERT INTO demo.app_user (user_id, display_name, role) VALUES
    ('op.a', 'Operator A', 'operator'),
    ('sup.a', 'Supervisor A', 'shift_supervisor'),
    ('sup.b', 'Supervisor B', 'shift_supervisor'),
    ('plan.a', 'Planner A', 'planner'),
    ('ql.a', 'Quality lead A', 'quality_lead'),
    ('pm.a', 'Plant manager A', 'plant_manager'),
    ('copilot-agent', 'Copilot agent', 'agent')
ON CONFLICT (user_id) DO NOTHING;

-- Empty by default; filled only by the injection demo target.
CREATE TABLE IF NOT EXISTS demo.injected_note (
    id serial PRIMARY KEY,
    event_key text NOT NULL,
    text text NOT NULL,
    source text NOT NULL DEFAULT 'synthetic',
    created_at timestamptz NOT NULL DEFAULT now()
);
