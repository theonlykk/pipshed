This message has a line count at the bottom

# PIPSHED: ADR-159 -- DAILY SNAPSHOT TABLE, CRITICAL BANNER, s4 COUNTER

## AUDIT TRAIL

| item | detail | status |
|---|---|---|
| Design | fxmatrix `docs/architecture/ADR-159-daily-snapshot-critical-banner.md`, ACCEPTED rev 2 at `600fc8d` (P1-P5 are this prompt; D1-D9 are the EA prompt, later) | read by Claude |
| Baseline | pipshed `origin/main` at `5153977` | read by Claude |
| Deploy order | pipshed FIRST. The EA does not emit `DAILY_SNAPSHOT` or the new `scalp_closed` fields until the cycle-3 attach, so everything here must work on an archive that has none of them yet | ADR s5 |
| G6 verified on broker data | 23 Sep deal dump (4,317 deals): all 972 CloseBy orders have EXACTLY two OUT_BY deals; their comments are `#<pos> by #<pos>` (the EA's comment parser rejects these, so `fill_logs.role` is null on OUT_BY rows); both deals carry the instance's magic, so both reach `fill_logs` | verified by Claude |
| Existing facts | `ea_events` purged after 90 days (`run_retention_if_due`); `fill_logs` and `scalp_history` never purged; `ea_time_ms` is UTC epoch ms; `EJECT_ACCEPTED.detail.source` is `"auto"` or `"command"`; `CARRY_PASS_SUMMARY` / `CARRY_PASS_INCOMPLETE` detail has integer `clamped`; `STARTUP_EXIT_SHORTFALL`, `QUARANTINE_ENTER`, `WARN_API_ENTRY_STOP` are archived at level `WARN` | read in fxmatrix source |

## FOR GEMINI (review before Cursor starts)

Rule on each; reason from the cited code, not general architecture.

- **Q1.** The ADR adds `ejected` and `broker_utc_offset_s` to
  `scalp_closed`. This prompt also accepts an optional `account_login`
  there (nullable column), so ejected-fill counts can be attributed to
  an account without relying on time alone (A5). Accept, or drop it?
- **Q2.** The FTMO day is computed in Python from a hard-coded EU rule
  (CEST from 01:00 UTC on the last Sunday of March to 01:00 UTC on the
  last Sunday of October), not with Postgres `AT TIME ZONE`. This
  mirrors the EA's own rule and is testable without a database. Accept?
- **Q3.** The banner's "last 24 h" uses `received_at` (it is about what
  the operator has not yet seen); daily attribution uses `ea_time_ms`
  (ADR P2). Accept the split?
- **Q4.** The derived-column rebuild runs hourly AND is forced when a
  batch contains a `DAILY_SNAPSHOT`, the same way `CARRY_SNAPSHOT` forces
  the carry table. Accept?

## BRANCH

`feat/adr159-daily-critical` from `origin/main`. THREE commits, in order:

1. **Tests + stubs.** `scripts/verify_daily_snapshots.py` complete;
   `ftmo_daily.py` with every public function present and raising
   `NotImplementedError`. Nothing else changes. Run the verify script and
   record its full output.
2. **Implementation.** Everything else in this prompt.
3. **Response doc** (see RESPONSE FORMAT).

Push after EACH commit. Do NOT merge -- merging to `main` deploys to
Railway, and the migration is applied by the operator afterwards.

## 1. MIGRATION `migrations/002_adr159_daily.sql`

Plain SQL, same style as `001`. No `DROP` of anything existing.

```
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
```

No retention job touches `daily_snapshots` -- ever.

## 2. NEW MODULE `ftmo_daily.py` (pure functions, no I/O)

Imported by `archive_worker.py` and `scripts/s4_scalps.py`.

- `ftmo_day_bounds_utc(day)` -> `(start, end)`, tz-aware UTC datetimes:
  local midnight Europe/Prague of `day` and of `day + 1`. CEST (UTC+2)
  applies from 01:00 UTC on the last Sunday of March until 01:00 UTC on
  the last Sunday of October; CET (UTC+1) otherwise. Compute the last
  Sundays arithmetically; no `zoneinfo`, no new dependency.
