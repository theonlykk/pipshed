# ADR-130: Postgres Archive Phase 1 (Migrations, Action Endpoint, Queue, Worker)

**Status:** Accepted  
**Date:** 2026-09-11  
**Context:** HANDOFF_2026-09-10 section 5b (ratified) and HANDOFF_2026-09-11 section 6 define an
asynchronous Postgres shadow of Redis operational telemetry. Gemini table consultation
(gemini_postgres_table_consult.md) produced rulings R1-R8: five archive tables
(send_logs, fill_logs, config_events, ea_events, scalp_history), Redis queue transport,
at-least-once delivery with idempotent inserts, and no Postgres on the web request path.
Evidence mapping ties EA event types to table columns; scalp_history arrives first via
the existing scalp_closed tap until the EA emits structured events in a later task.

## Decision

Implement Phase 1 in pipshed only:

1. **Migrations** -- Plain SQL in `migrations/001_archive_phase1.sql`; manual runner
   `db_migrate.py` (psycopg2, no ORM). Operator applies on Railway; never at app startup.
2. **POST /api/telemetry/action** -- Bearer-authenticated batch ingress; validates events;
   RPUSHes envelope items to `fxmatrix:archive:queue`; 503 if Redis fails.
3. **Scalp tap** -- `telemetry_scalp_closed` RPUSHes a scalp envelope to the same queue;
   existing scalp list behaviour unchanged.
4. **archive_worker.py** -- Separate Railway service: LMOVE queue to processing, INSERT
   ON CONFLICT DO NOTHING, LTRIM processing only after commit; deadletter on poison items;
   14-day send_logs and 90-day ea_events retention inside the worker; heartbeat key
   `fxmatrix:archive:worker`.
5. **GET /api/g/<token>/archive** -- Public Redis-only health (queue, processing,
   deadletter, worker JSON).

Redis remains operational truth. Postgres is an asynchronous shadow. The web process
never connects to Postgres.

## Consequences

- **Positive:** Durable queryable history for sends, fills, config, EA events, and scalps
  without blocking live telemetry paths.
- **Positive:** At-least-once queue semantics with idempotent inserts; crash recovery via
  the processing list.
- **Positive:** Dead letters remain in Redis (`fxmatrix:archive:deadletter`) for operator
  inspection without silent loss.
- **Negative:** EA structured events (send_log, fill_log, config_event, ea_event) arrive
  only after the EA-side emission task; until then archive growth is mostly scalp_history
  via the tap.
- **Negative:** Retention runs inside the single worker replica; multi-replica workers
  would require redesign.
- **Negative:** `close_time` on scalps is broker-local time wrongly suffixed with Z;
  stored as naive `close_time_broker` per existing EA convention.

## Operator steps

1. Railway, pipshed project: add PostgreSQL (done or pending).
2. After merge: `railway run python db_migrate.py` against that database.
3. Add a service from the same repo, start command `python archive_worker.py`, variables
   REDIS_URL and DATABASE_URL referenced from the Redis and Postgres services. Exactly ONE
   replica: the processing-list design assumes a single worker.
4. Check `/api/g/<token>/archive/<segment>` shows a fresh worker heartbeat.
5. The next scalp_closed should appear in scalp_history.
