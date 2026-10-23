This message has a line count at the bottom

# CURSOR PROMPT -- FLEET E's CARD BUILT (pipshed; tests first; no order path)

From Claude (Lead Engineer), 23 Oct 2026 ~17:40Z, for Cursor in `D:\pipshed`. Not reviewed by Argon: the
operator ruled ~17:32Z (option 2) that this change goes to Cursor without Argon (pinned test lists and
a config flip only; no order path, nothing an EA reads). Code base: pipshed `320afe6`
(the `twoarm-fleets` merge, pushed 23 Oct ~16:06Z, live on every page service from ~16:09Z); `main` holds
that code plus commits that add or change only this prompt file (s5).

## 0. RESTATE AND STOP (do this first, then wait)

Before any edit: restate each of the eight changes in s3 and s4 in ONE line each, quoting the exact
`old` text of each, and list the two commits you will make (s5). Then STOP and wait for the operator to
reply "go". Do not edit, run or commit anything before "go".

## 1. AUDIT TRAIL

| # | Fact | Where (at `320afe6`) | Status |
|---|---|---|---|
| F1 | Fleet E (FTMO free trial 1515045375 on wine-e) is LIVE: twelve charts attached 23 Oct 03:04-03:25Z; first fill 03:29:01Z | fxmatrix `HANDOFF_2026-09-24.md` s88 continued 5, s89 | VERIFIED (heartbeats read 23 Oct 04:14Z and 14:50Z) |
| F2 | E's strip entry is still a placeholder: `"cycle_start": "2026-10-21"`, `"placeholder": True`, `"built": False` | `app.py` 266-281 | VERIFIED |
| F3 | E's page service `linuxe.pipshed.com` (`GRIND_FLEET=E`) answers 200 and serves E's own data | Railway "pipshed Fleet E"; read 23 Oct 16:59Z | VERIFIED |
| F4 | An account missing from `COMMISSION_PER_CLOSE_BY_ACCOUNT` is reported as unknown; one missing from `REGIME_START_BY_ACCOUNT` has no "cycle" window | `sr_table.py` 24-33, 41-46, 129-134 | VERIFIED |
| F5 | FTMO's commission is 0.06 USD a closed layer (0.03 + 0.03), as on 1514731800 and 1514878887 | `sr_table.py` 24-29 | RECORDED (to be checked on E's own ledger after its first closes) |
| F6 | Flipping E to built adds E to the books table and the scalps-per-roll table (`_fleet_books` and the S/R block take every entry without `placeholder`) | `app.py` 1590-1597, 1657-1661 | VERIFIED (Claude ran it) |
| F7 | Pinned lists that change with F6: `verify_c113_fleet_books.py` BK1 (`want_fleets`), `verify_c137_sr_table.py` ST8 (`sr.get("fleets")`); with E's regime start, ST3 (`want`); E's own TA4 / TA7 in `verify_twoarm_fleets.py` | the files in s3 | VERIFIED |
| F8 | QG6 (`verify_c114_quote_gap`), QT7 (`verify_c115_quotes`), SA5 (`verify_c123_side_add`), GT8 (`verify_c129_geometry`) and ST14 fail ONLY because they re-run `verify_c113_fleet_books.py` inside themselves; they need no edit | those scripts | VERIFIED (Claude ran it) |
| F9 | BK1's `want_rows` is UNCHANGED with E built (E's six pairs are already rows from C and D) | `verify_c113_fleet_books.py` 157-160 | VERIFIED (Claude ran it) |
| F10 | Seven checks need `VERIFY_DATABASE_URL` (a scratch database) and fail without it on `main` today: `verify_archive_carrypass`, `verify_archive_codes_depth`, `verify_c131_reroll_resolved` RR8 RR10, `verify_c137_snapshots` SN1 SN3 SN5 SN6, `verify_c137_sr_table` ST6 ST7 ST16, `verify_ejection_telemetry` ET1 ET2 ET3 ET24 ET29, and `verify_c102_ejection_index` EI5 (which re-runs two of them) | `main` `320afe6` | VERIFIED (Claude, no database) |

