-- C137: one row per live instance per minute, written by the archive
-- worker from the fxmatrix:state:* heartbeats (fresh within 120 s).
-- Kept without retention (operator 7 Oct ~23:04Z; ~49k rows a day).
CREATE TABLE state_snapshots (
    id bigserial PRIMARY KEY,
    snapped_at timestamptz NOT NULL,
    instance_id text NOT NULL,
    account_login bigint,
    heartbeat_at timestamptz,
    balance numeric(14,2),
    equity numeric(14,2),
    net_mtm numeric(14,2),
    mtm_long numeric(14,2),
    mtm_short numeric(14,2),
    layers_long int,
    layers_short int,
    api_count int,
    halted boolean,
    quarantined boolean,
    entry_stopped boolean,
    max_layers int,
    width_long double precision,
    width_short double precision,
    add_long double precision,
    add_short double precision,
    exit_long double precision,
    exit_short double precision,
    closes_since_init int,
    fills int,
    UNIQUE (instance_id, snapped_at)
);
CREATE INDEX state_snapshots_snapped_at ON state_snapshots (snapped_at);
