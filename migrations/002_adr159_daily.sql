CREATE TABLE daily_snapshots (
    id bigserial PRIMARY KEY,
    account_login bigint NOT NULL,
    ftmo_day date NOT NULL,
    instance_id text,
    session_id text,
    ea_time_ms bigint,
    received_at timestamptz NOT NULL,
    balance_start numeric(14,2), equity_start numeric(14,2),
    balance_end numeric(14,2),   equity_end numeric(14,2),
    realised numeric(14,2), nontrade numeric(14,2),
    inventory_pnl numeric(14,2), total numeric(14,2), swap_day numeric(14,2),
    positions_long int, positions_short int, orders int,
    guard_total int, guard_age_s int,
    breaker_tripped boolean, premidnight_seen boolean,
    broker_utc_offset_s int,
    start_known boolean, balance_start_source text,
    ejections_auto int, ejections_command int,
    ejected_fills int, ejected_realised numeric(14,2),
    eject_filled_events int, eject_mismatch int,
    carry_clamps int, critical_events int,
    derived_at timestamptz,
    detail jsonb,
    UNIQUE (account_login, ftmo_day)
);
ALTER TABLE scalp_history ADD COLUMN ejected boolean;
ALTER TABLE scalp_history ADD COLUMN broker_utc_offset_s int;
ALTER TABLE scalp_history ADD COLUMN account_login bigint;
CREATE INDEX ea_events_ea_time ON ea_events (ea_time_ms);
CREATE VIEW session_accounts AS
    SELECT DISTINCT ON (session_id) session_id, instance_id, account_login
    FROM config_events
    WHERE session_id IS NOT NULL AND account_login IS NOT NULL
    ORDER BY session_id, received_at;
