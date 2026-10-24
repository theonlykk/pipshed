This message has a line count at the bottom

# CURSOR PROMPT -- FLEET A's CARD RETIRED (pipshed; tests first; no order path)

From Claude (Lead Engineer), 24 Oct 2026 ~04:20Z, for Cursor in `D:\pipshed`. Not reviewed by Argon: the
operator ruled ~03:50Z that this change goes to Cursor without Argon (as E's card: test fixtures and one
config entry deleted; no order path, nothing an EA reads). Code base: pipshed `0f80b30` (E's card built,
live since 23 Oct ~19:33Z); `main` holds that code plus commits that add or change only this prompt file (s5).

## 0. RESTATE AND STOP (do this first, then wait)

Before any edit: for each of the nine files in s3 and s4, restate its edits in ONE line (the edit numbers
and what each does, e.g. "T1-T7 verify_c113: BK1 rows B-first, BK3 B GBPCHF, ..."), confirm that every
`old` block in s3 and s4 occurs EXACTLY ONCE in its file at `0f80b30`, and list the two commits you will
make (s5). Then STOP and wait for the operator to reply "go". Do not edit, run or commit anything before "go".

## 1. AUDIT TRAIL

| # | Fact | Where (at `0f80b30`) | Status |
|---|---|---|---|
| F1 | Fleet A (FTMO 1514878887) closed 21 Oct: Algo off 21:46:11Z, EAs removed 21:51Z, the Windows VPS destroyed 22 Oct | fxmatrix `HANDOFF_2026-09-24.md` s87 continued 4 | VERIFIED |
| F2 | A's card shows NO CONNECTION on every page's strip, and its link `https://pipshed.com` now serves E's page (`GRIND_FLEET=E` on that service since 23 Oct ~22:15Z) | `app.py` 214-228 | VERIFIED |
| F3 | The operator's ruling (24 Oct ~03:50Z): drop A's `FLEET_STRIP` entry (no RETIRED card); KEEP 1514878887's and 1514731800's rows in `sr_table.py` (commission, regime start: history) | fxmatrix HANDOFF s90; 08_BACKLOG C158 | RULED |
| F4 | Dropping the entry alone changes 31 checks in 9 scripts: A is a fixture (BK1, BK3-5, QG2, QT4, QT5, GT3, GT5, ST8, ST10, ST11, FS2, FS4, FS8, FS11, FS20, FS22, FS37, FS42-44, TA4, TA7, TA10, TR5) or a script re-runs one that fails (QG6, QT7, SA5, GT8, ST14) | the nine scripts | VERIFIED (Claude ran it) |
| F5 | The books / gaps / quotes / geometry row order is first appearance across the strip's lists; without A it starts from B's nine: GBPUSD, EURUSD, EURGBP, AUDCAD, AUDCHF, CADCHF, NZDCHF, NZDCAD, AUDNZD, then C's EURUSD*, AUDCAD*, GBPCHF, GBPCHF*, then D's GBPUSD*, EURGBP*, AUDCHF*, CADCHF* (E adds none) | `GRIND_B/C/D/E_STRIP_INSTANCES` | DERIVED BY HAND, then VERIFIED |
| F6 | Where a check used A as the FTMO case (QT4 lattice, GT3 base-only geometry, ST8 commission 0.06, FS11 silent fleet, FS20 badge, FS22 event, FS37 summary, FS43-44 ring), it moves to E (FTMO 1515045375, rate 0.06) with the same hand-derived values | s3 | DESIGN |
| F7 | `GRIND_A_STRIP_INSTANCES`, `GRIND_A_INSTANCES` and the `GRIND_FLEET` default "A" STAY: A's own page list and the fixtures still read them | `app.py` 196, 270 | DESIGN |
| F8 | Seven checks need `VERIFY_DATABASE_URL` (a scratch database) and fail without it on `main` today: `verify_archive_carrypass`, `verify_archive_codes_depth`, `verify_c102_ejection_index` (4/5), `verify_c131_reroll_resolved` (8/10), `verify_c137_snapshots` (4/8), `verify_c137_sr_table` ST6 ST7 ST16, `verify_ejection_telemetry` (28/33) | those scripts | VERIFIED (base: 39 of 46 scripts exit 0) |

## 2. ONE WORKED EXAMPLE

Today every page's strip shows five cards, A's reading NO CONNECTION with a link to pipshed.com (which now
shows E), and the books table has columns A, B, C, D, E with A's seven rows first (GBPUSD, EURUSD, EURGBP,
AUDCHF, ...). After this change the strip shows four cards, B, C, D, E; the books, quote-gap, quotes,
geometry and scalps-per-roll tables lose the A column, and their rows start with B's order (GBPUSD, EURUSD,
EURGBP, AUDCAD, ...): AUDCAD moves up from 8th to 4th, because A had none. Nothing else on any card moves.

## 3. COMMIT 1 -- TESTS FIRST (51 edits in 8 scripts; expected to FAIL against the base code)

