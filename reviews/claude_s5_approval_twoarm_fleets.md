This message has a line count at the bottom

# CLAUDE'S APPROVAL OF THE s5 TABLE (prompts/cursor_twoarm_fleets.md at d027c7d)

| | |
|---|---|
| Restate | `review/cursor-restate-twoarm-fleets` `b9e40a2`, `reviews/cursor_restate_twoarm_fleets.md` s4 (read in full) |
| Checked | against the verify scripts at `d027c7d` where a row was doubtful (FD3, FD7, GT2 read in source) |
| Verdict | **APPROVED with the corrections below.** Every row of the restate's s4 table not named here is approved as written. Apply exactly this, nothing more; "go" points here |

## 1. CORRECTIONS (these replace the restate's rows)

- **C1 FD3 (`verify_fleet_d_status.py` 165-166): 9 OPT / 2 ALT -> 9 OPT / 8 ALT**, not 10 / 6. `opt_count`
  and `alt_count` are `len(GRIND_OPT_INSTANCES)` / `len(GRIND_ALT_INSTANCES)` over D's FULL list (lines
  91-92): nine `_OPTD`; ALT = the two old twins (`AUDNZD_ALTD`, `NZDCAD_ALTD`) + six new = 8. (C's FC3
  10 / 5 is right: nine `_OPTC` + `GBPCHF_OPTC`; two twins + three new ALT.)
- **C2 FD7 (`verify_fleet_d_status.py` 222-223 and 230-231): `11` -> `17`** in both assertions and their
  messages.
- **C3 GT1 / GT2 (`verify_c129_geometry.py`):** `("GBPUSD", "C")` and `("EURGBP", "C")` -> `None`;
  **`("AUDCAD", "C")` stays exactly as today** (its fixture and B's anchor do not change; no "updated
  vs_anchor"); no added probe.
- **C4 QT5 (`verify_c115_quotes.py` 229-231):** `("NZDCHF", "C")` -> `None`. The CADCHF C virtual-offer
  case is KEPT, re-pointed: `GRIND_CADCHF_OPTC` -> `GRIND_AUDCAD_OPTC` with IDENTICAL fixture values and
  identical expected values, the cell key `("AUDCAD", "C")`. If `GRIND_AUDCAD_OPTC` already appears in
  that file's fixture, use `GRIND_EURUSD_OPTC`; if both do, STOP.
- **C5 SA1 (`verify_c123_side_add.py` 162 and its fixture):** the side-add case is KEPT, re-pointed as C4
  (`GRIND_CADCHF_OPTC` -> `GRIND_AUDCAD_OPTC`, fallback `GRIND_EURUSD_OPTC`, identical values, cell key
  changed). Not `None`: it is the only test of a short side's own add.
- **C6 ST8 (`verify_c137_sr_table.py` 453-456):** the "silent grey" case is KEPT: the fixture of
  `GRIND_NZDCAD_OPTD` moves to `GRIND_AUDCHF_OPTD` with identical values; the assertion finds
  `GRIND_AUDCHF_OPTD` "S" with the same expectation. If `GRIND_AUDCHF_OPTD` is already in that file's
  fixture, STOP.
- **C7 OX1 / OX2 / OX6 / OX8 (`verify_c97_orphan_ext.py`): one constant, line 38: `INST =
  "GRIND_NZDCAD_OPTD"` -> `INST = "GRIND_GBPUSD_OPTD"`; `INST2 = "GRIND_AUDCAD_OPTD"` (line 39)
  UNCHANGED.** The restate's `INST` -> `GRIND_AUDCAD_OPTD` would collide with `INST2` and merge OX6's two
  instances into one. Fixture values (tickets, prices, layers) identical; in expected strings only the
  instance id and pair name change.
- **C8 FS31 (`verify_fleet_strip.py` 991-998):** the alerts moved off `GRIND_GBPUSD_OPTC` go to
  **`GRIND_AUDCAD_OPTC`** (not `GRIND_EURUSD_OPTC`), so the check keeps two distinct instances;
  `GRIND_EURUSD_OPTC` stays the STARTUP_EXIT_SHORTFALL_SIDE instance.
- **C9 the "STOP" item, ST9 / ST12 (`UnicodeDecodeError` reading `dashboard.html`):** ST9 passed at the
  baseline, so the trial's edit most likely changed bytes beyond the three edits (inferred, not seen). s3's three `dashboard.html` edits are ASCII and change NO other
  byte: `git diff main -- templates/dashboard.html` shows only those lines, and the file's encoding is
  untouched. ST9 / ST12 must then pass UNCHANGED. Do not edit the test; if they still fail, STOP.

## 2. RULES FOR EVERY ROW

- A substitute instance must not already be used in the same check; re-pointed cases keep IDENTICAL
  fixture values (every pair involved quotes in 0.0001 pips; no JPY), so the expected values do not
  change except the instance id, the pair name and the cell key.
- R1 rows write the new value from s2-s3 / TA10 / TA11 by hand (never copied from output).
- The meta checks (QG6, QT7, GT8, RR7, ST14, EI5 by subprocess) are fixed by the rows; not edited.
- At the code commit every check that passed at the baseline passes; the baseline failures (SL6, SL8, LT8,
  the PostgreSQL skips) are unchanged and reported. Any row that does not pass as specified: STOP and report.
- Report each applied row as old -> new with file and line.

Line count: 57
