# ADR-159 pipshed response

## Remote branch

```
git ls-remote origin refs/heads/feat/adr159-daily-critical
346e8ae826ce6bfcdc48831546e997f788387ec0	refs/heads/feat/adr159-daily-critical
```

```
git log --oneline -3 origin/feat/adr159-daily-critical
346e8ae ADR-159: pipshed response doc with verify outputs and commit refs.
b519383 ADR-159: daily snapshots, critical banner, s4 script, and worker publish.
166c226 ADR-159: daily snapshot verify script and ftmo_daily stubs.
```

## Commit hashes (implementation order)

1. `166c22658ac9e68c0c15c537ea1017e1456051b9` -- tests + stubs
2. `b519383587684b2609dac343fdbaf9dd555e08ab` -- implementation
3. `346e8ae826ce6bfcdc48831546e997f788387ec0` -- response doc

## Commit 2 diff stat

```
 app.py                            |  62 ++++++++
 archive_worker.py                 | 302 +++++++++++++++++++++++++++++++++++++-
 ftmo_daily.py                     | 273 +++++++++++++++++++++++++++++++++-
 migrations/002_adr159_daily.sql   |  34 +++++
 scripts/s4_scalps.py              | 197 +++++++++++++++++++++++++
 scripts/verify_daily_snapshots.py |  53 ++++---
 templates/dashboard.html          | 161 ++++++++++++++++++++
 7 files changed, 1055 insertions(+), 27 deletions(-)
```

## Stub-check output (commit 1)

```
DS1 FAIL: 
DS2 FAIL: 
DS3 FAIL: 
DS4 FAIL: 
DS5 FAIL: 
DS6 FAIL: 
DS7 FAIL: 
DS8 FAIL: 
DS9 FAIL: 
DS10 FAIL: 'ejected'
DS11 FAIL: 
DS12 FAIL: 
DS13 FAIL: 
DS14 FAIL: module 'archive_worker' has no attribute 'ARCHIVE_DAILY_KEY'
DS15 FAIL: 
DS16 FAIL: 
SUMMARY passed=0 failed=16
```

## Real-branch verify (`scripts/verify_daily_snapshots.py`)

```
DS1 OK: summer bounds 2026-09-23
DS2 OK: winter bounds 2026-11-10
DS3 OK: October switch 25h day
DS4 OK: March switch 23h day
DS5 OK: ftmo_day_of_utc boundary at 22:00Z summer
DS6 OK: parse_ftmo_day formats and rejection
DS7 OK: snapshot_row_from_detail contract mapping
2026-09-23 13:48:55,521 WARNING DAILY_SNAPSHOT skipped: missing account_login or ftmo_day
DS8 OK: missing account_login skips snapshot, ea_events commits
DS9 OK: valid DAILY_SNAPSHOT dual insert one commit
DS10 OK: scalp ejected fields pass through or None
DS11 OK: derive_counts fixture totals
DS12 OK: build_daily_derived selects ftmo_day >= today-7
DS13 OK: critical_groups merge, filter, sort
DS14 OK: daily and critical public routes
2026-09-23 13:48:55,788 WARNING daily table build failed: daily derived failed
DS15 OK: DAILY_SNAPSHOT batch drains despite daily build DataError
DS16 OK: s4_counts CloseBy pairs and median ratio
SUMMARY passed=16 failed=0
```

## Other `scripts/verify_*.py` last lines

```
verify_archive_action.py: All archive action checks passed.
verify_archive_scalp_tap.py: All archive scalp tap checks passed.
verify_archive_worker.py: All archive worker checks passed.
verify_carry_table.py: All carry table checks passed.
verify_daily_snapshots.py: SUMMARY passed=16 failed=0
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

## Gemini rulings (code impact)

- Q1: Optional nullable `account_login` on `scalp_history` and snapshot attribution is implemented.
- Q2-Q4: Accepted as specified (Prague DST in Python, received_at vs ea_time_ms split, hourly + forced daily derived build).

Line count: 106
