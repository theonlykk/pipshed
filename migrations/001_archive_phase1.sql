-- Archive phase 1: send_logs, fill_logs, config_events, ea_events, scalp_history

CREATE TABLE IF NOT EXISTS schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE send_logs (
    id bigserial PRIMARY KEY,
    instance_id text NOT NULL,
    magic bigint,
    session_id text NOT NULL,
    seq bigint NOT NULL,
    ea_time_ms bigint,
    received_at timestamptz NOT NULL,
    action text,
    order_type text,
    side text,
    layer_index int,
    role text,
    requested_price double precision,
    volume double precision,
    order_ticket bigint,
    position_ticket bigint,
    position_by_ticket bigint,
    comment text,
    ok boolean,
    retcode int,
    result_order bigint,
    result_deal bigint,
    duration_ms int,
    broker_time timestamp,
    UNIQUE (instance_id, session_id, seq)
);

CREATE INDEX send_logs_instance_ea_time ON send_logs (instance_id, ea_time_ms);
CREATE INDEX send_logs_received_at ON send_logs (received_at);

CREATE TABLE fill_logs (
    id bigserial PRIMARY KEY,
    instance_id text NOT NULL,
    magic bigint,
    session_id text NOT NULL,
    seq bigint NOT NULL,
    ea_time_ms bigint,
    received_at timestamptz NOT NULL,
    deal_ticket bigint NOT NULL,
    order_ticket bigint,
    position_id bigint,
    entry_type text,
    deal_type text,
    side text,
    layer_index int,
    role text,
    deal_price double precision,
    order_price_open double precision,
    slippage_pips double precision,
    volume double precision,
    profit double precision,
    swap double precision,
    commission double precision,
    deal_time_broker timestamp,
    deal_time_broker_msc bigint,
    halted_at_receipt boolean,
    quarantined_at_receipt boolean,
    UNIQUE (instance_id, session_id, seq),
    UNIQUE (instance_id, deal_ticket)
);

CREATE INDEX fill_logs_instance_ea_time ON fill_logs (instance_id, ea_time_ms);

CREATE TABLE config_events (
    id bigserial PRIMARY KEY,
    instance_id text NOT NULL,
    magic bigint,
    session_id text NOT NULL,
    seq bigint NOT NULL,
    ea_time_ms bigint,
    received_at timestamptz NOT NULL,
    event text NOT NULL,
    deinit_reason int,
    symbol text,
    slot text,
    ea_build text,
    account_login bigint,
    width_pips double precision,
    add_pips double precision,
    exit_pips double precision,
    max_layers int,
    lots double precision,
    deadband_pips double precision,
    stranded_thresh_pips double precision,
    cap_leg_a text,
    cap_leg_b text,
    cap_leg_a_thresh double precision,
    cap_leg_b_thresh double precision,
    inputs jsonb,
    UNIQUE (instance_id, session_id, seq)
);

CREATE TABLE ea_events (
    id bigserial PRIMARY KEY,
    instance_id text NOT NULL,
    magic bigint,
    session_id text NOT NULL,
    seq bigint NOT NULL,
    ea_time_ms bigint,
    received_at timestamptz NOT NULL,
    level text NOT NULL,
    code text NOT NULL,
    reason text,
    ticket bigint,
    detail jsonb,
    UNIQUE (instance_id, session_id, seq)
);

CREATE INDEX ea_events_code_received_at ON ea_events (code, received_at);

CREATE TABLE scalp_history (
    id bigserial PRIMARY KEY,
    instance_id text NOT NULL,
    instrument text,
    direction text NOT NULL,
    entry_price double precision NOT NULL,
    exit_price double precision NOT NULL,
    gross_pnl double precision,
    layer_depth int,
    stack_depth int,
    close_time_broker timestamp NOT NULL,
    entry_deal_ticket bigint,
    exit_deal_ticket bigint,
    source text NOT NULL,
    received_at timestamptz NOT NULL,
    UNIQUE (instance_id, close_time_broker, direction, entry_price, exit_price)
);