- `ftmo_day_of_utc(dt)` -> `date`: the FTMO day containing UTC instant `dt`.
- `parse_ftmo_day(text)` -> `date`: accepts `"2026.09.23"` (the EA's
  format) and `"2026-09-23"`; anything else raises `ValueError`.
- `snapshot_row_from_detail(detail)` -> `dict` or `None`: maps the
  **contract** below into `daily_snapshots` columns. Returns `None` if
  `account_login` or `ftmo_day` is missing or unparsable. Every other
  field may be absent or `null` and maps to `None` -- never to 0.
- `derive_counts(events, scalps, start, end, account_login)` -> `dict` of
  the derived columns (section 3.3), from plain row tuples.
- `critical_groups(rows, now)` -> list (section 3.4).
- `s4_counts(fill_rows, eject_tickets, day_of)` (section 6).

**The `DAILY_SNAPSHOT` contract** (keys of `ea_events.detail`; the EA
prompt will emit exactly these): `account_login`, `ftmo_day`,
`balance_start`, `equity_start`, `balance_end`, `equity_end`, `realised`,
`nontrade`, `inventory_pnl`, `total`, `swap_day`, `positions_long`,
`positions_short`, `orders`, `guard_total`, `guard_age_s`,
`breaker_tripped`, `premidnight_seen`, `broker_utc_offset_s`,
`start_known`, `balance_start_source`.

## 3. `archive_worker.py`

**3.1 Scalp fields.** Append `ejected`, `broker_utc_offset_s`,
`account_login` to `SCALP_FIELDS` and to the `scalp_history` INSERT.
Absent keys stay `None` (old payloads keep working).

**3.2 Snapshot insert.** In `insert_batch` AND `insert_single`: after an
`ea_events` row whose `code == "DAILY_SNAPSHOT"` is executed, call
`snapshot_row_from_detail`; if it returns a row, add `instance_id`,
`session_id`, `ea_time_ms`, `received_at`, `detail`, and execute
`INSERT INTO daily_snapshots (...) ... ON CONFLICT (account_login,
ftmo_day) DO NOTHING` on the SAME cursor, before the existing commit. A
`None` row is logged at WARNING and skipped; the `ea_events` row is
still inserted and the batch still commits.

**3.3 Derived columns** -- `build_daily_derived(conn)`:
- Select `daily_snapshots` rows with `ftmo_day >= ftmo_day_of_utc(now) - 7
  days`. Older rows are frozen (never recomputed).
- For each row, `(start, end) = ftmo_day_bounds_utc(ftmo_day)`, as epoch
  ms. Fetch `code, level, detail` from `ea_events e JOIN session_accounts
  s ON e.session_id = s.session_id` where `s.account_login = row's` and
  `e.ea_time_ms >= start_ms AND e.ea_time_ms < end_ms` and (`e.code IN
  ('EJECT_ACCEPTED','EJECT_FILLED','CARRY_PASS_SUMMARY',
  'CARRY_PASS_INCOMPLETE')` OR `e.level = 'CRITICAL'`).
- Fetch `scalp_history` rows with `ejected IS TRUE` and `received_at`
  within `[start - 1 day, end + 1 day)`: `close_time_broker,
  broker_utc_offset_s, account_login, gross_pnl`.
- `derive_counts` returns: `ejections_auto`, `ejections_command`
  (`EJECT_ACCEPTED` by `detail.source`), `eject_filled_events`,
  `carry_clamps` (sum of `detail.clamped` over both carry codes),
  `critical_events` (level CRITICAL), `ejected_fills` and
  `ejected_realised` (sum of `gross_pnl`) over scalp rows whose UTC close
  time `close_time_broker - broker_utc_offset_s seconds` lies in
  `[start, end)`, AND whose `account_login` is null or equal to the
  row's. Rows with a null `broker_utc_offset_s` are skipped -- no
  hard-coded broker offset anywhere. `eject_mismatch = ejected_fills -
  eject_filled_events`.
- `UPDATE daily_snapshots SET <derived>, derived_at = now() WHERE id = ...`.
- Then publish `fxmatrix:daily:table`: `{"generated_at", "rows"}`, rows
  newest `ftmo_day` first, at most 60, each with every column except
  `detail` and `id`, plus `carried = equity_start - balance_start` (null
  if either is null). Dates and times as ISO strings.

