# Section 0 — RESTATE AND STOP (`prompts/cursor_twoarm_fleets.md` at `d027c7d`)

Reviewed commit: `d027c7deee117726a63f1f2531e5c9b94d90cf4d` (`main` at fetch). Trial: applied **s2–s3 only** (no commit), ran all `scripts/verify_*.py`, then `git restore .` (no new files kept).

---

## 1. Restate s2–s4 (one line each, quoting the prompt)

**s2 — THE LISTS**
- **`GRIND_C_INSTANCES`:** “the eleven of today, then append `GRIND_EURUSD_ALTC`, `GRIND_AUDCAD_ALTC`, `GRIND_GBPCHF_OPTC`, `GRIND_GBPCHF_ALTC` (15).”
- **`GRIND_D_INSTANCES`:** “the eleven of today, then append `GRIND_GBPUSD_ALTD`, `GRIND_EURUSD_ALTD`, `GRIND_EURGBP_ALTD`, `GRIND_AUDCAD_ALTD`, `GRIND_AUDCHF_ALTD`, `GRIND_CADCHF_ALTD` (17).”
- **`GRIND_E_INSTANCES` (new):** “`GRIND_GBPUSD_OPTE`, `GRIND_GBPUSD_ALTE`, … `GRIND_CADCHF_OPTE`, `GRIND_CADCHF_ALTE` (12).”
- **`GRIND_RETIRED_INSTANCES`:** “today's ten plus D's `GRIND_NZDCHF_OPTD`, `GRIND_NZDCAD_OPTD`, `GRIND_AUDNZD_OPTD` and C's `GRIND_GBPUSD_OPTC`, `GRIND_EURGBP_OPTC`, `GRIND_AUDCHF_OPTC`, `GRIND_CADCHF_OPTC`, `GRIND_NZDCHF_OPTC`, `GRIND_NZDCAD_OPTC`, `GRIND_AUDNZD_OPTC` (20).”
- **Strips:** “B unchanged (9); C = `EURUSD_OPTC`, `AUDCAD_OPTC`, `EURUSD_ALTC`, `AUDCAD_ALTC`, `GBPCHF_OPTC`, `GBPCHF_ALTC` (6); D = six `_OPTD` + six `_ALTD` (12); `GRIND_E_STRIP_INSTANCES` = E list minus retired (12); each fleet's OWN page keeps its full list.”
- **A:** “unchanged (its trial ends ~21 Oct; its retirement is a later change).”

**s3 — THE CODE**
- **`FLEET_STRIP`:** append Fleet E placeholder entry (`linuxe.pipshed.com`, `GRIND_E_STRIP_INSTANCES`, `placeholder: True`, `built: False`, …).
- **`GRIND_FLEET_INSTANCES`:** add `"E": GRIND_E_INSTANCES`.
- **`_grind_slot`:** also strip for `OPTE` and `ALTE`.
- **`GRIND_DEFAULT_INSTANCE`:** first `GRIND_INSTANCES` id **not** in `GRIND_RETIRED_INSTANCES` (fallback first id).
- **Cross-fleet tables:** no code change; ALT strip instances → `<PAIR>*` rows (TA10).
- **`templates/dashboard.html`:** three edits — `fleetStripPair` `/_(OPT|ALT)[BCDE]?$/`, `fleetStripAlertLabel` slot from same match, `.fleet-strip` `repeat(5, 1fr)` at ≥1600px.
- **`GRIND_RINGS`:** add `"gbpchf": {"label": "GBPCHF", "symbols": ["GBPCHF"]}`.
- **Else:** no other changes to `app.py`, `templates/dashboard.html`, workers, or migrations.

**s4 — TESTS (`scripts/verify_twoarm_fleets.py`, tests commit first)**
- Hand-written expectations for TA1–TA11 (TA9 guard unchanged A/B); at tests-only commit TA1–TA8, TA10, TA11 fail; TA9 passes.

