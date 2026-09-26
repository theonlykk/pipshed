# PIPSHED C56+ : PASSIVE EJECTION TELEMETRY (ROLLS AND EJECTIONS), TESTS FIRST

Goal (operator, 2026-09-26): "the more telemetry the better for passive
ejection. I want you [Claude] to be able to look at pipshed and know
exactly what we have done rather than trawl through logs." After this
change pipshed alone answers, per fleet: which layer was rolled or
ejected, when, at what prices, at what cost in pips and dollars, whether
and when it filled, what is pending or stuck, and each day's closed P&L
split into scalps, rolls and ejections.

## AUDIT TRAIL

| item | detail | status |
|---|---|---|
| Why | ADR-162 (virtual lattice) goes live on Fleet B next (fxmatrix backlog C63); C56 is its last blocker. Cycle 4 scores CLOSED P&L incl. rolls (fxmatrix `cycle4-live-geometry-search.md` s8.1) | design |
| Base | pipshed `main` at `5e8b904` | verified by Claude |
| EA events | the EA (fxmatrix `main`, `grind_engine.mqh`) archives, as `ea_events` rows with `detail` jsonb: `ROLL_ACCEPTED` {ticket, side L/S, layer_index, entry, level, target, accrued, clamped, cost, cost_pips, rolled, was_ejected, source}; `ROLL_REFUSED` {ticket, reason, level, source}; `ROLL_FILLED` {ticket, level}; `ROLL_STRANDED` (WARN) {side, depth, rolled, lowest_effective, market, steps}; `ROLL_CLOSING_STUCK` (WARN); `EJECT_ACCEPTED` (source auto/command), `EJECT_REFUSED`, `EJECT_FILLED` {ticket, offset}. `ticket` = the layer's POSITION ticket | verified in EA source |
| Scalp payload | the EA's `scalp_closed` JSON already carries `"rolled":true/false` beside `"ejected"` (`grind_scalp_events.mqh`) | verified in EA source |
| Heartbeat | `HEARTBEAT_DETAIL` layers carry `"virtual_level"` for a rolled layer (`grind_heartbeat_detail.mqh` 247-261). NOT verified that this reaches Redis `fxmatrix:state:<inst>` | Cursor to verify (F3) |
| Schema | `scalp_history` (`migrations/001`, + `ejected`, `broker_utc_offset_s`, `account_login` in `002`); `fill_logs` has `deal_ticket`, `order_ticket`, `position_id`, `entry_type`, `side`, `profit`, `swap`, `commission`, `ea_time_ms`; `ea_events` has `code`, `level`, `ticket`, `detail`, `ea_time_ms` (index `ea_events_ea_time`); `daily_snapshots` (`002`) | verified |
| Worker | `SCALP_FIELDS` `archive_worker.py:85` (no `rolled`); scalp INSERT `:691`; `DAILY_EVENTS_SQL` `:91` (EJECT_ACCEPTED, EJECT_FILLED, CARRY_PASS_*, CRITICAL); `DAILY_SCALPS_SQL` `:106` (`WHERE ejected IS TRUE`); `DAILY_SNAPSHOTS_SELECT` `:113`; `DAILY_SNAPSHOT_INSERT` `:128`; `daily_row_to_public` `:348`; `build_daily_derived` `:363` | verified |
| Daily logic | `ftmo_daily.py`: `WARN_CRITICAL_ALLOW` line 5 (no ROLL_*); `derive_counts` (eject counts, mismatch); `s4_counts(fill_rows, eject_tickets, day_of)` 274 | verified |
| s4 | `scripts/s4_scalps.py`: `OUT_BY_SQL` 13, `EJECT_SQL` 20 (`code = 'EJECT_FILLED'` only), `SCALP_HISTORY_SQL` 27 (`ejected IS NOT TRUE`), eject set built 130, `s4_counts` 149. A roll's fill is an `OUT_BY` like a scalp's: TODAY A ROLL IS COUNTED AS A SCALP | verified |
| Public JSON | `/api/g/<token>/status[/<path:_ignored>]` `app.py:1341` is the pattern (token `PUBLIC_GRIND_STATUS_TOKEN` 230, `_apply_no_cache_headers`, fleet by `GRIND_FLEET` 99-108, `GRIND_INSTANCES`) | verified |
| Tests | pattern: `scripts/verify_*.py`; DB ones need `VERIFY_DATABASE_URL` (an EMPTY scratch database, never production), e.g. `verify_archive_codes_depth.py` | verified |
| Dry run | NOT done this time (no PostgreSQL in Claude's sandbox this session). Claude re-runs every verify script on PostgreSQL 16 against the pushed branch | pending |

## FOR GEMINI (answer these; Cursor waits for the answers)

- **Q1 Attribution of commission and swap.** A layer closes by CloseBy
  against the position its exit order opened, so its money sits on deals
  of TWO position ids. Proposed: a closed layer's net = `gross_pnl` (from
  `scalp_history`) + the sums of `commission` and `swap` over every
  `fill_logs` deal whose `position_id` is the position of the scalp's
  `entry_deal_ticket` OR of its `exit_deal_ticket`. Sound, or is there a
  cleaner key? Double-count risk?
