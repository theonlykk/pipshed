# ADR-136: Carry Table on Pipshed Dashboard

**Status:** Proposed  
**Date:** 2026-09-11  
**Context:** CARRY_SNAPSHOT ea_events (fxmatrix ADR-135a) record the fleet swap
landscape in Postgres `detail` jsonb. A week of carry on EURUSD long (-0.876
pips/night) is about -6.13 pips, which can exceed a scalp exit target. Operators
need the table on the dashboard without quoting psql through Railway SSH.
ADR-130 rule 1: the web service never connects to Postgres.

## Decision

1. **Worker (`archive_worker.py`)** reads Postgres and publishes a computed
   table to Redis key `fxmatrix:carry:table` (no TTL). Rebuild triggers:
   (a) once after first successful Postgres connection at startup;
   (b) immediately after any drained batch containing a CARRY_SNAPSHOT ea_event;
   (c) fallback at most once per hour, guarded by `fxmatrix:carry:last_build`.
   Failures log one line and never stop the queue drain.

2. **Web (`app.py`)** serves `GET /api/g/<token>/carry` from Redis only.
   Wrong token returns 404; missing key returns
   `{"generated_at": null, "rows": []}` with no-cache headers.

3. **Dashboard (`templates/dashboard.html`)** adds a "Carry (per night, pips)"
   panel after the grind ring sections. Columns: Symbol, Long, Short,
   Long/week, Short/week, Mult, Updated. Long/week and Short/week use
   `round(pips * 7, 2)` where 7 = five ordinary nights plus the extra two
   from the x3 rollover day (Mon1 Tue1 Wed3 Thu1 Fri1 convention).

4. **Dedup:** SQL uses `DISTINCT ON (detail->>'symbol')` ordered by
   `received_at DESC` so one row per symbol survives even though each
   instance emits its own snapshot.

## Consequences

- **Positive:** Web retains no Postgres access; dashboard shows carry during
  a Postgres outage (stale `generated_at` indicates age).
- **Positive:** Table refreshes on new snapshots without polling Postgres
  from the web tier.
- **Positive:** Per-symbol rates collapse both arms into one row.
- **Negative:** Eligible layer counts are omitted (they reflect whichever
  instance reported last, not fleet-wide eligibility).
- **Negative:** Hourly fallback may lag if snapshots stop arriving and no
  CARRY_SNAPSHOT batch triggers a rebuild.

## Tests

CT1-CT7 in `scripts/verify_carry_table.py`: row typing, week pips, null
symbol skip, Redis publish, public route auth, empty key, drain isolation.