---

## 2. s4 checks — id and assertion (expected lists written out)

| Id | Asserts |
|----|---------|
| **TA1** | `GRIND_C_INSTANCES` = today's 11 + `[GRIND_EURUSD_ALTC, GRIND_AUDCAD_ALTC, GRIND_GBPCHF_OPTC, GRIND_GBPCHF_ALTC]` (15, order as s2); `GRIND_D_INSTANCES` = today's 11 + six `_ALTD` append (17); `GRIND_E_INSTANCES` = twelve `_OPTE`/`_ALTE` pairs in s2 order. |
| **TA2** | `GRIND_RETIRED_INSTANCES` = today's 10 + `{GRIND_NZDCHF_OPTD, GRIND_NZDCAD_OPTD, GRIND_AUDNZD_OPTD, GRIND_GBPUSD_OPTC, GRIND_EURGBP_OPTC, GRIND_AUDCHF_OPTC, GRIND_CADCHF_OPTC, GRIND_NZDCHF_OPTC, GRIND_NZDCAD_OPTC, GRIND_AUDNZD_OPTC}` (20). |
| **TA3** | `GRIND_B_STRIP_INSTANCES` unchanged (9 `_OPTB`); C strip = `[GRIND_EURUSD_OPTC, GRIND_AUDCAD_OPTC, GRIND_EURUSD_ALTC, GRIND_AUDCAD_ALTC, GRIND_GBPCHF_OPTC, GRIND_GBPCHF_ALTC]`; D strip = `[GRIND_GBPUSD_OPTD, GRIND_EURUSD_OPTD, GRIND_EURGBP_OPTD, GRIND_AUDCAD_OPTD, GRIND_AUDCHF_OPTD, GRIND_CADCHF_OPTD, GRIND_GBPUSD_ALTD, GRIND_EURUSD_ALTD, GRIND_EURGBP_ALTD, GRIND_AUDCAD_ALTD, GRIND_AUDCHF_ALTD, GRIND_CADCHF_ALTD]`; E strip = all 12 E ids. |
| **TA4** | `FLEET_STRIP` letters `A,B,C,D,E`; E entry fields match s3 (name, broker, url, instances, lattice, limits, cycle_start, start_balance, placeholder True, built False). |
| **TA5** | `_grind_slot("GRIND_EURUSD_OPTE")`→`OPT`, `_grind_slot("GRIND_EURUSD_ALTE")`→`ALT`, `_grind_slot("GRIND_GBPCHF_ALTC")`→`ALT`, `_grind_slot("GRIND_EURUSD_ALTD")`→`ALT`, `_grind_slot("GRIND_EURUSD_OPT")`→`OPT`. |
| **TA6** | `GRIND_FLEET=E`: `GRIND_INSTANCES` = E's 12; six `_OPTE` in `GRIND_OPT_INSTANCES`, six `_ALTE` in `GRIND_ALT_INSTANCES`; `GRIND_DEFAULT_INSTANCE` = `GRIND_GBPUSD_OPTE`. |
| **TA7** | `/api/g/<token>/fleets`: five cards; E `placeholder` true, badge `NOT BUILT`, url `https://linuxe.pipshed.com`; `books.fleets` = `[A,B,C,D]` (E skipped). |
| **TA8** | `GRIND_FLEET=C`: `_grind_instances_for_ring("gbpchf")` = `[GRIND_GBPCHF_OPTC, GRIND_GBPCHF_ALTC]`; every C instance in exactly one ring. |
| **TA10** | `books.rows` pair order (17): `GBPUSD, EURUSD, EURGBP, AUDCHF, CADCHF, NZDCAD, AUDNZD, AUDCAD, NZDCHF, EURUSD*, AUDCAD*, GBPCHF, GBPCHF*, GBPUSD*, EURGBP*, AUDCHF*, CADCHF*`. |
| **TA11** | `GRIND_FLEET=C` → default `GRIND_EURUSD_OPTC`; `D` → `GRIND_GBPUSD_OPTD`; `E` → `GRIND_GBPUSD_OPTE`. |
| **TA9** | Guard: `GRIND_A_INSTANCES`, `GRIND_A_STRIP_INSTANCES`, `GRIND_B_INSTANCES`, and A–D strip metadata (except `instances`) unchanged from `main`. |