- **Q2 Deploy order.** Pushing pipshed `main` redeploys the worker. If the
  new INSERT writes `rolled` before migration `004` exists, every scalp
  insert fails. Proposed: the operator applies `004` to production FIRST
  (additive, NULL-able columns: old code ignores them), THEN merges.
  Alternative: the worker inserts `rolled` only if the column exists.
  Which?
- **Q3 Public endpoint.** The new JSON sits on the existing public read
  token (already in the public repo, backlog C9) and exposes tickets and
  prices of a DEMO fleet. Acceptable, or a separate token?
- **Q4 "Now" state.** From Redis `fxmatrix:state:<inst>` if it holds
  per-layer `virtual_level`; otherwise derived from events (a position
  with `ROLL_ACCEPTED`, no `ROLL_FILLED`, still open per `fill_logs`).
  Prefer one, or both with a disagreement flag?
- **Q5** Anything in C56's scope (fxmatrix backlog) missing below?

## GEMINI'S ANSWERS (2026-09-26) AS APPLIED

- **Q1 accepted, tightened by Claude.** Build the position set per closed
  layer, de-duplicated: the `position_id` of `entry_deal_ticket`, of
  `exit_deal_ticket`, and of every deal whose `order_ticket` is the
  layer's exit ORDER (a CloseBy involves the layer's position AND the
  position its exit order opened; the exit-order side's commission must
  not be lost). Sum `commission` and `swap` over `fill_logs` deals with
  `position_id IN (<set>)`, once each. Prove it on real-shaped rows in
  the tests; if production-shaped data cannot give the exit order's
  position, STOP (F2).
- **Q2 accepted.** Migration 004 is applied to production FIRST, then the
  merge. No `information_schema` check in the worker.
- **Q3 accepted.** Keep the existing public token.
- **Q4 accepted in part.** Events are the authority for WHICH layers are
  rolled (a `ROLL_ACCEPTED` without a later `ROLL_FILLED` or
  `ROLL_REFUSED`, position still open). Events do not carry depth,
  market or current exit prices, so those come from Redis state with
  `state_age_s`. Per side, `rolled_by_events` and `rolled_by_state`
  (null if state lacks `virtual_level`, F3) and `disagree` (true when
  both exist and differ).
- **Q5** none.

## BRANCH

Work on a NEW branch `c56-ejection-telemetry` from pipshed `main` at
`5e8b904`. Commit in the order below and PUSH the branch after each
commit. Do not merge.

## PART 1 -- MIGRATION `migrations/004_c56_rolls.sql`

- `ALTER TABLE scalp_history ADD COLUMN rolled boolean;`
- `ALTER TABLE daily_snapshots ADD COLUMN` each of: `rolls_accepted int`,
  `rolls_refused int`, `roll_filled_events int`, `rolled_fills int`,
  `rolled_realised numeric(14,2)`, `roll_mismatch int`,
  `roll_stranded_warns int`, `roll_stuck_warns int`.
- Additive only. No backfill, no NOT NULL, no defaults that rewrite rows.

## PART 2 -- INGEST

- `SCALP_FIELDS` gains `"rolled"`; the scalp INSERT writes it. A payload
  without the key stores NULL (older builds).

## PART 3 -- ROLLS OUT OF SCALP COUNTS

- `s4_scalps.py`: `EJECT_SQL` selects tickets for
  `code IN ('EJECT_FILLED', 'ROLL_FILLED')`; `SCALP_HISTORY_SQL` adds
  `AND rolled IS NOT TRUE`. Keep the variable name; add a comment.
- Every place pipshed COUNTS scalps (the Daily card, today-scalps,
  per-instance scalp totals on the dashboard, `archive_counts.py` flags
  that count scalps): rolled rows are excluded exactly as ejected rows
  are. Where the dashboard LISTS scalp records, keep rolled rows but mark
  them (a `rolled` flag in the JSON; a visible marker in the table).
  Report every site you changed and every site you checked and left.

## PART 4 -- DAILY SNAPSHOT AND CARD

- `DAILY_EVENTS_SQL` also selects `ROLL_ACCEPTED`, `ROLL_REFUSED`,
  `ROLL_FILLED`, `ROLL_STRANDED`, `ROLL_CLOSING_STUCK`.