Each edit: the `old` block is the exact text at `0f80b30` (every leading space counts; the line numbers
are `0f80b30`'s and are for orientation only, the text decides), replaced by the `new` block. An empty
`new` block deletes the `old` text. Apply them top to bottom within each file.

### scripts/verify_c113_fleet_books.py (BK1, BK3, BK4, BK5 and their docstring)

T1. line 13-14, old:

```text
     strip's instance lists (A, B, C, D); a twin (`_ALT*` slot) is its own
     row, `PAIR*`;
```

T1 new:

```text
     strip's instance lists (B, C, D, E since A's card retired, C158); a
     twin (`_ALT*` slot) is its own row, `PAIR*`;
```

T2. line 22, old:

```text
   Retired instances never appear (A lists its strip seven).
```

T2 new:

```text
   Retired instances never appear; A (closed 21 Oct) has no column (C158).
```

T3. line 118, old:

```text
    # A: the seven, simple values
```

T3 new:

```text
    # A: the seven still post in this fixture; A is off the strip (C158), so
    # none of them may reach the books (BK5)
```

T4. line 155-158, old:

```text
    want_fleets = ["A", "B", "C", "D", "E"]
    # first appearance across A's seven, then B's list order (hand-written)
    want_rows = ["GBPUSD", "EURUSD", "EURGBP", "AUDCHF", "CADCHF", "NZDCAD",
                 "AUDNZD", "AUDCAD", "NZDCHF",
```

T4 new:

```text
    want_fleets = ["B", "C", "D", "E"]
    # first appearance across B's nine (list order), then C's new rows
    # (EURUSD*, AUDCAD*, GBPCHF, GBPCHF*), then D's (GBPUSD*, EURGBP*,
    # AUDCHF*, CADCHF*); E adds none (hand-written, C158)
    want_rows = ["GBPUSD", "EURUSD", "EURGBP", "AUDCAD", "AUDCHF", "CADCHF",
                 "NZDCHF", "NZDCAD", "AUDNZD",
```

T5. line 201-202, old:

```text
    if _cell(books, "AUDCAD", "A") is not None:
        bad.append(f"A has no AUDCAD -> {_cell(books, 'AUDCAD', 'A')}")
```

T5 new:

```text
    if _cell(books, "GBPCHF", "B") is not None:
        bad.append(f"B has no GBPCHF -> {_cell(books, 'GBPCHF', 'B')}")
```

T6. line 215-218, old:

```text
    # A: k = 0..6, long k, short 7-k, mtm -k -> long 21, short 28, net -7, mtm -21.0
    want_a = {"long": 21, "short": 28, "net": -7, "mtm": -21.0, "live": 7}
    ok = t.get("B") == B_TOTALS and t.get("C") == want_c and t.get("A") == want_a
    check("BK4", ok, f"A {t.get('A')}; B {t.get('B')}; C {t.get('C')}")
```

T6 new:

```text
    # A: off the strip (C158): no totals although its seven post in the fixture
    ok = t.get("B") == B_TOTALS and t.get("C") == want_c and "A" not in t
    check("BK4", ok, f"A {t.get('A', 'absent')}; B {t.get('B')}; C {t.get('C')}")
```

T7. line 227-229, old:

```text
    a_rows = [r["pair"] for r in books["rows"] if r["cells"].get("A") is not None]
    ok = not leaked and len(a_rows) == len(pipshed.GRIND_A_STRIP_INSTANCES)
    check("BK5", ok, f"retired ids in books {leaked}; A rows {len(a_rows)}")
```

T7 new:

```text
    a_cells = [r["pair"] for r in books["rows"] if "A" in r["cells"]]
    ok = not leaked and not a_cells
    check("BK5", ok, f"retired ids in books {leaked}; rows with an A cell {a_cells}")
```

### scripts/verify_c114_quote_gap.py (QG2)

T8. line 85, old:

```text
    fake = FakeRedis()
```

T8 new:

```text
    fake = FakeRedis()
    # A's seven still post here; A is off the strip (C158), QG2
```

T9. line 146, old:

```text
        ("AUDCAD", "A"): None,
```

T9 new:

```text
        ("GBPCHF", "B"): None,
        # A is off the strip (C158): no A cell at all, though its seven post
        ("EURUSD", "A"): "MISSING",
```

### scripts/verify_c115_quotes.py (QT4 moves to E; QT5)

T10. line 10-11, old:

```text
1. FLEET_STRIP entries carry "lattice" (B, C, D: True, the ADR-162 lattice
   live since C63 / D0; A: False, cycle 3 runs ADR-157 ejection).
```

T10 new:

```text
1. FLEET_STRIP entries carry "lattice" (B, C, D, E: True, the ADR-162 lattice
   live since C63 / D0; A's card retired, C158).
```

T11. line 118, old:

```text
# A EURGBP: 8 long, no lattice on A
```

T11 new:

```text
# A EURGBP (A off the strip, C158) and E EURGBP (FTMO, lattice): 8 long, none rolled
```

T12. line 163-164, old:

```text
            fake.set(f"fxmatrix:state:{inst}", plain)
    return fake
```

T12 new:

```text
            fake.set(f"fxmatrix:state:{inst}", plain)
    # E: only EURGBP posts (QT4); A's EURGBP above is the same book, off the strip
    fake.set("fxmatrix:state:GRIND_EURGBP_OPTE", state(
        [o("SELL_LIMIT", 0.8521, "GRIND|OPT|S|L00|ENT")], A_EURGBP_LONG, long_n=8, short_n=0))
    return fake
```

T13. line 213-222, old:

```text
def qt4_no_lattice_on_a(q):
    # C137 (changed by hand): A runs the IC strategy with the lattice since 7 Oct
    # 22:08Z (FTMO 1514878887), so its capped side shows the lattice's next level
    # like B, C, D: 8 long at 0.8540 down by 3 pips, deepest 0.8519, none rolled ->
    # virtual bid 0.8519 - 3 pips = 0.8516, rolls left 8, gap to the 0.8521 offer
    # 5.0 pips. (Before C137: no lattice on A, so no virtual level.)
    w = want(offer=0.8521, offer_kind="entry", rolls_left_long=8, virtual_bid=0.8516,
             virtual_gap_pips=5.0)
    got = cell(q, "EURGBP", "A")
    check("QT4", got == w, f"EURGBP A (FTMO-IC, lattice) {got}")
```

T13 new:

```text
def qt4_lattice_on_ftmo(q):
    # C158 (changed by hand): A's card retired, so the FTMO lattice case moves to
    # E (FTMO 1515045375, lattice): 8 long at 0.8540 down by 3 pips, deepest 0.8519,
    # none rolled -> virtual bid 0.8519 - 3 pips = 0.8516, rolls left 8, gap to the
    # 0.8521 offer 5.0 pips. A's EURGBP posts the same book and has no cell.
    w = want(offer=0.8521, offer_kind="entry", rolls_left_long=8, virtual_bid=0.8516,
             virtual_gap_pips=5.0)
    got = cell(q, "EURGBP", "E")
    a = cell(q, "EURGBP", "A")
    check("QT4", got == w and a == "MISSING", f"EURGBP E (FTMO, lattice) {got}; A {a}")
```

T14. line 230, old:

```text
    ok = got == w and cell(q, "NZDCHF", "C") is None and cell(q, "AUDCAD", "A") is None
```

T14 new:

```text
    ok = got == w and cell(q, "NZDCHF", "C") is None and cell(q, "GBPCHF", "B") is None
```

T15. line 295, old:

```text
    if lattice != {"A": True, "B": True, "C": True, "D": True}:
```

T15 new:

```text
    if lattice != {"B": True, "C": True, "D": True, "E": True}:
```

T16. line 300, old:

```text
    qt4_no_lattice_on_a(q)
```

T16 new:

```text
    qt4_lattice_on_ftmo(q)
```

### scripts/verify_c119_twins_retired.py (TR5 row order)

T17. line 57, old:

```text
    "GBPUSD", "EURUSD", "EURGBP", "AUDCHF", "CADCHF", "NZDCAD", "AUDNZD", "AUDCAD", "NZDCHF",
```

T17 new:

```text
    # C158: A retired; first appearance across B's nine, then C, D, E (by hand)
    "GBPUSD", "EURUSD", "EURGBP", "AUDCAD", "AUDCHF", "CADCHF", "NZDCHF", "NZDCAD", "AUDNZD",
```

### scripts/verify_c129_geometry.py (GT3 moves to E; GT5)

T18. line 115-116, old:

```text
    # A (FTMO, aa6970a): no per-side keys
    "GRIND_GBPUSD_OPT": hb(5.0, 10.0, 10.0),
```

T18 new:

```text
    # E (FTMO two-arm; the no-per-side case, moved from A when A's card retired, C158)
    "GRIND_GBPUSD_OPTE": hb(5.0, 10.0, 10.0),
```

T19. line 123, old:

```text
    for letter in ("A", "B", "C", "D"):
```

T19 new:

```text
    for letter in ("B", "C", "D", "E"):
```

T20. line 127, old:

```text
            fake.set(f"fxmatrix:state:{inst}", SPECIAL.get(inst, hb(5.0, 6.0, 10.0)))
```

T20 new:

```text
            fake.set(f"fxmatrix:state:{inst}", SPECIAL.get(inst, hb(5.0, 6.0, 10.0)))
    # A's GBPUSD still posts; A is off the strip (C158), so it has no cell (GT3)
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPT", hb(5.0, 10.0, 10.0))
```

T21. line 169-174, old:

```text
    # A sends only width_pips / add_pips / exit_pips (5 / 10 / 10): both sides from the base;
    # against B (2.5 / 9 / 10) width and add differ on both sides, exit does not
    a = cell(g, "GBPUSD", "A")
    wa = live(8, (5.0, 5.0), (10.0, 10.0), (10.0, 10.0),
              ["add_long", "add_short", "width_long", "width_short"])
    check("GT3", a == wa, f"GBPUSD A {a}")
```

T21 new:

```text
    # E's GBPUSD here sends only width_pips / add_pips / exit_pips (5 / 10 / 10): both sides
    # from the base; against B (2.5 / 9 / 10) width and add differ on both sides, exit does
    # not. A's GBPUSD posts the same and has no cell (A retired, C158).
    e = cell(g, "GBPUSD", "E")
    we = live(8, (5.0, 5.0), (10.0, 10.0), (10.0, 10.0),
              ["add_long", "add_short", "width_long", "width_short"])
    a = cell(g, "GBPUSD", "A")
    check("GT3", e == we and a == "MISSING", f"GBPUSD E {e}; A {a}")
```

T22. line 186, old:

```text
    # AUDCAD on A: A has no such instance -> null
```

T22 new:

```text
    # GBPCHF on B: B has no such instance -> null
```

T23. line 191-192, old:

```text
    ok = nb == {"live": False} and nc is None and nd is None and cell(g, "AUDCAD", "A") is None
    check("GT5", ok, f"NZDCHF B {nb}; C {nc}; D {nd}; AUDCAD A {cell(g, 'AUDCAD', 'A')}")
```

T23 new:

```text
    ok = nb == {"live": False} and nc is None and nd is None and cell(g, "GBPCHF", "B") is None
    check("GT5", ok, f"NZDCHF B {nb}; C {nc}; D {nd}; GBPCHF B {cell(g, 'GBPCHF', 'B')}")
```

### scripts/verify_c137_sr_table.py (ST8 (E rows), ST10, ST11)

T24. line 70, old:

```text
B_ACC, C_ACC, A_OLD, A_NEW = 53066709, 53071896, 1514731800, 1514878887
```

T24 new:

```text
B_ACC, C_ACC, A_OLD, A_NEW = 53066709, 53071896, 1514731800, 1514878887
E_ACC = 1515045375   # FTMO trial, Fleet E (C158: the strip's FTMO case since A's card retired)
```

T25. line 409-410, old:

```text

def _strip_fixture(built_at=None):
```

T25 new:

```text

# the strip's FTMO case (C158): E's GBPUSD long closes as A's a3-a5 on A_NEW, on E's account
E_STRIP_ROWS = [
    ("e3", "GRIND_GBPUSD_OPTE", E_ACC, "LONG", 1.3400, 1.3410, 1.00, "2026-10-07 23:00:00", False, False),
    ("e4", "GRIND_GBPUSD_OPTE", E_ACC, "LONG", 1.3400, 1.3380, -2.00, "2026-10-08 01:00:00", False, True),
    ("e5", "GRIND_GBPUSD_OPTE", E_ACC, "LONG", 1.3400, 1.3338, -6.20, "2026-10-08 02:00:00", True, False),
]


def _strip_fixture(built_at=None):
```

T26. line 414-416, old:

```text
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPT", _hb("GRIND_GBPUSD_OPT", A_NEW, 8, 9.0, 9.0, 10.0, 10.0))
    fake.set("fxmatrix:state:GRIND_EURUSD_OPTC", _hb("GRIND_EURUSD_OPTC", C_ACC, 8, 7.0, 6.0, 10.0, 10.0))
    payload = st.aggregate(pure_rows(), pure_rolls(), NOW)
```

T26 new:

```text
    # A still posts and the worker's table still holds a1-a5; A is off the strip (C158)
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPT", _hb("GRIND_GBPUSD_OPT", A_NEW, 8, 9.0, 9.0, 10.0, 10.0))
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPTE", _hb("GRIND_GBPUSD_OPTE", E_ACC, 8, 9.0, 9.0, 10.0, 10.0))
    fake.set("fxmatrix:state:GRIND_EURUSD_OPTC", _hb("GRIND_EURUSD_OPTC", C_ACC, 8, 7.0, 6.0, 10.0, 10.0))
    e_rows = [{"instance_id": inst, "account_login": acc, "direction": d, "entry_price": ep,
               "exit_price": xp, "gross_pnl": g, "close_utc": T(t), "rolled": rolled, "ejected": ejected}
              for _k, inst, acc, d, ep, xp, g, t, rolled, ejected in E_STRIP_ROWS]
    payload = st.aggregate(pure_rows() + e_rows, pure_rolls(), NOW)
```

T27. line 434, old:

```text
    if not sr or sr.get("available") is not True or sr.get("fleets") != ["A", "B", "C", "D", "E"]:
```

T27 new:

```text
    if not sr or sr.get("available") is not True or sr.get("fleets") != ["B", "C", "D", "E"] \
            or "A" in (sr.get("rows") or {}):
```

T28. line 449-452, old:

```text
    # A: 1514878887 at 0.06 a close: c = 0.6, k* = (72 - 10 + 0.6) / 9.4 = 6.6596
    a = _find(sr["rows"]["A"], "GRIND_GBPUSD_OPT", "L")
    if not a or a["today"].get("k_star") != 6.66 or a["today"].get("E") != 1:
        raise AssertionError(f"A GBPUSD long on the new account: {a}")
```

T28 new:

```text
    # E: 1515045375 at 0.06 a close: c = 0.6, k* = (72 - 10 + 0.6) / 9.4 = 6.6596;
    # e4 ejected on a non-cycle-3 account -> E 1
    e = _find(sr["rows"]["E"], "GRIND_GBPUSD_OPTE", "L")
    if not e or e["today"].get("k_star") != 6.66 or e["today"].get("E") != 1 \
            or e["today"].get("c_pips") != 0.6:
        raise AssertionError(f"E GBPUSD long on FTMO 1515045375: {e}")
```

T29. line 510-512, old:

```text
    one = client.get(f"/api/g/{TOKEN}/sr/x?format=csv&instance=GRIND_GBPUSD_OPT").get_data(as_text=True)
    if len([ln for ln in one.splitlines() if ln]) != 1 + 2 * 3:
        raise AssertionError(f"instance filter: 2 sides x 3 windows; got {one.splitlines()[:3]}")
```

T29 new:

```text
    one = client.get(f"/api/g/{TOKEN}/sr/x?format=csv&instance=GRIND_GBPUSD_OPTE").get_data(as_text=True)
    if len([ln for ln in one.splitlines() if ln]) != 1 + 2 * 3:
        raise AssertionError(f"instance filter: 2 sides x 3 windows; got {one.splitlines()[:3]}")
    gone = client.get(f"/api/g/{TOKEN}/sr/x?format=csv&instance=GRIND_GBPUSD_OPT").get_data(as_text=True)
    if len([ln for ln in gone.splitlines() if ln]) != 1:
        raise AssertionError(f"A retired (C158): its instance exports the header only; got {gone.splitlines()[:3]}")
```

T30. line 521-530, old:

```text
    a = next(e for e in pipshed.FLEET_STRIP if e["letter"] == "A")
    want = {"name": "FTMO-IC 1514878887", "lattice": True, "cycle_start": "2026-10-08"}
    got = {k: a.get(k) for k in want}
    if got != want:
        raise AssertionError(f"A: expected {want}, got {got}")
    rates = pipshed.COMMISSION_PER_CLOSE_BY_ACCOUNT
    if rates is not st.COMMISSION_PER_CLOSE_BY_ACCOUNT or rates.get(1514878887) != 0.06 \
            or rates.get(1514731800) != 0.06 or rates.get(53066709) != 0.08:
        raise AssertionError(f"one commission table (app re-exports sr_table's) with 1514878887 at 0.06: {rates}")
    return "A = FTMO-IC 1514878887: lattice on, cycle from 8 Oct, commission 0.06 a close"
```

T30 new:

```text
    letters = [e["letter"] for e in pipshed.FLEET_STRIP]
    if "A" in letters:
        raise AssertionError(f"C158: A's card retired, strip letters {letters}")
    rates = pipshed.COMMISSION_PER_CLOSE_BY_ACCOUNT
    if rates is not st.COMMISSION_PER_CLOSE_BY_ACCOUNT or rates.get(1514878887) != 0.06 \
            or rates.get(1514731800) != 0.06 or rates.get(53066709) != 0.08 \
            or rates.get(1515045375) != 0.06:
        raise AssertionError(f"one commission table (app re-exports sr_table's); A's accounts kept at 0.06: {rates}")
    return "A off the strip; commission table keeps 1514878887 and 1514731800 at 0.06 (history), E 0.06"
```

### scripts/verify_fleet_strip.py (FS2, FS4, FS8, FS11, FS20, FS22, FS37, FS42, FS43, FS44)

T31. line 316-317, old:

```text
    if letters != ["A", "B", "C", "D", "E"]:
        raise AssertionError(f"letters expected ABCDE, got {letters}")
```

T31 new:

```text
    if letters != ["B", "C", "D", "E"]:
        raise AssertionError(f"letters expected BCDE (A retired, C158), got {letters}")
```

T32. line 360-367, old:

```text
    a = _fleet_by_letter(
        pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "A"
    )
    # 2 Oct 2026: cycle 3 cut to the seven-pair ring after FTMO's
    # hyperactivity warning (fxmatrix geometry-cycle3 A7); was 11.
    if (a.get("health") or {}).get("instances_total") != 7:
        raise AssertionError("A must total 7 strip instances (the ring)")
    return "A total 7"
```

T32 new:

```text
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json()
    # C158: A (FTMO 1514878887, closed 21 Oct) has no card; E (FTMO 1515045375)
    # totals its twelve two-arm strip instances
    if any(c.get("letter") == "A" for c in data.get("fleets") or []):
        raise AssertionError("A's card must be gone (C158)")
    e = _fleet_by_letter(data, "E")
    if (e.get("health") or {}).get("instances_total") != 12:
        raise AssertionError(f"E must total 12 strip instances, got {e.get('health')}")
    return "no A card; E total 12"
```

T33. line 454, old:

```text
    for letter in ("A", "B", "C"):
```

T33 new:

```text
    for letter in ("B", "C", "E"):
```

T34. line 506-520, old:

```text
    a = _fleet_by_letter(
        pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "A"
    )
    if a.get("status") != "no_data":
        raise AssertionError(f"A status expected no_data, got {a.get('status')}")
    for key in ("open_mtm",):
        if (a.get("money") or {}).get(key) is not None:
            raise AssertionError(f"A money.{key} must be null")
    risk = a.get("risk") or {}
    for key in ("open_layers_long", "deepest", "day_pnl"):
        if risk.get(key) is not None:
            raise AssertionError(f"A risk.{key} must be null")
    if (a.get("account") or {}).get("login") is not None:
        raise AssertionError("A account.login must be null")
    return "A no_data nulls"
```

T34 new:

```text
    # C158: the silent-fleet case moves from A to E (no E heartbeats in fixture fb)
    e = _fleet_by_letter(
        pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "E"
    )
    if e.get("status") != "no_data":
        raise AssertionError(f"E status expected no_data, got {e.get('status')}")
    for key in ("open_mtm",):
        if (e.get("money") or {}).get(key) is not None:
            raise AssertionError(f"E money.{key} must be null")
    risk = e.get("risk") or {}
    for key in ("open_layers_long", "deepest", "day_pnl"):
        if risk.get(key) is not None:
            raise AssertionError(f"E risk.{key} must be null")
    if (e.get("account") or {}).get("login") is not None:
        raise AssertionError("E account.login must be null")
    return "E no_data nulls"
```

T35. line 715-716, old:

```text
    if _fleet_by_letter(data, "A").get("badge") != "NO CONNECTION":
        raise AssertionError("A badge must be NO CONNECTION")
```

T35 new:

```text
    if _fleet_by_letter(data, "E").get("badge") != "NO CONNECTION":
        raise AssertionError("E badge must be NO CONNECTION (no E heartbeats here)")
```

T36. line 765, old:

```text
                "instance_id": "GRIND_GBPUSD_OPT",
```

T36 new:

```text
                "instance_id": "GRIND_GBPUSD_OPTE",
```

T37. line 790-792, old:

```text
    a_alerts = _alert_triples(_fleet_by_letter(data, "A"))
    if ("red", "EVENT", "GRIND_GBPUSD_OPT") not in a_alerts:
        raise AssertionError(f"A must include GBPUSD OPT event, got {a_alerts}")
```

T37 new:

```text
    e_alerts = _alert_triples(_fleet_by_letter(data, "E"))
    if ("red", "EVENT", "GRIND_GBPUSD_OPTE") not in e_alerts:
        raise AssertionError(f"E must include GBPUSD OPTE event, got {e_alerts}")
```

T38. line 1110-1111, old:

```text
    # A (FTMO): 1 EURGBP scalp +5.0 pips; must not appear on B's card
    _push(fake, "GRIND_EURGBP_OPT", _scalp_rec("GRIND_EURGBP_OPT", 0.85000, 0.85050, 0.67, login=1514731800))
```

T38 new:

```text
    # E (FTMO 1515045375): 1 EURGBP scalp +5.0 pips; must not appear on B's card
    _push(fake, "GRIND_EURGBP_OPTE", _scalp_rec("GRIND_EURGBP_OPTE", 0.85000, 0.85050, 0.67, login=1515045375))
```

T39. line 1134-1137, old:

```text
    a = (_fleet_by_letter(data, "A").get("summary") or {})
    # A: 1 FTMO scalp +5.0 pips, 0.67 USD; 1 close x 0.06
    if ((a.get("scalps") or {}).get("count"), a.get("commission"), a.get("net_usd")) != (1, -0.06, 0.61):
        raise AssertionError(f"fleet A summary {a}")
```

T39 new:

```text
    e = (_fleet_by_letter(data, "E").get("summary") or {})
    # E: 1 FTMO scalp +5.0 pips, 0.67 USD; 1 close x 0.06 -> net 0.61
    if ((e.get("scalps") or {}).get("count"), e.get("commission"), e.get("net_usd")) != (1, -0.06, 0.61):
        raise AssertionError(f"fleet E summary {e}")
```

T40. line 1205, old:

```text
    a = _fleet_by_letter(data, "A").get("summary") or {}
```

T40 new:

(empty: delete the old text)

T41. line 1224-1228, old:

```text
# FS43-FS44 (2 Oct 2026, fxmatrix geometry-cycle3 A7): cycle 3 runs the
# seven-pair ring. Retired: GRIND_AUDNZD_ALT, GRIND_NZDCAD_ALT (15:14Z),
# GRIND_AUDCAD_OPT, GRIND_NZDCHF_OPT (~15:40Z). Predicted at the tests-only
# commit: FS4 and FS43 FAIL (the strip still lists eleven); FS44 is a guard
# (a kept instance's event still shows) and passes in both states.
```

T41 new:

```text
# FS43-FS44 (C158, 24 Oct 2026): A's card retired (FTMO 1514878887 closed
# 21 Oct). FS43: with A's seven AND E's twelve reporting, no card is A's, E
# is LIVE 12/12, and an event on an A instance is alerted on no card. FS44 is
# a guard (an E instance's event shows on E) and passes in both states.
# (Before C158: A's seven-pair ring, geometry-cycle3 A7.)
```

T42. line 1238-1243, old:

```text
A_RETIRED = {"GRIND_AUDNZD_ALT", "GRIND_NZDCAD_ALT", "GRIND_AUDCAD_OPT", "GRIND_NZDCHF_OPT"}


def _fleet_a_ring_live(fake, crit_rows):
    for inst in A_RING:
        fake.set(f"fxmatrix:state:{inst}", HBB(30, account_login=1514731800, invariant_ok=True))
```

T42 new:

```text


def _fleets_a_and_e_live(fake, crit_rows):
    import app as pipshed

    for inst in A_RING:
        fake.set(f"fxmatrix:state:{inst}", HBB(30, account_login=1514878887, invariant_ok=True))
    for inst in pipshed.GRIND_E_STRIP_INSTANCES:
        fake.set(f"fxmatrix:state:{inst}", HBB(30, account_login=1515045375, invariant_ok=True))
```

T43. line 1251-1255, old:

```text
    if list(pipshed.GRIND_A_STRIP_INSTANCES) != A_RING:
        raise AssertionError(f"A strip must be the ring {A_RING}, got {pipshed.GRIND_A_STRIP_INSTANCES}")
    fake = FakeRedis()
    _fleet_a_ring_live(fake, [
        {"instance_id": "GRIND_AUDCAD_OPT", "level": "CRITICAL", "code": "INVARIANT_FAIL",
```

T43 new:

```text
    fake = FakeRedis()
    _fleets_a_and_e_live(fake, [
        {"instance_id": "GRIND_GBPUSD_OPT", "level": "CRITICAL", "code": "INVARIANT_FAIL",
```

T44. line 1259-1266, old:

```text
    a = _fleet_by_letter(pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "A")
    health = a.get("health") or {}
    if a.get("badge") != "LIVE" or health.get("instances_live") != 7 or health.get("instances_total") != 7:
        raise AssertionError(f"A with the seven reporting: LIVE 7/7, got {a.get('badge')}, {health}")
    named = {al.get("instance_id") for al in a.get("alerts") or []}
    if named & A_RETIRED:
        raise AssertionError(f"retired instances must not be alerted on A: {sorted(named & A_RETIRED)}")
    return "A = the seven-pair ring, LIVE 7/7, no alerts for retired instances"
```

T44 new:

```text
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json()
    if any(c.get("letter") == "A" for c in data.get("fleets") or []):
        raise AssertionError("A's card must be gone though its seven report (C158)")
    e = _fleet_by_letter(data, "E")
    health = e.get("health") or {}
    if e.get("badge") != "LIVE" or health.get("instances_live") != 12 or health.get("instances_total") != 12:
        raise AssertionError(f"E with the twelve reporting: LIVE 12/12, got {e.get('badge')}, {health}")
    named = {al.get("instance_id") for c in data.get("fleets") or [] for al in c.get("alerts") or []}
    if named & set(A_RING):
        raise AssertionError(f"A's instances must not be alerted on any card: {sorted(named & set(A_RING))}")
    return "no A card though A reports; E LIVE 12/12; no alerts for A's instances"
```

T45. line 1273-1274, old:

```text
    _fleet_a_ring_live(fake, [
        {"instance_id": "GRIND_AUDNZD_OPT", "level": "CRITICAL", "code": "STARTUP_EXIT_SHORTFALL",
```

T45 new:

```text
    _fleets_a_and_e_live(fake, [
        {"instance_id": "GRIND_AUDCHF_ALTE", "level": "CRITICAL", "code": "STARTUP_EXIT_SHORTFALL",
```

T46. line 1278-1283, old:

```text
    a = _fleet_by_letter(pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "A")
    hits = [al for al in a.get("alerts") or []
            if al.get("instance_id") == "GRIND_AUDNZD_OPT" and al.get("code") == "STARTUP_EXIT_SHORTFALL"]
    if not hits:
        raise AssertionError(f"a kept ring instance's event must still show on A: {a.get('alerts')}")
    return "events of kept instances still show on A"
```

T46 new:

```text
    e = _fleet_by_letter(pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "E")
    hits = [al for al in e.get("alerts") or []
            if al.get("instance_id") == "GRIND_AUDCHF_ALTE" and al.get("code") == "STARTUP_EXIT_SHORTFALL"]
    if not hits:
        raise AssertionError(f"an E instance's event must show on E: {e.get('alerts')}")
    return "events of E's instances show on E"
```

### scripts/verify_twoarm_fleets.py (TA4, TA7, TA10 row order)

T47. line 130, old:

```text
    "GBPUSD", "EURUSD", "EURGBP", "AUDCHF", "CADCHF", "NZDCAD", "AUDNZD", "AUDCAD", "NZDCHF",
```

T47 new:

```text
    # C158: A retired; first appearance across B's nine, then C, D, E (by hand)
    "GBPUSD", "EURUSD", "EURGBP", "AUDCAD", "AUDCHF", "CADCHF", "NZDCHF", "NZDCAD", "AUDNZD",
```

T48. line 340, old:

```text
    if letters != ["A", "B", "C", "D", "E"]:
```

T48 new:

```text
    if letters != ["B", "C", "D", "E"]:
```

T49. line 348, old:

```text
    return "five fleets; E built fields"
```

T49 new:

```text
    return "four fleets (A retired); E built fields"
```

T50. line 384-385, old:

```text
    if len(cards) != 5:
        raise AssertionError(f"expected 5 cards, got {len(cards)}")
```

T50 new:

```text
    if len(cards) != 4 or any(c.get("letter") == "A" for c in cards):
        raise AssertionError(f"expected 4 cards, no A, got {[c.get('letter') for c in cards]}")
```

T51. line 392-394, old:

```text
    if books.get("fleets") != ["A", "B", "C", "D", "E"]:
        raise AssertionError(f"books fleets {books.get('fleets')}")
    return "five cards; E built; books ABCDE"
```

T51 new:

```text
    if books.get("fleets") != ["B", "C", "D", "E"]:
        raise AssertionError(f"books fleets {books.get('fleets')}")
    return "four cards (A retired); E built; books BCDE"
```

**After commit 1, run every `scripts/verify_*.py` (s6). Expected, against the base code: exactly these
NEW failures, no others:** BK1, BK4, BK5 (`verify_c113_fleet_books` 4/7); QG2, QG6 (`verify_c114_quote_gap`
4/6); QT4, QT7 (`verify_c115_quotes` 6/8); TR5 (`verify_c119_twins_retired` passed=5 failed=1); SA5
(`verify_c123_side_add` 4/5, unedited: it re-runs `verify_c115_quotes`); GT3, GT8 (`verify_c129_geometry`
6/8); ST8, ST10, ST11, ST14 (`verify_c137_sr_table` 11/18 with F8's ST6, ST7, ST16); FS2, FS4, FS43
(`verify_fleet_strip` passed=41 failed=3); TA4, TA7, TA10 (`verify_twoarm_fleets` 8/11). Every other
script as at the base (F8).

**These edited checks PASS in both states; that is expected and must be reported, not "fixed":** BK3,
QT5, GT5, FS8, FS11, FS20, FS22, FS37, FS42 (they move a fixture off A so the check keeps its coverage
after A goes) and FS44 (a guard: an E event shows on E).

## 4. COMMIT 2 -- THE CODE (one edit)

C1. `app.py` lines 213-228, A's `FLEET_STRIP` entry, old:

```text
FLEET_STRIP = [
    {
        "letter": "A",
        # C137: since 7 Oct 22:08Z FTMO 1514878887 runs the IC strategy (lattice,
        # re-roll, roll gate 0) static at B's round-2 anchor; cycle 3 (1514731800,
        # ADR-157 ejection, no lattice) retired 21:23Z. Same seven ids and magics.
        "name": "FTMO-IC 1514878887",
        "broker": "FTMO",
        "url": "https://pipshed.com",
        "instances": GRIND_A_STRIP_INSTANCES,
        "lattice": True,
        "daily_loss_limit_usd": 500.0,
        "cycle_start": "2026-10-08",
        "start_balance": 10000.0,
        "placeholder": False,
    },
```

C1 new:

```text
FLEET_STRIP = [
```

That is: delete the first dict of `FLEET_STRIP` (the 15 lines from `{` to `},` whose `"letter"` is "A"),
nothing else. `GRIND_A_STRIP_INSTANCES` (`app.py` 196) and `GRIND_FLEET_INSTANCES["A"]` stay (F7).

**After commit 2, run every `scripts/verify_*.py`. Expected: every script exactly as at the base `0f80b30`**
(39 of 46 exit 0; the only failures F8's; `verify_fleet_strip` passed=44 failed=0, `verify_twoarm_fleets`
11/11, `verify_c113_fleet_books` 7/7, `verify_c137_sr_table` 15/18).

## 5. BRANCH AND COMMITS

- Branch `a-card-retired` from the current `main`. First check that `main` holds the code base and only this
  prompt on top: `git diff --stat 0f80b30 HEAD` must list ONLY `prompts/cursor_a_card_retired.md`.
- Commit 1 message: `verify: A retired (strip BCDE; FTMO cases move to E) -- tests first`
- Commit 2 message: `Fleet A card retired: FLEET_STRIP entry removed (C158)`
- `git add` each file by name. Push the BRANCH only (`git push origin a-card-retired`).

## 6. RUNNING THE CHECKS

From `D:\pipshed` in the venv, one script at a time (they are independent); this prints each script's
name, exit code and last line:

    Get-ChildItem scripts\verify_*.py | ForEach-Object { $o = python $_.FullName 2>&1 | Out-String; "{0} exit={1} | {2}" -f $_.BaseName, $LASTEXITCODE, (($o -split "`n" | Where-Object { $_.Trim() }) | Select-Object -Last 1) }

Report the 46 lines at the base, after commit 1 and after commit 2 (three lists), and for commit 1 the
failing check names per script (both forms: `FAIL BK1 ...` and `TA4 FAIL: ...`). If your machine has
`VERIFY_DATABASE_URL` set, say so: F8's checks may then pass, which is fine; report them.

## 7. NEGATIVE SPACE (do NOT)

- Do not push to `main`, merge, open a PR, or deploy: a push to `main` deploys every page service at once.
- Do not touch `sr_table.py` (1514878887's and 1514731800's rows STAY, F3), `templates/`, `archive_worker.py`,
  `ftmo_daily.py`, `ejection_view.py`, migrations, or any file not named in s3 and s4.
- Do not remove or rename `GRIND_A_INSTANCES`, `GRIND_A_STRIP_INSTANCES`, the `GRIND_FLEET` default "A",
  `GRIND_RETIRED_INSTANCES`, or any other fleet's `FLEET_STRIP` entry (F7).
- Do not edit any check not named in s3, and never change an expected value to make a check pass.
- No `git add .` or `-u`; no `git stash`; no checkout of files from other commits; no force push.
- Do not run any script against Railway, Redis or a real database; no `railway` command.

## 8. FAILURE MODES (STOP and report; do not improvise)

- An `old` block in s3 or s4 not found exactly once in its file: STOP, quote what is there.
- After commit 1, a failure other than s3's list, or one of s3's list NOT failing: STOP, report the line.
- After commit 2, any script not as at the base: STOP, report the script and its failing check.
- `git diff --stat 0f80b30 HEAD` lists any file but `prompts/cursor_a_card_retired.md` at the start: STOP.

## 9. WHAT CLAUDE CHECKS AFTER

Claude fetches `a-card-retired`, diffs both commits against a reference built independently on `0f80b30`
(the changed lines must be byte-identical), and reruns every check at each commit. Then the operator
merges to `main` by fast-forward and pushes, outside 20:50-21:00Z; Claude reads the strip (four cards,
B C D E) on every page.

Line count: 1007