---

## 3. BASELINE — every `scripts/verify_*.py` on `d027c7d` (before s2–s3)

Environment: Windows, **no** `VERIFY_DATABASE_URL`, **node** present for some UI checks.

| Script | Result |
|--------|--------|
| verify_archive_action.py | **PASS** (0) |
| verify_archive_carrypass.py | **CANNOT RUN** — SKIP: VERIFY_DATABASE_URL |
| verify_archive_codes_depth.py | **CANNOT RUN** — SKIP: VERIFY_DATABASE_URL |
| verify_archive_export_study.py | **PASS** (SKIP PG inside) |
| verify_archive_scalp_tap.py | **PASS** |
| verify_archive_worker.py | **PASS** |
| verify_c102_ejection_index.py | **FAIL** — EI5 (subprocess: verify_ejection_telemetry.py, verify_c137_sr_table.py) |
| verify_c108_retired_critical.py | **PASS** |
| verify_c109_default_instance.py | **PASS** 4/4 |
| verify_c110_scalp_reads.py | **PASS** 6/6 |
| verify_c113_fleet_books.py | **PASS** 7/7 |
| verify_c114_quote_gap.py | **PASS** 6/6 |
| verify_c115_quotes.py | **PASS** 8/8 |
| verify_c119_twins_retired.py | **PASS** 6/6 |
| verify_c123_side_add.py | **PASS** 5/5 |
| verify_c129_geometry.py | **PASS** 8/8 |
| verify_c131_reroll_resolved.py | **FAIL** — RR8, RR10 need VERIFY_DATABASE_URL (8/10) |
| verify_c137_snapshots.py | **FAIL** — SN1, SN3, SN5, SN6 need PG (4/8) |
| verify_c137_sr_table.py | **FAIL** — ST6, ST7, ST16 need PG; 13/18 pass |
| verify_c80_c74_c81.py | **PASS** |
| verify_c90_d_commission.py | **PASS** |
| verify_c94_stranded_resolved.py | **PASS** |
| verify_c97_orphan_ext.py | **PASS** |
| verify_carry_table.py | **PASS** |
| verify_critical_resolved.py | **PASS** |
| verify_daily_snapshots.py | **PASS** |
| verify_dashboard_contrast.py | **PASS** |
| verify_dashboard_rings.py | **PASS** |
| verify_db_migrate.py | **PASS** |
| verify_ejection_telemetry.py | **FAIL** — ET1, ET2, ET3, ET24, ET29 need VERIFY_DATABASE_URL (28/33) |
| verify_fleet_b_status.py | **PASS** |
| verify_fleet_c_status.py | **PASS** |
| verify_fleet_d_status.py | **PASS** |
| verify_fleet_select.py | **PASS** |
| verify_fleet_strip.py | **PASS** 44/44 |
| verify_fleet_strip_slots.py | **FAIL** — SL6, SL8 (middle-dot `·` vs mojibake in rendered JS line; **baseline**, not s2–s3) |
| verify_fxgrind_panel.py | **PASS** |
| verify_grind_arm_cards.py | **PASS** |
| verify_grind_display_gaps.py | **PASS** |
| verify_grind_exposure.py | **PASS** |
| verify_grind_pnl_render.py | **PASS** |
| verify_layer_table_market.py | **FAIL** — LT8 (same `·` encoding; **baseline**) |
| verify_nzd_ext_registration.py | **PASS** |
| verify_summary_carry.py | **PASS** |
| verify_telemetry_key_next.py | **PASS** |