- `DAILY_SCALPS_SQL` returns rows where `ejected IS TRUE OR rolled IS
  TRUE`, with both flags, so `derive_counts` can split them.
- `derive_counts` adds: `rolls_accepted`, `rolls_refused`,
  `roll_filled_events`, `roll_stranded_warns`, `roll_stuck_warns` (event
  counts), `rolled_fills` and `rolled_realised` (rolled scalp rows in the
  day, as for ejected), `roll_mismatch = rolled_fills -
  roll_filled_events`. Ejected figures must not change for rows that are
  ejected and not rolled.
- The new columns are stored, selected and exposed through
  `daily_row_to_public` like the eject ones.
- `WARN_CRITICAL_ALLOW` gains `ROLL_STRANDED` and `ROLL_CLOSING_STUCK`.
- Daily card: add columns "Rolls" (`accepted/filled`) and "Roll $"
  (`rolled_realised`) next to the eject columns; update every `colspan`.

## PART 5 -- NEW PUBLIC JSON: `/api/g/<token>/ejection[/<path:_ignored>]`

Same token check, no-cache headers and fleet scoping as `/status`. The
`_ignored` path segment is a cache-buster and is never parsed. Query
`hours` (default 48, clamp 1..168). Only instances in `GRIND_INSTANCES`.
Times as ISO UTC strings from `ea_time_ms`. Response keys, in order:

1. `generated_at`, `fleet`, `fleet_label`, `hours`.
2. `now`: per instance, per side (`L`, `S`): `depth`, `max_layers`,
   `rolled` (layers with a virtual level), `lowest_effective`, `market`,
   `last_stranded_at` (latest `ROLL_STRANDED` for that side, or null),
   `state_age_s`, and `layers`: [{`layer_index`, `ticket`, `entry`,
   `virtual_level` (null if unrolled), `exit_target`}], sorted by
   `layer_index`. Per Q4 as applied: `rolled_by_events`,
   `rolled_by_state`, `disagree`.
3. `rolls`: one row per (instance, position ticket) with a `ROLL_*` event
   in the window: `instance_id`, `side`, `layer_index`, `ticket`, `entry`,
   `level`, `target`, `cost_pips`, `clamped`, `source`, `accepted_at`,
   `status` (`accepted`, `filled`, `refused`), `filled_at`,
   `minutes_to_fill`, and `realised` {`gross`, `commission`, `swap`,
   `net`} for filled rows (Q1 method; null if not yet filled).
4. `ejections`: the same shape from `EJECT_*` (`source` auto/command,
   `offset` instead of `level`/`target`).
5. `days`: per FTMO day in the window (22:00Z boundary, `ftmo_daily`),
   per instance, per side: `scalps` {`count`, `gross`, `net`}, `rolls`
   {`accepted`, `filled`, `net`}, `ejections` {`filled`, `net`},
   `commission`, `swap`, `closed_net` (= scalps.net + rolls.net +
   ejections.net). "Scalps" = closed rows neither rolled nor ejected.
6. `warnings`: every `ROLL_STRANDED` and `ROLL_CLOSING_STUCK` in the
   window with its detail.
7. `reconciliation`: per instance: `roll_mismatch`, `eject_mismatch`,
   `accepted_unfilled` [{ticket, accepted_at, age_h}] (accepted, not
   filled, not refused), `refused` counts by reason.

Keep the handler thin: put the building in a pure function in a new
module `ejection_view.py` that takes rows and returns the dict, so tests
can call it without Flask or Redis.

## PART 6 -- DASHBOARD PANEL

A "Passive ejection" panel on the dashboard (same fleet): today's rolls
and ejections (time, instance, side, layer, cost pips, status, net $)
and a one-line per-instance "now" (depth/cap, rolled count, stranded).
Fed by the same builder. Plain table; no new libraries.

## TESTS FIRST -- `scripts/verify_ejection_telemetry.py`

Commit 1 = THIS PROMPT as `prompts/c56_ejection_telemetry.md` (added by
name), the tests plus STUBS (the migration file absent or empty,
`ejection_view.py` returning an empty dict, no other change). Run them;
report the stub result. Commit 2 onward = the change; report the real
result. Scratch DB via `VERIFY_DATABASE_URL` only. Fixture (all hand
values; GBPUSD_OPTB, account 1, one FTMO day D = 22:00Z D-1 to 22:00Z D):
- scalps (OUT_BY, not rolled): 3 rows, gross +0.50 each; commission
  -0.07 on each of their 6 deals (entry and CloseBy sides); swap 0.