Scheduling: `try_daily_build(conn, redis_client, force)` exactly like
`try_carry_build`: an hourly interval (key `fxmatrix:daily:last_build`),
forced when a processed batch contains a `DAILY_SNAPSHOT` ea_event (mirror
`batch_contains_carry_snapshot`), connection errors re-raised, any other
exception logged at WARNING and swallowed. **A failing build must never
stop the queue drain.**

**3.4 Critical list** -- `build_critical_list(conn)`, every 60 s (key
`fxmatrix:critical:last_build`), same try/swallow wrapper:
- SQL: `SELECT instance_id, level, code, received_at FROM ea_events WHERE
  received_at > now() - interval '24 hours' AND level IN
  ('CRITICAL','WARN')`.
- `critical_groups` keeps level CRITICAL (any code) and level WARN only
  for `STARTUP_EXIT_SHORTFALL`, `QUARANTINE_ENTER`, `WARN_API_ENTRY_STOP`.
  Groups by `(instance_id, level, code)`: `count`, `first_at`, `last_at`.
  Sorted CRITICAL first, then by `last_at` descending.
- Publish `fxmatrix:critical:last24h`: `{"generated_at", "rows"}`.

## 4. `app.py`

Two public routes, copied from `public_carry_table` (same token check,
same `/<path:_ignored>` cache-buster form, same no-cache headers, same
empty payload when the Redis key is absent):
`/api/g/<token>/daily` -> `fxmatrix:daily:table`,
`/api/g/<token>/critical` -> `fxmatrix:critical:last24h`.
Add both to the route list in the module docstring. No other change.

## 5. `templates/dashboard.html`

- **Banner:** a new `<div id="criticalBanner">` directly after the
  `.header` div, hidden when there are no rows. Red background when any
  row is CRITICAL, otherwise amber. One line per group:
  `INSTANCE  CODE  xCOUNT  last HH:MMZ`. If `generated_at` is older than
  5 minutes, show a grey line "critical list stale (worker?)" instead of
  hiding. Fetch `/api/g/<token>/critical/<Date.now()>` every 30 s.
- **Daily card:** a new `.card` `id="dailySection"` directly after
  `#carrySection`, table class `teams-table`, wrapped in a div with
  `overflow-x:auto`. Columns: FTMO day, Account, Realised, Inventory,
  Total, Carried, Swap, L/S, Orders, Guard, Breaker, Pre-mid, Eject
  A/C, Ejected fills ($), Clamps, CRIT. **Null renders as `--`, never
  0.** Negative money uses the existing red class used for negative
  carry. Fetch every 30 s, mirroring `fetchCarryTable`.
- Do not remove or rename any existing element id.

## 6. NEW `scripts/s4_scalps.py` (read-only)

Same connection pattern as `scripts/archive_counts.py` (`DATABASE_URL`,
`psycopg2`, no writes, no transaction left open).

- Default: the last 7 complete FTMO days; `--days N` to change.
- Pull `instance_id, order_ticket, position_id, ea_time_ms` from
  `fill_logs WHERE entry_type = 'OUT_BY'` in the window, and the set of
  `ticket` from `ea_events WHERE code = 'EJECT_FILLED'` in the window.
- `s4_counts`: a scalp is a DISTINCT `order_ticket` per instance; a pair
  is EXCLUDED if either of its rows' `position_id` is in the eject set;
  the day is `ftmo_day_of_utc(ea_time_ms)`.
- Print per FTMO day: each instance's scalps, and for instances whose id
  ends `_OPT`, the ratio to that day's median over `_OPT` instances (the
  s4 primary; others are listed, not in the median). Also print the
  `scalp_history` count per instance with `ejected IS NOT TRUE` for the
  same days (UTC close time via the offset; rows without an offset
  counted separately as `no_offset`) and flag any day where the two
  counts differ.
- `--probe`: print, for the last 14 days, the number of OUT_BY rows, the
  distribution of rows per `order_ticket` (1 / 2 / more), and the
  distinct `role` values on OUT_BY rows. The operator runs this once
  after merge to confirm the G6 facts on the archive itself.

## 7. TESTS -- `scripts/verify_daily_snapshots.py`

Style of `scripts/verify_carry_table.py` (FakeRedis, fake cursor, no
database), BUT each check runs in `try/except` and prints `DSn OK: ...` or
`DSn FAIL: <exception>`, and the script ends with exactly one line
`SUMMARY passed=<p> failed=<f>`, exit code 1 if any failed. Checks:

- **DS1** summer bounds: 2026-09-23 -> [2026-09-22 22:00Z, 2026-09-23 22:00Z)
- **DS2** winter bounds: 2026-11-10 -> [2026-11-09 23:00Z, 2026-11-10 23:00Z)
- **DS3** October switch: 2026-10-25 -> [2026-10-24 22:00Z, 2026-10-25 23:00Z) (25 h)
- **DS4** March switch: 2026-03-29 -> [2026-03-28 23:00Z, 2026-03-29 22:00Z) (23 h)
- **DS5** `ftmo_day_of_utc`: 2026-09-22 21:59:59Z -> 09-22; 22:00:00Z -> 09-23
- **DS6** `parse_ftmo_day` accepts both formats, rejects `"23/09/2026"`
- **DS7** full snapshot maps every contract field; a `start_known=false`
  snapshot keeps `equity_start`, `inventory_pnl`, `total`, `swap_day` as
  `None`
- **DS8** snapshot missing `account_login` -> `None`, and `insert_batch`
  still inserts its `ea_events` row and commits once
- **DS9** `insert_batch` with a valid `DAILY_SNAPSHOT` executes the
  `ea_events` INSERT then the `daily_snapshots` INSERT (with `ON CONFLICT
  (account_login, ftmo_day) DO NOTHING`), one commit
- **DS10** scalp row: `ejected`, `broker_utc_offset_s`, `account_login`
  pass through; an old payload without them gives `None` for all three
- **DS11** `derive_counts` on a fixture: 1 auto + 1 command accept, 2
  `EJECT_FILLED`, carry clamped 2 + 1 = 3, 1 CRITICAL; scalps: two
  ejected inside the window (one only inside once the 10800 s offset is
  applied), one outside, one with null offset, one of another account
  -> `ejected_fills=2`, `ejected_realised` = their sum, `eject_mismatch=0`
- **DS12** `build_daily_derived` selects rows from `today - 7` only
  (assert the date parameter the fake cursor receives)
- **DS13** `critical_groups`: three identical CRITICAL rows -> one group,
  count 3, correct first/last; allow-listed WARN kept; `STRAY_L0_CANCEL`
  WARN dropped; CRITICAL sorts before WARN
- **DS14** routes: `/daily` and `/critical` return the Redis payload; an
  absent key returns empty `rows`; a wrong token returns 404
- **DS15** `worker_cycle` with a `DAILY_SNAPSHOT` in the batch forces the
  daily build; a build that raises `psycopg2.DataError` does not stop
  the drain (queue and processing both end empty, one commit)
- **DS16** `s4_counts`: instance A has 3 CloseBy orders (2 rows each),
  one of whose rows has an ejected `position_id` -> 2; instance B 4;
  `_ALT` instance excluded from the median; ratios correct

**Stub-check (commit 1):** every DS check is expected to FAIL (stubs raise,
and the worker/app changes do not exist yet): `SUMMARY passed=0 failed=16`.
Report the actual line. **Real branch (commit 2):** `SUMMARY passed=16
failed=0`, AND every existing `scripts/verify_*.py` still passes unchanged
-- run each and report its last line.

## 8. NEGATIVE SPACE

- No change to retention, the queue/processing/deadletter mechanics, the
  carry table, `/status`, the heartbeat path, or any existing element id.
- No hard-coded broker UTC offset. No `zoneinfo`, no new dependency.
- The derived and critical builds never block or stop the drain.
- No write in `s4_scalps.py`. No migration applied by Cursor.
- ASCII only. Stage by exact path. No merge, no PR.

## RESPONSE FORMAT

`prompts/adr159_pipshed_response.md` (commit 3): the three commit hashes
AS THEY EXIST ON ORIGIN (paste the output of `git ls-remote origin
refs/heads/feat/adr159-daily-critical` and `git log --oneline -3
origin/feat/adr159-daily-critical`), the diff stat of commit 2, the
stub-check output (commit 1) verbatim, the real-branch verify output
verbatim, and the last line of every other `scripts/verify_*.py`.
Answers to Gemini's rulings go in a section only if they changed the
code. Footer: true line count. Reply in chat with ONLY the branch, the
three hashes, and one line saying all three are pushed.

Line count: 300
