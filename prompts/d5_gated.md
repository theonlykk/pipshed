This message has a line count at the bottom

# PIPSHED D5 (ADR-160, C36): GATED SECONDS AND HISTORY_OK AS COLUMNS, GATED HOURS ON THE DAILY CARD AND IN S4, TESTS FIRST

## AUDIT TRAIL

| item | detail | status |
|---|---|---|
| Why | ADR-160 (EA, live since cycle 3) adds `"gated_seconds":<int>` and ADR-159 `"history_ok":<bool>` to every `DAILY_SNAPSHOT` detail. They are stored only inside `detail` jsonb; the Daily card and `s4_scalps.py` cannot show them. ADR-160 s9 D5 | design |
| Base | pipshed `main` at `39df6e0` + this spec | verified by Claude |
| Table | `daily_snapshots` (`migrations/002_adr159_daily.sql`), `detail jsonb`, `UNIQUE (account_login, ftmo_day)` | verified |
| Insert | `DAILY_SNAPSHOT_INSERT` (`archive_worker.py:127`) lists its columns explicitly; UNCHANGED here | verified |
| Select | `DAILY_SNAPSHOTS_SELECT` (`archive_worker.py:112-125`) ends `derived_at`; `build_daily_derived` zips `cur.description`; `daily_row_to_public` (`:345`) copies every key and adds `carried` | verified |
| Card | `templates/dashboard.html`: header `<th>Pre-mid</th>` 1010, loading row `colspan="16"` 1018; `renderDailyTable` 1697, empty row `colspan="16"` 1702, pre-mid cell 1723; `dailyCell(val, decimals)` 1638 | verified |
| s4 | `scripts/s4_scalps.py`: `connect_readonly` 35, `run_main` 88, day header print 108 | verified |
| Tests | `scripts/verify_daily_snapshots.py`: `FakeCursor.description` for `WHERE ftmo_day >=` ends `"derived_at"` (line 79), `fetchall` returns `conn.daily_snapshot_rows` for the same SQL; `CHECKS` ends DS17 (545); baseline `SUMMARY passed=17 failed=0` | verified by running |
| Dry run | Claude implemented this spec in a scratch copy: stub state `SUMMARY passed=17 failed=5` (DS18-DS22), real `22/0`; every other `scripts/verify_*.py` unchanged (the three C33 failures are pre-existing) | verified |
| SQL | the migration below was run by Claude on PostgreSQL 16: existing rows backfilled (5400 -> 5400, `true` -> t); missing key, string, negative, 1e15 and a NULL detail -> NULL; new inserts compute; an explicit value is refused | verified |

## FOR GEMINI