- one roll: `ROLL_ACCEPTED` at D 10:00Z (ticket 9001, side L, layer 0,
  entry 1.33000, level 1.32600, target 1.32650, cost_pips 35.0, source
  "live"); `ROLL_FILLED` at 10:17Z; its scalp row `rolled=true`, gross
  -3.50; commission -0.07 x 2; swap -0.20.
- one `ROLL_REFUSED` (ticket 9002, reason MODIFY_FAILED); one
  `ROLL_STRANDED` (side L); one `EJECT_ACCEPTED` source auto + its
  `EJECT_FILLED` (ticket 9003), scalp row `ejected=true`, gross -1.00,
  commission -0.14, swap 0.

| test | checks | expected (by hand) | stub |
|---|---|---|---|
| ET1 | 004 adds `scalp_history.rolled` and the 8 daily columns | all present | FAIL |
| ET2 | scalp payload `"rolled":true` stored true; missing key -> NULL | t / NULL | FAIL |
| ET3 | s4 count for GBPUSD_OPTB on D (three long scalps + the short scalp below; the ejection excluded as today) | 4 (stub counts the roll too: 5) | FAIL |
| ET4 | `derive_counts` roll figures | accepted 1, refused 1, filled_events 1, rolled_fills 1, rolled_realised -3.50, mismatch 0, stranded 1, stuck 0 | FAIL |
| ET5 | eject figures unchanged | auto 1, ejected_fills 1, ejected_realised -1.00 | PASS both (must be reported: a guard, not the change) |
| ET6 | allow-list | contains ROLL_STRANDED and ROLL_CLOSING_STUCK | FAIL |
| ET7 | endpoint: bad token 404 AND good token 200 with the 7 keys | both | FAIL (good token 404 in stub) |
| ET8 | `rolls` row 9001 | status filled, minutes_to_fill 17, realised gross -3.50, commission -0.14, swap -0.20, net -3.84 | FAIL |
| ET9 | `days` for GBPUSD_OPTB side L on D | scalps count 3, gross 1.50, net 1.50 - 0.42 = 1.08; rolls filled 1, net -3.84; ejections filled 1, net -1.14; closed_net 1.08 - 3.84 - 1.14 = -3.90 | FAIL |
| ET10 | cache-buster `/ejection/abc123` same as `/ejection` | equal bodies except generated_at | FAIL |
| ET11 | `hours=0` -> 1, `hours=999` -> 168 | clamped | FAIL |
| ET12 | an instance outside `GRIND_INSTANCES` never appears | absent | FAIL |
| ET13 | `reconciliation` for ticket 9002 | in refused (MODIFY_FAILED: 1), not in accepted_unfilled | FAIL |
| ET14 | Q1 set rule: a roll whose exit ORDER opened position 7002 (entry commission -0.07) closed by CloseBy against layer position 7001 (entry -0.07, OUT_BY -0.07 on 7001 and -0.07 on 7002, swap -0.20 on 7001) | commission -0.28, swap -0.20, each deal counted once | FAIL |
| ET15 | Q4: state shows layer 0 rolled, events show none | `disagree` true | FAIL |

Put all three scalps and the ejected row on side L (direction BUY) so
ET9's side split is exercised; add one short scalp (+0.50, -0.14
commission) and assert side S separately: count 1, net 0.36.

A new test that passes in BOTH states is not testing the change: report
any besides ET5. Run every other `scripts/verify_*.py` before and after;
report any that change.

## NEGATIVE SPACE

- Do NOT touch the fxmatrix repo or any EA file. Do NOT deploy, do NOT
  run a migration against production, do NOT set Railway variables.
- Do NOT merge, no PR, do NOT push to `main`. No `git stash`, no `git add
  .` or `-u`, no checkout of files from other commits.
- Do NOT change existing JSON keys or card columns except as stated;
  additive only. Do NOT change eject semantics.
- Do NOT backfill `rolled` on old rows. Do NOT add libraries.
- Do NOT compute anything from open positions' P&L: this is CLOSED P&L.

## FAILURE MODES -- STOP AND REPORT, DO NOT IMPROVISE

- F1: a baseline `verify_*.py` fails before your change.
- F2: `scalp_history` rows cannot be joined to `fill_logs` by deal ticket
  (tickets missing or not matching) -- Q1's method then does not work.
- F3: Redis state holds no per-layer `virtual_level`: implement the
  event-derived `now` only, set `source: "events"`, and say so.
- F4: any stub-state result differs from the table above.
- F5: a scalp-counting site you cannot classify (count vs list).

## REPORT

Branch, commit hashes, the stub and real summaries, every site changed
and every site checked-and-left (Part 3), Gemini's answers as applied,
and anything in F1-F5. Deploy (operator, later, never inside 20:50-21:00Z):
migration 004 first per Q2, then merge; pushing `main` redeploys the worker.
