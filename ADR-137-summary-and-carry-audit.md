# ADR-137: Daily Summary Block and Carry Audit Table

**Status:** Proposed  
**Date:** 2026-09-12  
**Context:** Operators want a copy/paste daily summary of broker-day scalp
performance and account snapshot, plus an independent table showing how
tonight's carry increment should move each working order's limit price.
The EA applies carry to layer exits overnight; the dashboard must cross-check
that arithmetic from Redis heartbeat orders and the ADR-136 carry table, not
echo any EA-supplied projection. ADR-130 rule 1: the web service reads Redis
only and never connects to Postgres.

## Decision

1. **Daily summary (`GET /api/g/<token>/summary`)** returns plain text
   (`Content-Type: text/plain`, no-cache) built from broker-today scalp lists
   across all grind instances, the freshest heartbeat account balance/equity,
   open book positions for risk/MTM, and optional `CYCLE_START_DATE` env for
   cycle day numbering. Pips use `|exit - entry| * 10000` (or `* 100` when
   price implies a 3-digit symbol). Commission assumes 0.01 lots at
   2.5 USD/lot round-trip (`-0.05 USD` per scalp). The dashboard renders the
   same text in a `<pre>` block at the top with a Copy button.

2. **Carry audit (`GET /api/g/<token>/carry_audit`)** returns JSON listing
   every working order from heartbeat `book.orders[]`. Comments parse as
   `GRIND|slot|L|S|Lnn|ENT|EXT`. ROLE EXT: `price_tonight = price_now -
   direction * carry_pips * pip_size` where direction is +1 for long layers
   and -1 for short layers; carry_pips comes from the carry table row for the
   instance symbol. ROLE ENT and unparsable comments stay unchanged. Missing
   carry data lists the order with `why = "no carry data"`. Rows include
   `carry_pips` and `pip_size` for eyeball verification. The dashboard section
   "Carry audit (tonight)" highlights changed rows and mutes unchanged ones.

3. **Tests:** S1-S3 and C1-C6 in `scripts/verify_summary_carry.py` (mock Redis,
   no network).

## Consequences

- **Positive:** Operators get a distributable daily summary without querying
  telemetry routes or Postgres. Carry audit is a cross-check of the EA computed
  from the broker's own rates already in the carry table.
- **Positive:** Web retains no Postgres access; both features are Redis-only.
- **Negative:** The audit shows tonight's carry increment only, not accrued
  swap on open positions (that would need per-position swap in the heartbeat).
- **Negative:** Commission and lot size remain assumed constants (0.01 lots),
  matching existing dashboard exposure assumptions.
- **Negative:** Open MTM sums `book.positions[].profit` from heartbeats; if
  the book is stale, MTM will lag.

## Update 2026-09-12 (ADR-138)

**Defect:** Live check on 2026-09-12 found `/carry_audit` reporting
`carry_pips` of 0.0 for every order. Cause: the carry table published
`long_pips` / `short_pips` using the snapshot's **today** `multiplier`.
On Saturday the broker weekday table has multiplier 0, so all published
pips collapsed to zero even though the imminent rollover uses **Monday's**
multiplier (1).

**Fix:** `archive_worker.build_carry_table` now uses `mult_tomorrow` when
present (fallback: `multiplier`), recomputing pips as
`swap_points * mult_used / 10`. Rows publish `mult_used` and
`mult_snapshot` alongside the recomputed pips.

**Summary v2:** Layout leads with account (not commission), adds financing
accrued `(equity - balance) - open_mtm`, cycle weekday totals via
`_collect_scalp_records_between`, optional `?date=` with `(historical)` /
`(live, not historical)` markers on fields that cannot be reconstructed
for past broker days.