- **Q1.** GENERATED STORED columns computed from `detail`, instead of
  parsing in the worker plus an `UPDATE` backfill (C36's wording). The
  insert path does not change, so a gap between Railway's deploy and the
  manual migrate cannot deadletter a snapshot, and a malformed or
  out-of-range value becomes NULL instead of failing the insert. Accept?
- **Q2.** Gated hours shown as-is per account row (no fleet adjustment),
  and printed per account per day by `s4_scalps.py`. Accept?

## BRANCH

`feat/d5-gated` from `origin/main`. TWO commits (tests + stubs, then
implementation), push after each. Run `scripts/verify_daily_snapshots.py`
after each commit and include its full output. No merge.

## 1. BUILD (commit 2)

1. New `migrations/003_adr160_gated.sql`, EXACTLY:
```
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
```
2. `archive_worker.py`: in `DAILY_SNAPSHOTS_SELECT` the last line becomes
   `       derived_at, gated_seconds, history_ok`. In `daily_row_to_public`,
   before `return out`: `gs = row_dict.get("gated_seconds")`;
   `out["gated_hours"] = None if gs is None else float(gs) / 3600.0`.
3. `templates/dashboard.html`: `<th>Gated (h)</th>` directly after
   `<th>Pre-mid</th>`; in `renderDailyTable`, directly after the pre-mid
   cell: `'<td>' + dailyCell(row.gated_hours, 1) + '</td>' +`; both
   `colspan="16"` of the daily table become `colspan="17"`.
4. `scripts/s4_scalps.py`:
   - `GATED_SQL = "SELECT account_login, ftmo_day, gated_seconds FROM
     daily_snapshots WHERE ftmo_day >= %s AND ftmo_day <= %s"`.
   - `gated_by_day(conn, days)`: empty dict if `days` is empty; else one
     query with `(min(days), max(days))`; returns `{ftmo_day:
     {account_login: gated_seconds}}` (None kept as None).
   - `format_gated_line(accounts)`: `"  gated_hours: no snapshot"` if
     empty; else `"  gated_hours: "` + space-joined `<login>=<h>` sorted
     by login as an integer, `<h>` = `f"{s / 3600:.1f}"`, or `--` for None.
   - `run_main`: a third `connect_readonly()` (closed in `finally`)
     computes `gated_by_day(conn3, days)`; directly after the `FTMO day`
     print, `print(format_gated_line(gated.get(day, {})))`.

## 2. TESTS (commit 1) -- `scripts/verify_daily_snapshots.py`

Append `"gated_seconds", "history_ok"` to the END of the `FakeCursor`
description list (after `"derived_at"`). Add DS18-DS22 to `CHECKS`:

| check | asserts |
|---|---|
| DS18 | `migrations/003_adr160_gated.sql` exists, reads as ASCII, contains `GENERATED ALWAYS AS` twice, `STORED` twice, `jsonb_typeof(detail -> 'gated_seconds')`, `BETWEEN 0 AND 172800`, and no `UPDATE` |
| DS19 | `FakeConnection` with two rows as tuples in the description order, every column None except: row 1 `id=1, account_login=1514731800, ftmo_day=date(2026, 9, 23), gated_seconds=5400, history_ok=True`; row 2 `id=2, account_login=53066709, ftmo_day=date(2026, 9, 23)`. `build_daily_derived(conn, now=datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc))`: row for 1514731800 has `gated_hours == 1.5`, `gated_seconds == 5400`, `history_ok is True`; row for 53066709 has `gated_hours is None` |
| DS20 | `templates/dashboard.html` contains `<th>Gated (h)</th>` and `dailyCell(row.gated_hours, 1)`; `colspan="17"` appears exactly twice and `colspan="16"` not at all |
| DS21 | `import s4_scalps` (insert the `scripts` directory into `sys.path`): `format_gated_line({1514731800: 5400, 53066709: None}) == "  gated_hours: 53066709=-- 1514731800=1.5"` (numeric sort); `format_gated_line({}) == "  gated_hours: no snapshot"` |
| DS22 | `FakeConnection` with `daily_snapshot_rows = [(1514731800, date(2026, 9, 23), 5400), (53066709, date(2026, 9, 23), None), (1514731800, date(2026, 9, 22), 0)]`; `gated_by_day(conn, [date(2026, 9, 22), date(2026, 9, 23)])` equals `{date(2026, 9, 23): {1514731800: 5400, 53066709: None}, date(2026, 9, 22): {1514731800: 0}}`; the executed SQL contains `FROM daily_snapshots` and its params are `(date(2026, 9, 22), date(2026, 9, 23))` |

**Commit 1** `D5: verification DS18-DS22 and s4 stubs`. Stubs: in
`s4_scalps.py`, `GATED_SQL` as specified, `gated_by_day` returning `{}`,
`format_gated_line` returning `""`; `run_main` untouched. Nothing else
changes (no migration file, no worker or template change).

**Commit 2** `D5: migration 003 generated columns, gated hours on the daily card and in s4`.

**Expected:** after commit 1 `SUMMARY passed=17 failed=5` (DS18, DS19,
DS20, DS21, DS22 FAIL); after commit 2 `SUMMARY passed=22 failed=0`.

## NEGATIVE SPACE

- No change to `DAILY_SNAPSHOT_INSERT`, `ftmo_daily.py`, `app.py`,
  `db_migrate.py`, migrations 001/002 or any other route or card.
- Do not run the migration, deploy, `railway` anything, or touch Redis
  or Postgres. No merge, no PR, no amend, no `git add .` / `-u`. ASCII.
- Never change an existing check or expected value.

## FAILURE MODES -- STOP AND REPORT

- Any audit-trail site is not where stated.
- An existing DS check fails after the description change.

## FINAL REPORT (fixed format)

```
BRANCH: <git branch --show-current>
BASE:   <sha>
COMMIT1: <sha>  files: <list>  verify: SUMMARY passed=<p> failed=<f>
COMMIT2: <sha>  files: <list>  verify: SUMMARY passed=<p> failed=<f>
PUSHED: <git ls-remote origin feat/d5-gated>
DEVIATIONS: <none, or each with reason>
```

Line count: 123