## 2. ONE WORKED EXAMPLE

Today the cross-fleet strip on every page shows E's card as "NOT BUILT" and its books table has columns
A, B, C, D. After this change E's card is a live card like D's (badge from its twelve heartbeats, e.g.
"LIVE 12/12"), the books table gains an E column (EURUSD row: A -, B 8/4, C 6/2, D 6/3, E E's own open
layers; the EURUSD numbers are the strip at 16:10Z), and the scalps-per-roll table gains E's rows, with closes on 1515045375 costed at 0.06 USD each
instead of "unknown".

## 3. COMMIT 1 -- TESTS FIRST (five edits; expected to FAIL against the base code)

T1. `scripts/verify_twoarm_fleets.py` 230-233, in `E_FLEET_ENTRY`:

    old:     "cycle_start": "2026-10-21",
             "start_balance": 10000.0,
             "placeholder": True,
             "built": False,
    new:     "cycle_start": "2026-10-23",
             "start_balance": 10000.0,
             "placeholder": False,
             "built": True,

   and line 348: `return "five fleets; E placeholder fields"` -> `return "five fleets; E built fields"`.

T2. `scripts/verify_twoarm_fleets.py` 387-394, in `check_ta7`:

    old: if not e.get("placeholder") or e.get("badge") != "NOT BUILT":
    new: if e.get("placeholder") or e.get("badge") == "NOT BUILT":

    old: if books.get("fleets") != ["A", "B", "C", "D"]:
    new: if books.get("fleets") != ["A", "B", "C", "D", "E"]:

    old: return "five cards; E NOT BUILT; books ABCD"
    new: return "five cards; E built; books ABCDE"

   (keep the two `raise AssertionError(...)` lines and the url check exactly as they are.)

T3. `scripts/verify_c113_fleet_books.py` 155:

    old:     want_fleets = ["A", "B", "C", "D"]
    new:     want_fleets = ["A", "B", "C", "D", "E"]

   (`want_rows` unchanged, F9.)

T4. `scripts/verify_c137_sr_table.py` 210-211, in `check_st3`:

    old:     want = {53066709: T("2026-10-07 02:25:00"), 53071896: T("2026-10-07 02:25:00"),
                     53077984: T("2026-10-07 02:25:00"), 1514878887: T("2026-10-07 22:08:00")}
    new:     want = {53066709: T("2026-10-07 02:25:00"), 53071896: T("2026-10-07 02:25:00"),
                     53077984: T("2026-10-07 02:25:00"), 1514878887: T("2026-10-07 22:08:00"),
                     1515045375: T("2026-10-23 03:04:00")}

T5. `scripts/verify_c137_sr_table.py` 433, in `check_st8`:

    old: ... or sr.get("fleets") != ["A", "B", "C", "D"]:
    new: ... or sr.get("fleets") != ["A", "B", "C", "D", "E"]:

**After commit 1, run every `scripts/verify_*.py` (s6). Expected, against the base code: exactly these
NEW failures, no others:** TA4, TA7 (`verify_twoarm_fleets` 9/11); BK1 (`verify_c113_fleet_books` 6/7);
QG6 (`verify_c114_quote_gap` 5/6); QT7 (`verify_c115_quotes` 7/8); SA5 (`verify_c123_side_add` 4/5); GT8
(`verify_c129_geometry` 7/8); ST3, ST8, ST14 (`verify_c137_sr_table` 12/18 with F10's ST6, ST7, ST16).
Every other script as at the base (F10).

## 4. COMMIT 2 -- THE CODE (three edits)

C1. `app.py` 268-280, E's `FLEET_STRIP` entry:

    old:         # New FTMO demo on a new Linux + wine server; flip placeholder and built,
                 # and set cycle_start and the account's commission (sr_table.py), when it attaches.
    new:         # FTMO free trial 1515045375 on wine-e; twelve charts attached 23 Oct
                 # 03:04-03:25Z (fxmatrix HANDOFF s88 continued 5), first fill 03:29:01Z.

    old:         "cycle_start": "2026-10-21",
    new:         "cycle_start": "2026-10-23",

    old:         "placeholder": True,
                 "built": False,
    new:         "placeholder": False,
                 "built": True,

   ONLY inside E's entry (lines 266-281). `app.py` 1324 also reads `"placeholder": True,`: that is
   `_fleet_strip_placeholder_card`, DO NOT TOUCH IT.

C2. `sr_table.py`, after line 29 (`1514878887: 0.06, ...`), add ONE line:

        1515045375: 0.06,   # FTMO trial, Fleet E (wine-e) from 23 Oct 03:04Z: FTMO's measured rate, to check on its ledger

C3. `sr_table.py`, after line 45 (`1514878887: datetime(2026, 10, 7, 22, 8, tzinfo=timezone.utc),`), add
   ONE line:

        1515045375: datetime(2026, 10, 23, 3, 4, tzinfo=timezone.utc),

**After commit 2, run every `scripts/verify_*.py`. Expected: every script exactly as at the base `320afe6`**
(the only failures F10's, `verify_twoarm_fleets` 11/11, `verify_c113_fleet_books` 7/7,
`verify_c137_sr_table` 15/18).

## 5. BRANCH AND COMMITS

- Branch `e-card-built` from the current `main`. First check that `main` holds the code base and only this
  prompt on top: `git diff --stat 320afe6 HEAD` must list ONLY `prompts/cursor_e_card_built.md` (the line
  numbers in s3 and s4 are those of `320afe6`, unchanged on `main`).
- Commit 1 message: `verify: E built (TA4, TA7, BK1, ST3, ST8) -- tests first`
- Commit 2 message: `Fleet E card built: cycle_start 2026-10-23; 1515045375 commission 0.06 and regime start`
- `git add` each file by name. Push the BRANCH only (`git push origin e-card-built`).

## 6. RUNNING THE CHECKS

From `D:\pipshed` in the venv, one script at a time (they are independent):

    Get-ChildItem scripts\verify_*.py | ForEach-Object { $o = python $_.FullName 2>&1 | Out-String; "{0} {1}" -f $_.BaseName, ($o -split "`n" | Select-String -Pattern '\d+/\d+' | Select-Object -Last 1) }

Report the 46 lines at the base, after commit 1 and after commit 2 (three lists). If your machine has
`VERIFY_DATABASE_URL` set, say so: F10's checks may then pass, which is fine; report them.

## 7. NEGATIVE SPACE (do NOT)

- Do not push to `main`, merge, open a PR, or deploy: a push to `main` deploys every page service at once.
- Do not touch `templates/`, `archive_worker.py`, `ftmo_daily.py`, `ejection_view.py`, migrations, or any
  file not named in s3 and s4.
- Do not change `want_rows` in BK1, `_fleet_strip_placeholder_card` (`app.py` 1317-1330), E's `name`,
  `broker`, `url`, `instances`, `daily_loss_limit_usd` or `start_balance`, or any other fleet's entry.
- Do not add A's retirement, E's commission for any other account, or any other cleanup.
- Do not edit the expected values of any check not named in s3 to make it pass.
- No `git add .` or `-u`; no `git stash`; no checkout of files from other commits; no force push.
- Do not run any script against Railway, Redis or a real database; no `railway` command.

## 8. FAILURE MODES (STOP and report; do not improvise)

- After commit 1, a failure other than s3's list, or one of s3's list NOT failing: STOP, report the line.
- After commit 2, any script not as at the base: STOP, report the script and its failing check.
- An `old` text in s3 or s4 not found exactly once at its line: STOP, quote what is there.
- `git diff --stat 320afe6 HEAD` lists any file but `prompts/cursor_e_card_built.md` at the start: STOP.

## 9. WHAT CLAUDE CHECKS AFTER

Claude fetches `e-card-built`, reads both commits against s3 and s4 (and a reference diff built
independently on `320afe6`), and reruns the checks. Then the operator merges to `main` by fast-forward and
pushes, outside 20:50-21:00Z; Claude reads E's card LIVE on the strip.

Line count: 170
