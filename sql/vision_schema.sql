-- Visual inspection (stage 5): the simulated inspection stream, reviewer labels, and the
-- simulated quality events that rejected images create. VisA images are not from the PIADE or
-- brick lines, so the stations and the quality events are SYNTHETIC and say so in `source`.
-- mart.* and dbt never read synthetic.sim_asset, synthetic.quality_event or core.event_all.
-- Safe to run repeatedly; the view is re-created after every dbt build (`make dbt` applies
-- this file again, because dbt drops views that depend on the tables it rebuilds).
CREATE SCHEMA IF NOT EXISTS vision;
CREATE SCHEMA IF NOT EXISTS synthetic;

-- One row per scored image of the simulated stream (written by `make inspect`).
CREATE TABLE IF NOT EXISTS vision.inspection (
    inspection_id bigserial PRIMARY KEY,
    subset text NOT NULL,
    image_id text NOT NULL,
    split text NOT NULL DEFAULT 'test',
    score double precision NOT NULL,
    decision text NOT NULL CHECK (decision IN ('pass', 'review', 'reject')),
    threshold double precision NOT NULL,
    review_lower double precision,
    heatmap_path text,
    created_at timestamptz NOT NULL DEFAULT now(),
    source text NOT NULL DEFAULT 'simulated_stream',
    UNIQUE (subset, image_id)
);

-- A reviewer's decision on a queued image; the model's score is kept beside it.
CREATE TABLE IF NOT EXISTS vision.review (
    review_id bigserial PRIMARY KEY,
    inspection_id bigint NOT NULL UNIQUE REFERENCES vision.inspection (inspection_id),
    decision text NOT NULL CHECK (decision IN ('accept', 'reject')),
    reviewer text NOT NULL,
    score_at_review double precision NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- One simulated inspection station per subset.
CREATE TABLE IF NOT EXISTS synthetic.sim_asset (
    asset_id text PRIMARY KEY,
    subset text NOT NULL UNIQUE,
    name text NOT NULL,
    source text NOT NULL DEFAULT 'synthetic' CHECK (source = 'synthetic')
);

-- Ids come from their own range so they can never collide with core.event ids (1, 2, ...).
CREATE SEQUENCE IF NOT EXISTS synthetic.quality_event_seq START 9000000000;

CREATE TABLE IF NOT EXISTS synthetic.quality_event (
    event_id bigint PRIMARY KEY DEFAULT nextval('synthetic.quality_event_seq'),
    asset_id text NOT NULL REFERENCES synthetic.sim_asset (asset_id),
    inspection_id bigint NOT NULL UNIQUE REFERENCES vision.inspection (inspection_id),
    start_ts timestamptz NOT NULL DEFAULT now(),
    reason_code text NOT NULL DEFAULT 'VISUAL_REJECT' CHECK (reason_code = 'VISUAL_REJECT'),
    detail text NOT NULL,
    source text NOT NULL DEFAULT 'synthetic' CHECK (source = 'synthetic')
);

-- core.event plus the simulated quality events, in core.event's columns. Real rows keep
-- is_synthetic = false; quality events are event_type 'quality' with is_synthetic = true.
-- NOTE: the first branch keeps only NOT is_synthetic rows of core.event, so a synthetic row that
-- ever lands in core.event would be hidden from evidence checks; a test pins core.event to 0
-- synthetic rows. Quality events are the only synthetic rows in this view.
-- Created only once core.event exists (before the first dbt build there is nothing to union).
DO $$
BEGIN
    IF to_regclass('core.event') IS NOT NULL THEN
        EXECUTE $v$
            CREATE OR REPLACE VIEW core.event_all AS
            SELECT event_id, event_key, source_system, line_id, machine_id, event_type, state,
                   start_ts, end_ts, duration_s, shift_id, reason_code, reason_text, alarm_code,
                   product, qty_in, qty_out, qty_good, qty_reject, raw_table, source_file,
                   raw_row_ids, is_synthetic, location, stop_type
            FROM core.event
            WHERE NOT is_synthetic
            UNION ALL
            SELECT q.event_id,
                   'synthetic.quality_event#' || q.event_id::text,
                   'simulated_inspection',
                   q.asset_id,
                   q.asset_id,
                   'quality',
                   NULL::text,
                   q.start_ts,
                   q.start_ts,
                   0::numeric,
                   NULL::text,
                   q.reason_code,
                   q.detail,
                   NULL::text,
                   a.subset,
                   1::numeric,
                   NULL::numeric,
                   NULL::numeric,
                   1::numeric,
                   'synthetic.quality_event',
                   'synthetic.quality_event',
                   ARRAY[]::int[],
                   true,
                   NULL::text,
                   NULL::text
            FROM synthetic.quality_event q
            JOIN synthetic.sim_asset a USING (asset_id)
        $v$;
    END IF;
END
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'linecopilot_agent') THEN
        GRANT USAGE ON SCHEMA vision, synthetic TO linecopilot_agent;
        GRANT SELECT ON ALL TABLES IN SCHEMA vision TO linecopilot_agent;
        GRANT SELECT ON synthetic.sim_asset, synthetic.quality_event TO linecopilot_agent;
        ALTER DEFAULT PRIVILEGES FOR ROLE linecopilot IN SCHEMA vision
            GRANT SELECT ON TABLES TO linecopilot_agent;
        -- read only: the agent never labels an image or creates a quality event
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA vision
            FROM linecopilot_agent;
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON synthetic.sim_asset,
            synthetic.quality_event FROM linecopilot_agent;
        IF to_regclass('core.event_all') IS NOT NULL THEN
            GRANT SELECT ON core.event_all TO linecopilot_agent;
        END IF;
    END IF;
END
$$;
