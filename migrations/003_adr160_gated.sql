ALTER TABLE daily_snapshots
    ADD COLUMN gated_seconds int GENERATED ALWAYS AS (
        CASE WHEN jsonb_typeof(detail -> 'gated_seconds') = 'number' THEN
            CASE WHEN (detail ->> 'gated_seconds')::numeric BETWEEN 0 AND 172800
                 THEN (detail ->> 'gated_seconds')::numeric::int
            END
        END
    ) STORED;
ALTER TABLE daily_snapshots
    ADD COLUMN history_ok boolean GENERATED ALWAYS AS (
        CASE WHEN jsonb_typeof(detail -> 'history_ok') = 'boolean'
             THEN (detail ->> 'history_ok')::boolean
        END
    ) STORED;