---

## 4. s5 table — existing checks newly failing after s2–s3 trial

Only checks that **passed at baseline** (or passed except PG) and **failed after trial**. PG-only checks unchanged (still SKIP). Baseline failures (SL6/SL8, LT8, EI5 partial, etc.) not duplicated unless they **worsened**.

| File | Check | Line(s) | R | Old → new (exact) |
|------|-------|---------|---|-------------------|
| verify_fleet_strip.py | FS2 | 306–307 | R1 | `letters == ["A","B","C","D"]` → `["A","B","C","D","E"]` |
| verify_fleet_strip.py | FS3 | 330–331, 339–340 | R1 | D strip health `instances_total/live` **9/9** → **12/12** when all D strip ids have heartbeats; first leg still **9/0** with no hb → **12/0** |
| verify_fleet_strip.py | FS9 | 459–469 | R2 | Stale heartbeat on **`GRIND_NZDCAD_OPTC`** (strip) → **`GRIND_EURUSD_OPTC`** (live on C strip); expect status **green**, oldest age **89–92 s** |
| verify_fleet_strip.py | FS10 | 480–490 | R2 | Same: stale **`GRIND_NZDCAD_OPTC`** → **`GRIND_EURUSD_OPTC`**; expect **amber** |
| verify_fleet_strip.py | FS20 | 701–708 | R1/R2 | Update local `GRIND_C_INSTANCES` (29–41) to s2 list; seed heartbeats for all **6** C strip ids so C badge stays **LIVE** |
| verify_fleet_strip.py | FS31 | 991–998 | R2 | Alerts on **`GRIND_GBPUSD_OPTC`** (retired, off strip) → use **`GRIND_EURUSD_OPTC`** for QUARANTINE_ENTER + resolved halt rows; keep **`GRIND_EURUSD_OPTC`** for STARTUP_EXIT_SHORTFALL_SIDE red |
| verify_fleet_strip.py | FS32 | 1012–1016 | R2 | Halt/invariant fixtures on **`GRIND_GBPUSD_OPTC`** → **`GRIND_EURUSD_OPTC`**; expect red HALTED, INVARIANT_FAIL, QUARANTINE_HALT |
| verify_fleet_strip.py | FS35 | 1048–1059 | R2 | Same: **`GRIND_GBPUSD_OPTC`** → **`GRIND_EURUSD_OPTC`** for invariant_ok false / missing invariant_ok |
| verify_fleet_strip.py | (local lists) | 29–41, 69–80 | R1 | Pin `GRIND_C_INSTANCES` / `GRIND_D_INSTANCES` to s2 **15** / **17** lists |
| verify_c108_retired_critical.py | RC6 | 98–99 | R1 | `RETIRED` frozenset (10 ids) → s2 **20** ids (written out in TA2) |
| verify_c109_default_instance.py | DD2 | 82–85 | R1 | Fleet C: `opens_on == default == first` → `opens_on == default == "GRIND_EURUSD_OPTC"` (TA11); `first` may stay `GRIND_GBPUSD_OPTC` on full list |
| verify_c110_scalp_reads.py | SR2 | 350–352 | R1 | `missing = [k for v in s3 if v is None and k != "D"]` → also exclude **`E`** (placeholder summary None): `and k not in ("D","E")` |
| verify_c113_fleet_books.py | BK1 | 155–158, 163 | R1 | `want_rows` nine pairs → TA10 **17 rows** (quoted in §2 TA10) |
| verify_c113_fleet_books.py | BK2 | 188 | R3 | `("NZDCHF","D")` live cell → **`None`** (NZDCHF_OPTD retired off D strip) |
| verify_c113_fleet_books.py | BK3 | 199–200 | R3 | `("NZDCHF","C") == {"live": False}` → **`None`** (NZDCHF_OPTC off C strip) |
| verify_c113_fleet_books.py | BK4 | 215 | R1 | C totals `want_c = {long:16, short:16, net:0, mtm:-4.0, live:8}` → `{long:12, short:12, net:0, mtm:-3.0, live:6}` (six live strip instances in fixture) |
| verify_c114_quote_gap.py | QG2 | 145 | R3 | `("NZDCHF","C"): {"live": False}` → **`None`** |
| verify_c115_quotes.py | QT3 | 209 | R3 | `("NZDCHF","D")` rolled cell → **`None`** |
| verify_c115_quotes.py | QT5 | 229–231 | R3 | `("CADCHF","C")` and `("NZDCHF","C")` → **`None`**; re-point CADCHF virtual-offer case to a live C strip id if a replacement case is needed |
| verify_c123_side_add.py | SA1 | 162 | R3/R2 | `("CADCHF","C")` → **`None`**; or fixture **`GRIND_CADCHF_OPTC`** → live pair on C strip with hand-recomputed add (e.g. keep **`GRIND_EURUSD_OPTC`** if side-add case moved) |
| verify_c119_twins_retired.py | TR1 | 63–64 | R1 | `got == CYCLE3 \| TWINS` (10) → equals s2 **20** retired set |
| verify_c119_twins_retired.py | TR2 | 71–75 | R1 | B/C/D strip = nine `_OPT` only → B unchanged **9 OPTB**; C **6** ids (s2 strip); D **12** ids (s2 strip) |
| verify_c119_twins_retired.py | TR3 | 85–86 | R1 | B/C/D badge **LIVE 9/9** → B **9/9**; C **6/6**; D **12/12** |
| verify_c119_twins_retired.py | TR5 | 103–108 | R1 | “nine pairs, no twin rows” → TA10 **17 rows** including starred ALT rows |
| verify_c119_twins_retired.py | TR6 | 116–119 | R1 | B/C/D page list len **11** → B **11**; C **15**; D **17** (twins + new ids per s2) |
| verify_c129_geometry.py | GT1 | 151–156 | R3 | `("GBPUSD","C")` live geometry → **`None`** (GBPUSD_OPTC retired); optional anchor probe on **`EURUSD`** C |
| verify_c129_geometry.py | GT2 | 159–166 | R3 | `("EURGBP","C")` → **`None`**; `("AUDCAD","C")` stays live with updated vs_anchor |
| verify_c129_geometry.py | GT4 | 178–183 | R3 | `("NZDCAD","D")` → **`None`**; `("GBPUSD","D")` unchanged |
| verify_c129_geometry.py | GT5 | 186–193 | R3 | `("NZDCHF","C")` and `("NZDCHF","D")` **`{"live": False}`** → **`None`** |
| verify_critical_resolved.py | CR2 | 107–111 | R2 | Heartbeat tests on **`GRIND_GBPUSD_OPTC`** → **`GRIND_EURUSD_OPTC`** (live, not retired) so halt rows are not auto-resolved as retired |
| verify_critical_resolved.py | CR3 | 117–127 | R2 | Same instance swap **`GRIND_GBPUSD_OPTC`** → **`GRIND_EURUSD_OPTC`** |
| verify_critical_resolved.py | CR4 | 132–135 | R2 | Same **`GRIND_GBPUSD_OPTC`** → **`GRIND_EURUSD_OPTC`** for no-heartbeat case |
| verify_c90_d_commission.py | DM1 | 87–95 | R2 | `DUP_INST = GRIND_NZDCAD_OPTD` → **`GRIND_GBPUSD_OPTD`** (live on D strip); same DUPLICATE_MAGIC resolved behaviour |
| verify_c90_d_commission.py | DM2 | 98–105 | R2 | Same **`GRIND_NZDCAD_OPTD`** → **`GRIND_GBPUSD_OPTD`** for missing hb |
| verify_c90_d_commission.py | DM4 | 119–125 | R2 | Same **`GRIND_NZDCAD_OPTD`** → **`GRIND_GBPUSD_OPTD`**; expect no resolved when halted |
| verify_c97_orphan_ext.py | OX1, OX2, OX8 | 38, 104–120, 178–191 | R2 | `INST = GRIND_NZDCAD_OPTD` → **`GRIND_AUDCAD_OPTD`** (live on D strip); recompute ticket/price labels in detail strings if needed (same layer structure) |
| verify_c97_orphan_ext.py | OX6 | 168–174 | R2 | Two-instance case: keep **`GRIND_AUDCAD_OPTD`**; replace **`GRIND_NZDCAD_OPTD`** leg with **`GRIND_GBPUSD_OPTD`** |
| verify_c137_sr_table.py | ST8 | 453–456 | R3 | `_find(..., "GRIND_NZDCAD_OPTD", "S")` → **`None`**; move “silent grey” assertion to a live D strip instance with no closes, or drop row |
| verify_fleet_c_status.py | FC1 | 132–133 | R1 | Local `GRIND_C_INSTANCES` constant → s2 **15** ids |
| verify_fleet_c_status.py | FC3 | 151–156 | R1 | Probe list + **`default "GRIND_GBPUSD_OPTC"`** → **`GRIND_EURUSD_OPTC`**; **`opt_count/alt_count` `9/2`** → **`10/5`** (full C list slot counts) |
| verify_fleet_c_status.py | FC4 | 162–163 | R1 | Pinned C list → s2 **15** |
| verify_fleet_c_status.py | FC7 | 209–218 | R1 | `status_c` **`len(instances) == 11`** → **15**; **`instances_total == 11`** → **15** |
| verify_fleet_d_status.py | FD1 | 144–145 | R1 | Local D list → **17** |
| verify_fleet_d_status.py | FD3 | 163–168 | R1 | D list + **`opt_count/alt_count` `9/2`** → **`10/6`**; default stays **`GRIND_GBPUSD_OPTD`** |
| verify_fleet_d_status.py | FD4 | 174–175 | R1 | Pinned D list → **17** |
| verify_fleet_d_status.py | FD7 | (status_d len) | R1 | **`len(instances) == 11`** → **17** (same pattern as FC7) |
| verify_fleet_d_status.py | FD10 | 282–284 | R1 | D `FLEET_STRIP.instances` = nine `_OPT` only → s2 **12** strip ids; url unchanged |

