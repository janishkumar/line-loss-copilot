-- Raw layer: normalised source values as text, plus row-level lineage.
-- (source_file, source_row) points at the 1-based data line of the original file.
-- Tables are only created if missing; load.py replaces a file's rows on re-load.

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.load (
    load_id          serial PRIMARY KEY,
    dataset          text NOT NULL,
    filename         text NOT NULL,
    sha256           text NOT NULL,
    loaded_at        timestamptz NOT NULL DEFAULT now(),
    rows_read        int NOT NULL,
    rows_accepted    int NOT NULL,
    rows_rejected    int NOT NULL,
    trimmed_columns  int NOT NULL DEFAULT 0,
    trimmed_rows     int NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS raw.brick_oee (
    shift_date          text,
    oee                 text,
    availability        text,
    performance         text,
    quality             text,
    good_production_s   text,
    slow_production_s   text,
    planned_s           text,
    ideal_qty           text,
    planned_stops_s     text,
    unplanned_stops_s   text,
    good_qty            text,
    total_qty           text,
    period              text,
    load_id             int NOT NULL REFERENCES raw.load (load_id),
    source_file         text NOT NULL,
    source_row          int NOT NULL,
    PRIMARY KEY (source_file, source_row)
);

CREATE TABLE IF NOT EXISTS raw.brick_downtime (
    shift_date    text,
    product       text,
    stop_group    text,
    stop          text,
    stop_type     text,
    location      text,
    note          text,
    start_local   text,
    end_local     text,
    duration_min  text,
    period        text,
    load_id       int NOT NULL REFERENCES raw.load (load_id),
    source_file   text NOT NULL,
    source_row    int NOT NULL,
    PRIMARY KEY (source_file, source_row)
);

CREATE TABLE IF NOT EXISTS raw.piade_raw (
    machine_id   text,
    alarm        text,
    state        text,
    start_utc    text,
    end_utc      text,
    elapsed_ms   text,
    pi           text,
    po           text,
    speed        text,
    start_raw    text,
    end_raw      text,
    load_id      int NOT NULL REFERENCES raw.load (load_id),
    source_file  text NOT NULL,
    source_row   int NOT NULL,
    PRIMARY KEY (source_file, source_row)
);

CREATE TABLE IF NOT EXISTS raw.rejected (
    load_id      int NOT NULL REFERENCES raw.load (load_id),
    source_file  text NOT NULL,
    source_row   int NOT NULL,
    reason       text NOT NULL,
    raw          jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS rejected_file_idx ON raw.rejected (source_file, source_row);
