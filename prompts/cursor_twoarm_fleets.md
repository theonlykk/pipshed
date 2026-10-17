This message has a line count at the bottom

# CURSOR PROMPT (pipshed): TWO-ARM FLEETS -- NEW IDS ON C AND D, RETIREMENTS, FLEET E (TESTS FIRST)

| | |
|---|---|
| Written | 17 Oct 2026 (fxmatrix HANDOFF s85 continued 9), Claude (Lead Engineer) |
| Why | fxmatrix rules next week's layout (`docs/research/fleet-d-two-arm-ring-2026-10-16.md` s10-s11; presets merged in fxmatrix `2426f94`, `ea/presets_{c,d,e}/*_t1.set`): D and C gain ALT arms and retire pairs; a new FTMO demo runs as fleet E with its own page service `linuxe.pipshed.com` (operator, 17 Oct) |
| Base | Branch `twoarm-fleets` from pipshed `main` at the commit that adds THIS file. Files: `app.py`, `scripts/verify_twoarm_fleets.py` (new), and only the existing verify scripts named in s5 |
| Deploy | AFTER D's and C's charts change (Wed 21 Oct or later), never before: the retirements hide instances from the strip (C119's rule). The operator creates the Railway service "pipshed Fleet E" (`GRIND_FLEET=E`, domain `linuxe.pipshed.com`, start command as "pipshed Copy") after this is deployed |
| Review | Gemini (Argon, in Cursor) reviews this file before Cursor sees it; questions in s7 |

## 0. RESTATE AND STOP (do this first; write nothing else)

1. Restate each item of s2-s5 in one line, quoting this prompt.
2. For every check of s4: its id and what it asserts, with the expected lists written out.
3. Run every `scripts/verify_*.py` on `main` (the base) and report which pass and which cannot run here
   (e.g. need PostgreSQL); this is the BASELINE. Say which checks fail at your tests commit and why.
4. STOP. Wait for the operator's "go".

## 1. AUDIT TRAIL (verified by Claude in source at pipshed `6ea487e`)

| # | Fact | Where | Status |
|---|---|---|---|
| P1 | Instance lists per fleet, `GRIND_RETIRED_INSTANCES` (C108 / C119), strips derived as "list minus retired" for B, C, D; A's strip hand-written | `app.py` 76-174 | READ |
| P2 | `FLEET_STRIP` entries A-D (letter, name, broker, url, instances, lattice, daily_loss_limit_usd, cycle_start, start_balance, placeholder, built) | `app.py` 176-230 | READ |
| P3 | `GRIND_FLEET` from the env picks `GRIND_FLEET_INSTANCES[letter]`; an unknown letter falls back to A with a warning | `app.py` 232-248 | READ |
| P4 | `_grind_slot` strips the fleet letter only for `OPTB ALTB OPTC ALTC OPTD ALTD`; `GRIND_OPT_INSTANCES` / `GRIND_ALT_INSTANCES` are built from it | `app.py` 254-264 | READ |
| P5 | A placeholder card reads only letter, name, broker, url, daily_loss_limit_usd and `built` ("NOT BUILT" / "NOT ATTACHED"); `_fleet_books` and the S/R table skip placeholders | `app.py` 1264-1300, 1540 | READ |
| P6 | `GRIND_RINGS` groups instances by symbol; GBPCHF is in no ring (it would appear in no ring panel) | `app.py` 2059-2085, 2161-2164 | READ |
| P7 | Every EA pushes to pipshed.com (`TelemetryURL` in every preset); the ingest stores `fxmatrix:state:<instance_id>` for any id; page services read Redis | `app.py` 4001-4060; `RAILWAY.md` | READ |
| P8 | Existing checks pin today's fleets and lists: `verify_fleet_strip.py` 306 (letters ABCD), `verify_c119_twins_retired.py` 118 (eleven ids a fleet), `verify_c113_fleet_books.py` 155-158 (rows), `verify_fleet_c_status.py`, `verify_fleet_d_status.py` (the lists), `verify_c137_sr_table.py` 433 (fleets ABCD) | those lines | READ |

## 2. THE LISTS (write them exactly)

- **`GRIND_C_INSTANCES`:** the eleven of today, then append `GRIND_EURUSD_ALTC`, `GRIND_AUDCAD_ALTC`,
  `GRIND_GBPCHF_OPTC`, `GRIND_GBPCHF_ALTC` (15).
- **`GRIND_D_INSTANCES`:** the eleven of today, then append `GRIND_GBPUSD_ALTD`, `GRIND_EURUSD_ALTD`,
  `GRIND_EURGBP_ALTD`, `GRIND_AUDCAD_ALTD`, `GRIND_AUDCHF_ALTD`, `GRIND_CADCHF_ALTD` (17).
- **`GRIND_E_INSTANCES` (new):** `GRIND_GBPUSD_OPTE`, `GRIND_GBPUSD_ALTE`, `GRIND_EURUSD_OPTE`,
  `GRIND_EURUSD_ALTE`, `GRIND_EURGBP_OPTE`, `GRIND_EURGBP_ALTE`, `GRIND_AUDCAD_OPTE`, `GRIND_AUDCAD_ALTE`,
  `GRIND_AUDCHF_OPTE`, `GRIND_AUDCHF_ALTE`, `GRIND_CADCHF_OPTE`, `GRIND_CADCHF_ALTE` (12).
- **`GRIND_RETIRED_INSTANCES`:** today's ten plus D's `GRIND_NZDCHF_OPTD`, `GRIND_NZDCAD_OPTD`,
  `GRIND_AUDNZD_OPTD` and C's `GRIND_GBPUSD_OPTC`, `GRIND_EURGBP_OPTC`, `GRIND_AUDCHF_OPTC`,
  `GRIND_CADCHF_OPTC`, `GRIND_NZDCHF_OPTC`, `GRIND_NZDCAD_OPTC`, `GRIND_AUDNZD_OPTC` (20). A comment as
  C119's: the two-arm build (fxmatrix fleet D note s10), deployed after the charts change.
- **Strips (derived as today, "list minus retired"):** B unchanged (9); C = `EURUSD_OPTC`,
  `AUDCAD_OPTC`, `EURUSD_ALTC`, `AUDCAD_ALTC`, `GBPCHF_OPTC`, `GBPCHF_ALTC` (6); D = `GBPUSD_OPTD`,
  `EURUSD_OPTD`, `EURGBP_OPTD`, `AUDCAD_OPTD`, `AUDCHF_OPTD`, `CADCHF_OPTD` and the six `_ALTD` (12);
  `GRIND_E_STRIP_INSTANCES` = the E list minus retired (12). Each fleet's OWN page keeps its full list
  (a retired tile says CONNECTION LOST), as C119.
- **A is unchanged** (its trial ends ~21 Oct; its retirement is a later change).

## 3. THE CODE

- **`FLEET_STRIP`:** append after D: `{"letter": "E", "name": "Fleet E (FTMO two-arm)", "broker": "FTMO",
  "url": "https://linuxe.pipshed.com", "instances": GRIND_E_STRIP_INSTANCES, "lattice": True,
  "daily_loss_limit_usd": 500.0, "cycle_start": "2026-10-21", "start_balance": 10000.0, "placeholder":
  True, "built": False}` with a comment: a new FTMO demo on a new Linux + wine server; flip `placeholder`
  and `built`, and set `cycle_start` and the account's commission (`sr_table.py`), when it attaches.
- **`GRIND_FLEET_INSTANCES`:** add `"E": GRIND_E_INSTANCES`.
- **`_grind_slot`:** also strip the letter for `OPTE` and `ALTE`.
- **`GRIND_RINGS`:** add `"gbpchf": {"label": "GBPCHF", "symbols": ["GBPCHF"]}` (C's each-currency-once
  set; with a comment). Nothing else in `GRIND_RINGS` changes.
- Nothing else in `app.py` changes. No change to `archive_worker.py`, `sr_table.py`, `ftmo_daily.py`,
  `ejection_view.py`, templates or migrations.

## 4. TESTS (`scripts/verify_twoarm_fleets.py`, its own commit first; hand-written expectations)

In the style of `verify_c119_twins_retired.py` (checks TA1-TA9, a PASS / FAIL line each, a count, exit 1
on any failure). Expected values are the lists of s2, written out in the script, never read from `app.py`.

- **TA1** `GRIND_C_INSTANCES`, `GRIND_D_INSTANCES`, `GRIND_E_INSTANCES` equal s2's lists, in order.
- **TA2** `GRIND_RETIRED_INSTANCES` equals s2's twenty.
- **TA3** the B, C, D, E strip lists equal s2's (B's nine unchanged; C 6; D 12; E 12, in list order).
- **TA4** `FLEET_STRIP` letters are A, B, C, D, E; E's entry has exactly s3's fields and values.
- **TA5** `_grind_slot` gives `OPT` for `GRIND_EURUSD_OPTE`, `ALT` for `GRIND_EURUSD_ALTE`,
  `GRIND_GBPCHF_ALTC`, `GRIND_EURUSD_ALTD`; and `OPT` for `GRIND_EURUSD_OPT` (A, unchanged).
