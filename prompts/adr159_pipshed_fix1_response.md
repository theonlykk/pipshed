# ADR-159 fix1 response

## Remote branch

```
git ls-remote origin refs/heads/feat/adr159-daily-critical
d6443ea5b88b126a43cb963245130104a66f8d34	refs/heads/feat/adr159-daily-critical
```

```
git log --oneline -6 origin/feat/adr159-daily-critical
d6443ea ADR-159 fix1: response doc with verify and mutation outputs.
e36daa9 ADR-159 fix1: rollback after swallowed carry, daily, and critical build errors.
0428b1b ADR-159 fix1: extend DS11 offset guard and add DS17 rollback test.
f73147e ADR-159: pipshed response doc with verify outputs and commit refs.
b519383 ADR-159: daily snapshots, critical banner, s4 script, and worker publish.
166c226 ADR-159: daily snapshot verify script and ftmo_daily stubs.
```

## New commit hashes (on top of f73147e)

1. `0428b1be8af06596d33e69ca737562e5a97ae234` -- tests (DS11 + DS17)
2. `e36daa9ebd5e960e5dfd5f9af022b4e1d2c49583` -- rollback after swallowed build errors
3. `d6443ea5b88b126a43cb963245130104a66f8d34` -- this response doc

## Commit 1 verify output

```
DS1 OK: summer bounds 2026-09-23
DS2 OK: winter bounds 2026-11-10
DS3 OK: October switch 25h day
DS4 OK: March switch 23h day
DS5 OK: ftmo_day_of_utc boundary at 22:00Z summer
DS6 OK: parse_ftmo_day formats and rejection
DS7 OK: snapshot_row_from_detail contract mapping
2026-09-23 15:20:39,135 WARNING DAILY_SNAPSHOT skipped: missing account_login or ftmo_day
DS8 OK: missing account_login skips snapshot, ea_events commits
DS9 OK: valid DAILY_SNAPSHOT dual insert one commit
DS10 OK: scalp ejected fields pass through or None
DS11 OK: derive_counts fixture totals
DS12 OK: build_daily_derived selects ftmo_day >= today-7
DS13 OK: critical_groups merge, filter, sort
DS14 OK: daily and critical public routes
2026-09-23 15:20:39,595 WARNING daily table build failed: daily derived failed
DS15 OK: DAILY_SNAPSHOT batch drains despite daily build DataError
DS16 OK: s4_counts CloseBy pairs and median ratio
2026-09-23 15:20:39,598 WARNING daily table build failed: daily derived failed
DS17 FAIL: 
SUMMARY passed=16 failed=1
```

## Mutation run (_scalp_utc_close offset zeroed, then reverted)

```
DS11 FAIL: 
SUMMARY passed=15 failed=2
```

```
git status -s
 M scripts/verify_daily_snapshots.py
```

## Commit 2 verify output

```
DS1 OK: summer bounds 2026-09-23
DS2 OK: winter bounds 2026-11-10
DS3 OK: October switch 25h day
DS4 OK: March switch 23h day
DS5 OK: ftmo_day_of_utc boundary at 22:00Z summer
DS6 OK: parse_ftmo_day formats and rejection
DS7 OK: snapshot_row_from_detail contract mapping
2026-09-23 16:15:32,601 WARNING DAILY_SNAPSHOT skipped: missing account_login or ftmo_day
DS8 OK: missing account_login skips snapshot, ea_events commits
DS9 OK: valid DAILY_SNAPSHOT dual insert one commit
DS10 OK: scalp ejected fields pass through or None
DS11 OK: derive_counts fixture totals
DS12 OK: build_daily_derived selects ftmo_day >= today-7
DS13 OK: critical_groups merge, filter, sort
DS14 OK: daily and critical public routes
2026-09-23 16:15:33,535 WARNING daily table build failed: daily derived failed
DS15 OK: DAILY_SNAPSHOT batch drains despite daily build DataError
DS16 OK: s4_counts CloseBy pairs and median ratio
2026-09-23 16:15:33,541 WARNING daily table build failed: daily derived failed
2026-09-23 16:15:33,541 WARNING critical list build failed: critical list failed
DS17 OK: swallowed build errors roll back
SUMMARY passed=17 failed=0
```

## Other scripts/verify_*.py last lines

```
verify_archive_action.py: All archive action checks passed.
verify_archive_scalp_tap.py: All archive scalp tap checks passed.
verify_archive_worker.py: All archive worker checks passed.
verify_carry_table.py: All carry table checks passed.
verify_daily_snapshots.py: SUMMARY passed=17 failed=0
verify_dashboard_rings.py: All dashboard ring checks passed.
verify_db_migrate.py: All db_migrate checks passed.
verify_fxgrind_panel.py: AssertionError
verify_grind_arm_cards.py: Unit OK: _summarize_grind_arm uses max(api_count)
verify_grind_display_gaps.py: 4e OK: grind_rings structure matches GRIND_RINGS mapping
verify_grind_exposure.py: AssertionError
verify_grind_pnl_render.py: KeyError: 'arm_summaries'
verify_nzd_ext_registration.py: 8 OK: GRIND_DEFAULT_INSTANCE unchanged
verify_summary_carry.py: All summary and carry audit checks passed.
```

## Gemini Q1

Fix 1 rolls back in `try_carry_build` as well (same failure mode as daily/critical).

Line count: 114
