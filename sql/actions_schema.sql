-- Approved-actions tables, the append-only audit log and the restricted agent role.
-- Safe to run repeatedly; the grants at the end are re-applied after every dbt build
-- because dbt recreates core and mart tables, which drops their grants.
CREATE SCHEMA IF NOT EXISTS actions;

CREATE TABLE IF NOT EXISTS actions.web_session (
    token_sha256 text PRIMARY KEY,
    user_id text NOT NULL REFERENCES demo.app_user (user_id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS actions.confirmation_code (
    code_sha256 text PRIMARY KEY,
    action text NOT NULL,
    principal text NOT NULL,
    on_behalf_of text NOT NULL,
    payload_sha256 text NOT NULL,
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS actions.proposal (
    proposal_id bigserial PRIMARY KEY,
    action text NOT NULL CHECK (action IN ('work_order', 'quality_hold', 'follow_up')),
    args jsonb NOT NULL,
    payload_sha256 text NOT NULL,
    summary text NOT NULL,
    checks jsonb NOT NULL DEFAULT '[]',
    principal text NOT NULL,
    on_behalf_of text NOT NULL,
    channel text NOT NULL CHECK (channel IN ('mcp', 'web_chat', 'web_form')),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    decided_by text,
    decided_at timestamptz,
    decision_note text,
    target_id bigint,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS actions.proposal_evidence (
    proposal_id bigint NOT NULL REFERENCES actions.proposal (proposal_id),
    event_key text NOT NULL,
    event_id_at_link bigint,
    PRIMARY KEY (proposal_id, event_key)
);

CREATE TABLE IF NOT EXISTS actions.work_order (
    work_order_id bigserial PRIMARY KEY,
    proposal_id bigint NOT NULL UNIQUE REFERENCES actions.proposal (proposal_id),
    asset_id text NOT NULL,
    failure_mode text NOT NULL,
    priority text NOT NULL CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    description text NOT NULL,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    closed_by text,
    closed_at timestamptz
);

CREATE TABLE IF NOT EXISTS actions.quality_hold (
    hold_id bigserial PRIMARY KEY,
    proposal_id bigint NOT NULL UNIQUE REFERENCES actions.proposal (proposal_id),
    asset_id text NOT NULL,
    product text,
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    reason text NOT NULL,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'released')),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    released_by text,
    released_at timestamptz
);

CREATE TABLE IF NOT EXISTS actions.follow_up (
    follow_up_id bigserial PRIMARY KEY,
    proposal_id bigint NOT NULL UNIQUE REFERENCES actions.proposal (proposal_id),
    assignee_role text NOT NULL,
    due_date date NOT NULL,
    description text NOT NULL,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS actions.audit_log (
    audit_id bigserial PRIMARY KEY,
    at timestamptz NOT NULL DEFAULT now(),
    event text NOT NULL,
    action text,
    proposal_id bigint,
    principal text NOT NULL,
    on_behalf_of text,
    channel text,
    payload_sha256 text,
    outcome text NOT NULL,
    checks jsonb,
    detail text
);

CREATE OR REPLACE FUNCTION actions.audit_log_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END;
$$;

DROP TRIGGER IF EXISTS audit_log_append_only ON actions.audit_log;
CREATE TRIGGER audit_log_append_only
    BEFORE UPDATE OR DELETE ON actions.audit_log
    FOR EACH ROW EXECUTE FUNCTION actions.audit_log_guard();

DROP TRIGGER IF EXISTS audit_log_no_truncate ON actions.audit_log;
CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON actions.audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION actions.audit_log_guard();

-- A code can only move from unused to used; nothing else about it may change, so a burned
-- code cannot be revived.
CREATE OR REPLACE FUNCTION actions.confirmation_code_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.used_at IS NOT NULL
       OR NEW.used_at IS NULL
       OR (NEW.code_sha256, NEW.action, NEW.principal, NEW.on_behalf_of, NEW.payload_sha256,
           NEW.expires_at, NEW.created_at)
          IS DISTINCT FROM
          (OLD.code_sha256, OLD.action, OLD.principal, OLD.on_behalf_of, OLD.payload_sha256,
           OLD.expires_at, OLD.created_at) THEN
        RAISE EXCEPTION 'confirmation_code is single-use: used_at may only be set once';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS confirmation_code_single_use ON actions.confirmation_code;
CREATE TRIGGER confirmation_code_single_use
    BEFORE UPDATE ON actions.confirmation_code
    FOR EACH ROW EXECUTE FUNCTION actions.confirmation_code_guard();

-- Restricted role the agent paths (MCP, chat) connect with. Roles are cluster-wide, so the
-- create is guarded.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'linecopilot_agent') THEN
        CREATE ROLE linecopilot_agent LOGIN PASSWORD 'linecopilot_agent';
    END IF;
END
$$;

-- Read access to every schema that exists (core and mart are absent before the first dbt
-- build), plus default privileges for tables the owner creates later.
DO $$
DECLARE
    s text;
BEGIN
    FOREACH s IN ARRAY ARRAY['raw', 'core', 'mart', 'enrich', 'ml', 'demo', 'actions'] LOOP
        IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = s) THEN
            EXECUTE format('GRANT USAGE ON SCHEMA %I TO linecopilot_agent', s);
            EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO linecopilot_agent', s);
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES FOR ROLE linecopilot IN SCHEMA %I '
                'GRANT SELECT ON TABLES TO linecopilot_agent', s);
        END IF;
    END LOOP;
END
$$;

-- The agent never sees the session token hashes.
REVOKE ALL ON actions.web_session FROM linecopilot_agent;

-- Proposal INSERT is column-level: status, decided_*, decision_note and target_id always take
-- their defaults, so the agent cannot write a pre-approved row. The REVOKE removes any
-- table-level grant left by an earlier version of this script.
REVOKE INSERT ON actions.proposal FROM linecopilot_agent;
GRANT INSERT (action, args, payload_sha256, summary, checks, principal, on_behalf_of, channel,
    created_at) ON actions.proposal TO linecopilot_agent;
GRANT INSERT ON actions.confirmation_code, actions.proposal_evidence,
    actions.audit_log TO linecopilot_agent;
GRANT UPDATE (used_at) ON actions.confirmation_code TO linecopilot_agent;
GRANT USAGE ON SEQUENCE actions.proposal_proposal_id_seq,
    actions.audit_log_audit_id_seq TO linecopilot_agent;