- **TA6** with `GRIND_FLEET=E` (a subprocess probe, as `verify_fleet_d_status.py`'s `run_probe` does for D):
  `GRIND_INSTANCES` is E's twelve; `GRIND_OPT_INSTANCES` the six `_OPTE`, `GRIND_ALT_INSTANCES` the six
  `_ALTE`; `GRIND_DEFAULT_INSTANCE` `GRIND_GBPUSD_OPTE`.
- **TA7** `/api/g/<token>/fleets` (test client, empty Redis as `verify_fleet_strip.py`): five cards; E's
  card `placeholder` true, badge `NOT BUILT`, url `https://linuxe.pipshed.com`; the strip response's
  `books` `fleets` stays A, B, C, D (placeholders skipped).
- **TA8** with `GRIND_FLEET=C` (a subprocess probe): `_grind_instances_for_ring("gbpchf")` is `GRIND_GBPCHF_OPTC`,
  `GRIND_GBPCHF_ALTC`; every C instance is in exactly one ring.
- **TA9** guard: `GRIND_A_INSTANCES`, `GRIND_A_STRIP_INSTANCES`, `GRIND_B_INSTANCES` and A-D's strip
  entries other than `instances` are unchanged from `main` (hand-written).

At the tests commit TA1-TA8 fail (no E, no new ids); TA9 passes (a guard). Report it.

## 5. EXISTING CHECKS THAT PIN TODAY'S LISTS (update ONLY these, ONLY to s2-s3)

These requirements change, so their expectations change; each update is written by hand from s2-s3:

- `verify_fleet_strip.py` 306-307: letters A-E; its C and D lists (lines ~30-60) to s2's full lists.
- `verify_c119_twins_retired.py` 118: fleet list lengths 11 (B), 15 (C), 17 (D); the twins still in
  each; the retired set is a superset of C119's ten.
- `verify_c113_fleet_books.py` 155-158: `want_rows` gains `GBPCHF` at the END (rows follow first appearance
  across the non-placeholder strips A, B, C, D: A's seven, B adds AUDCAD and NZDCHF, C adds GBPCHF);
  `want_fleets` unchanged (E is a placeholder).
- `verify_fleet_c_status.py`, `verify_fleet_d_status.py`: their copies of the C and D lists to s2's.
- Any OTHER existing check that fails after the code commit and passed at the baseline: STOP and report
  it with the line; do not edit it.

Report every updated expectation as old -> new, file and line.

## 6. NEGATIVE SPACE (do NOT)

- No deploy, no Railway command, no change to `RAILWAY.md`, no env var, no DNS. No change to the fxmatrix
  repo. No `git stash`, no merge, no PR, no `git add .` / `-u`, no push to `main`.
- Do not retire A, flip E to built, or touch `sr_table.py`'s commission table (later, when E attaches).
- Do not change any other expectation in any test to make it pass.

## 7. FOR THE REVIEWER (Gemini / Argon): attack the premises, say which fact is missing

- **Q1.** Deploying the retirements after the charts change (C119's rule): a retired-but-still-running
  instance for a few hours would be hidden from the strip. Is "after, never before" enough, or should the
  retirements be a separate deploy from the new ids and fleet E?
- **Q2.** Each fleet's own page keeps its full list (C: 15 tiles, 9 retired; D: 17, 5 retired): readable,
  or should own pages drop retired ids (a change of C119's convention, with what risk)?
- **Q3.** A ring of one (`gbpchf`) for C's GBPCHF: any ring view that assumes a ring has two or more pairs,
  or that counts each currency's instances across rings?
- **Q4.** E's card as a placeholder until attach: does any path read a placeholder's `instances`,
  `cycle_start` or `start_balance`?
- **Q5.** What fact is missing (e.g. a per-fleet table keyed by letter elsewhere: commission, logins,
  geometry anchors)?

Save your reply as `reviews/argon_twoarm_fleets.md` on a branch `review/argon-twoarm-fleets` from this
commit, commit and push it; Claude reads it there.

## 8. COMMITS AND REPORT

1. `scripts/verify_twoarm_fleets.py` (tests). 2. `app.py` and the s5 updates. Nothing else. Push
`twoarm-fleets`. Report both hashes; the baseline, tests-commit and final results of every
`scripts/verify_*.py` (pass / fail / cannot run here); s5's updates as old -> new; `git diff --stat
main..twoarm-fleets`. STOP on any failure you cannot explain from this prompt.

Line count: 139