**Subprocess/meta (newly failing because children fail):** verify_c114 QG6, verify_c115 QT7, verify_c129 GT8, verify_c131 RR7, verify_c137 ST14, verify_c102 EI5 — fixed when rows above are applied.

**STOP — does not fit R1–R3 (do not edit without operator):**
- **verify_c137_sr_table.py ST9 / ST12:** `UnicodeDecodeError` reading `dashboard.html` with default encoding on Windows after s3 edit; baseline ST9 passed in this run. Fix: open with `encoding="utf-8"` in test, not product code.

---

## 5. Tests commit (`verify_twoarm_fleets.py` only) — expected failures

Before `app.py` / dashboard changes:

| Check | Why it fails |
|-------|----------------|
| **TA1–TA3** | Lists/strips/retired still at `main` values. |
| **TA4** | No E in `FLEET_STRIP`. |
| **TA5** | `_grind_slot` lacks `OPTE`/`ALTE`. |
| **TA6** | No `GRIND_FLEET_INSTANCES["E"]`. |
| **TA7** | Four cards; no E placeholder; books unchanged. |
| **TA8** | No `gbpchf` ring. |
| **TA10** | Nine book rows, not 17. |
| **TA11** | Default still `GRIND_INSTANCES[0]` (C opens on retired `GRIND_GBPUSD_OPTC`). |
| **TA9** | **PASS** — guard on unchanged A/B. |

---

## 6. STOP

Waiting for operator **"go"** (Claude approves s5 table first). No implementation commit on this branch.

Line count: 99
