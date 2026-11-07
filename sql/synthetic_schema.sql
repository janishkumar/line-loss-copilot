-- Synthetic orders, BOMs, stock and receipts for stage 4 planning. Every row is synthetic and
-- says so in `source`; mart.* never reads this schema. Written by `make synth`, which replaces
-- the content tables in one transaction and keeps `generation` as history. Safe to run repeatedly.
CREATE SCHEMA IF NOT EXISTS synthetic;

CREATE TABLE IF NOT EXISTS synthetic.generation (
    generation_id serial PRIMARY KEY,
    seed int NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    anchors jsonb NOT NULL,
    content_sha256 text NOT NULL,
    source text NOT NULL DEFAULT 'synthetic'
);

CREATE TABLE IF NOT EXISTS synthetic.product (
    product_id text PRIMARY KEY,
    family text NOT NULL,
    name text NOT NULL,
    source text NOT NULL DEFAULT 'synthetic'
);

CREATE TABLE IF NOT EXISTS synthetic.machine_capability (
    machine_id text NOT NULL,
    family text NOT NULL,
    source text NOT NULL DEFAULT 'synthetic',
    PRIMARY KEY (machine_id, family)
);

-- Rate and availability are anchored to PIADE (rate_source, availability_window say how).
CREATE TABLE IF NOT EXISTS synthetic.machine_rate (
    machine_id text PRIMARY KEY,
    rate_per_hour numeric NOT NULL,
    availability numeric NOT NULL,
    rate_source text NOT NULL,
    availability_window text NOT NULL,
    source text NOT NULL DEFAULT 'synthetic'
);

-- Changeover minutes between families; same_product true means no changeover. Cross-family and
-- same-family minutes are the p75 and p25 of the real brick-line SETUPS-CHANGEOVERS stops.
CREATE TABLE IF NOT EXISTS synthetic.changeover (
    from_family text NOT NULL,
    to_family text NOT NULL,
    same_product boolean NOT NULL,
    minutes int NOT NULL,
    basis text NOT NULL,
    source text NOT NULL DEFAULT 'synthetic',
    PRIMARY KEY (from_family, to_family, same_product)
);

CREATE TABLE IF NOT EXISTS synthetic.customer_order (
    order_id text PRIMARY KEY,
    product_id text NOT NULL,
    quantity int NOT NULL CHECK (quantity > 0),
    release_at timestamptz NOT NULL,
    due_at timestamptz NOT NULL,
    note text,
    customer text NOT NULL,
    source text NOT NULL DEFAULT 'synthetic'
);

CREATE TABLE IF NOT EXISTS synthetic.material (
    material_id text PRIMARY KEY,
    name text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('subassembly', 'raw')),
    unit text NOT NULL,
    lead_time_days int NOT NULL,
    source text NOT NULL DEFAULT 'synthetic'
);

-- parent_id is a product or a subassembly material.
CREATE TABLE IF NOT EXISTS synthetic.bom (
    parent_id text NOT NULL,
    child_id text NOT NULL,
    qty_per numeric NOT NULL CHECK (qty_per > 0),
    source text NOT NULL DEFAULT 'synthetic',
    PRIMARY KEY (parent_id, child_id)
);

CREATE TABLE IF NOT EXISTS synthetic.stock (
    material_id text PRIMARY KEY,
    on_hand numeric NOT NULL CHECK (on_hand >= 0),
    source text NOT NULL DEFAULT 'synthetic'
);

CREATE TABLE IF NOT EXISTS synthetic.receipt (
    receipt_id text PRIMARY KEY,
    material_id text NOT NULL,
    qty numeric NOT NULL CHECK (qty > 0),
    due_at timestamptz NOT NULL,
    source text NOT NULL DEFAULT 'synthetic'
);

-- Ground truth for the shortage eval. decoy rows look like a shortage to a naive rule but are not.
CREATE TABLE IF NOT EXISTS synthetic.planted_shortage (
    material_id text NOT NULL,
    order_id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('plain', 'timing', 'level_two')),
    decoy boolean NOT NULL DEFAULT false,
    note text,
    source text NOT NULL DEFAULT 'synthetic',
    PRIMARY KEY (material_id, order_id)
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'linecopilot_agent') THEN
        GRANT USAGE ON SCHEMA synthetic TO linecopilot_agent;
        GRANT SELECT ON ALL TABLES IN SCHEMA synthetic TO linecopilot_agent;
        ALTER DEFAULT PRIVILEGES FOR ROLE linecopilot IN SCHEMA synthetic
            GRANT SELECT ON TABLES TO linecopilot_agent;
    END IF;
END
$$;
