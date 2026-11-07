-- Stop-risk model outputs, written by `make train-risk`. Safe to run repeatedly.
CREATE SCHEMA IF NOT EXISTS ml;

-- One score per machine, prediction time t (whole UTC hour) and target, from the model
-- selected on validation PR-AUC. The score is for an event starting in [t, t + 1 h).
CREATE TABLE IF NOT EXISTS ml.stop_risk_score (
    machine_id text NOT NULL,
    t timestamptz NOT NULL,
    target text NOT NULL CHECK (target IN ('long', 'any')),
    model_name text NOT NULL,
    score double precision NOT NULL,
    top_features jsonb NOT NULL DEFAULT '[]',
    split text NOT NULL CHECK (split IN ('train', 'validation', 'test')),
    PRIMARY KEY (target, machine_id, t)
);

-- Evaluation numbers per target, model and split; machine_id null means all machines.
CREATE TABLE IF NOT EXISTS ml.model_metrics (
    target text NOT NULL,
    model_name text NOT NULL,
    split text NOT NULL,
    metric text NOT NULL,
    value double precision,
    machine_id text,
    created_at timestamptz NOT NULL DEFAULT now()
);
