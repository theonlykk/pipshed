"""Verification: C129, the geometry table per pair and fleet on the fleet strip.

Operator 5 Oct 2026 (~19:40Z): "seeing the inputs will be reassuring and
allow us to get a feel for their impact - and not have to keep pulling from
separate locations or rely on memory"; 6 Oct (~01:51Z): "can we update
pipshed with the add/exit, width layers for each fleet?"

Rule (C129):
1. The strip response carries `geometry` (same fleets and row order as
   `books`), from the heartbeats the strip already reads (no new reads). A
   live cell: {"live": true, "cap", "width": [L, S], "add": [L, S],
   "exit": [L, S], "vs_anchor"}:
   - cap = the card's max_layers;
   - each side's width / add / exit = the heartbeat's
     `<k>_pips_long` / `<k>_pips_short` when a number > 0 (fxgrind v2.0,
     `fxgrind.mq5` 103-105: the resolved per-side values), else the card's
     base `<k>_pips` (older builds, e.g. FTMO's `aa6970a`, send no per-side
     keys); rounded to 2 dp;
   - vs_anchor (the anchor is fleet B): on B, []; on any other fleet, the
     sorted keys among cap, width_long, width_short, add_long, add_short,
     exit_long, exit_short whose value differs from B's cell for the pair;
     null when B's cell is not live or absent.
   Not reporting = {"live": false}; a fleet without the pair = null.
   The response also carries "anchor": "B".
2. Page: renderFleetGeometry(data && data.geometry) from fetchFleetStrip
   (renderFleetGeometry(null) on the error path), drawn in
   <div id="fleetGeometry"> under the books tables, a table titled
   "geometry"; geoHtml(cell) gives "W<w> A<add> X<exit> c<cap>", a pair of
   sides as "L/S" only where they differ, and wraps each part that differs
   from the anchor in <span class="g-diff">.

Tests first. Predicted at the tests-only commit: GT1-GT7 FAIL; GT8 (C113,
C114, C115, C119 still pass) is a guard.

    python scripts/verify_c129_geometry.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["GRIND_FLEET"] = "A"
os.environ.pop("GRIND_FLEET_LABEL", None)

import app as pipshed  # noqa: E402

TOKEN = pipshed.PUBLIC_GRIND_STATUS_TOKEN
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeRedis:
    def __init__(self):
        self.kv = {}

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value, ex=None):
        self.kv[key] = value

    def mget(self, keys):
        return [self.kv.get(k) for k in keys]

    def lrange(self, key, start, end):
        return []

    def hgetall(self, key):
        return {}

    def hget(self, key, field):
        return None


def hb(width, add, exit_, cap=8, sides=None):
    """A heartbeat: base width / add / exit (the long side's resolved values,
    as the EA sends them) and, when `sides` is given, the v2.0 per-side keys."""
    d = {"_received_at": NOW, "open_layers_long": 1, "open_layers_short": 1, "net_mtm": 0.0,
         "max_layers": cap, "width_pips": width, "add_pips": add, "exit_pips": exit_,
         "halted": False, "book": {"orders": [], "positions": []}, "layers": []}
    if sides:
        (wl, ws), (al, as_), (xl, xs) = sides
        d.update({"width_pips_long": wl, "width_pips_short": ws, "add_pips_long": al,
                  "add_pips_short": as_, "exit_pips_long": xl, "exit_pips_short": xs})
    return json.dumps(d)


def strip(letter):
    for e in pipshed.FLEET_STRIP:
        if e["letter"] == letter:
            return e["instances"]
    return []


SPECIAL = {
    # B, the anchor
    "GRIND_GBPUSD_OPTB": hb(2.5, 9.0, 10.0, sides=((2.5, 2.5), (9.0, 9.0), (10.0, 10.0))),
    "GRIND_EURGBP_OPTB": hb(1.0, 3.0, 5.0, sides=((1.0, 1.0), (3.0, 3.0), (5.0, 5.0))),
    "GRIND_AUDCAD_OPTB": hb(1.5, 6.0, 10.0, sides=((1.5, 1.5), (6.0, 6.0), (10.0, 10.0))),
    # B AUDCHF: a per-side add of 0.0 (not > 0) falls back to the base add 4.0
    "GRIND_AUDCHF_OPTB": hb(1.0, 4.0, 10.0, sides=((1.0, 1.0), (0.0, 4.0), (10.0, 10.0))),
    "GRIND_NZDCAD_OPTB": hb(2.0, 8.0, 10.0, sides=((2.0, 2.0), (8.0, 8.0), (10.0, 10.0))),
    # C, the add probe
    "GRIND_GBPUSD_OPTC": hb(2.5, 8.0, 10.0, sides=((2.5, 2.5), (8.0, 8.0), (10.0, 10.0))),
    "GRIND_EURGBP_OPTC": hb(1.0, 2.5, 5.0, sides=((1.0, 1.0), (2.5, 4.0), (5.0, 5.0))),
    "GRIND_AUDCAD_OPTC": hb(1.5, 5.0, 10.0, sides=((1.5, 1.5), (5.0, 6.0), (10.0, 10.0))),
    # D, the exit probe
    "GRIND_GBPUSD_OPTD": hb(2.5, 9.0, 9.0, sides=((2.5, 2.5), (9.0, 9.0), (9.0, 9.0))),
    "GRIND_NZDCAD_OPTD": hb(2.0, 8.0, 10.0, cap=10, sides=((2.0, 2.0), (8.0, 8.0), (10.0, 10.0))),
    "GRIND_NZDCHF_OPTD": hb(1.0, 3.0, 9.0, sides=((1.0, 1.0), (3.0, 3.0), (9.0, 9.0))),
    # A (FTMO, aa6970a): no per-side keys
    "GRIND_GBPUSD_OPT": hb(5.0, 10.0, 10.0),
}
ABSENT = {"GRIND_NZDCHF_OPTB", "GRIND_NZDCHF_OPTC"}


def fixture():
    fake = FakeRedis()
    for letter in ("A", "B", "C", "D"):
        for inst in strip(letter):
            if inst in ABSENT:
                continue
            fake.set(f"fxmatrix:state:{inst}", SPECIAL.get(inst, hb(5.0, 6.0, 10.0)))
    return fake


results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")


def cell(g, pair, letter):
    for row in (g or {}).get("rows", []):
        if row["pair"] == pair:
            return row["cells"].get(letter, "MISSING")
    return "NO ROW"


def live(cap, width, add, exit_, vs):
    return {"live": True, "cap": cap, "width": list(width), "add": list(add), "exit": list(exit_),
            "vs_anchor": vs}


def gt1_anchor_and_add_probe(g):
    b = cell(g, "GBPUSD", "B")
    c = cell(g, "GBPUSD", "C")
    wb = live(8, (2.5, 2.5), (9.0, 9.0), (10.0, 10.0), [])
    wc = live(8, (2.5, 2.5), (8.0, 8.0), (10.0, 10.0), ["add_long", "add_short"])
    check("GT1", b == wb and c == wc and (g or {}).get("anchor") == "B", f"GBPUSD B {b}; C {c}")


def gt2_sides_differ(g):
    # EURGBP C 2.5 / 4.0 against B 3 / 3: both add sides differ;
    # AUDCAD C 5 / 6 against B 6 / 6: only the long add differs
    e = cell(g, "EURGBP", "C")
    a = cell(g, "AUDCAD", "C")
    we = live(8, (1.0, 1.0), (2.5, 4.0), (5.0, 5.0), ["add_long", "add_short"])
    wa = live(8, (1.5, 1.5), (5.0, 6.0), (10.0, 10.0), ["add_long"])
    check("GT2", e == we and a == wa, f"EURGBP C {e}; AUDCAD C {a}")


def gt3_ftmo_base_values(g):
    # A sends only width_pips / add_pips / exit_pips (5 / 10 / 10): both sides from the base;
    # against B (2.5 / 9 / 10) width and add differ on both sides, exit does not
    a = cell(g, "GBPUSD", "A")
    wa = live(8, (5.0, 5.0), (10.0, 10.0), (10.0, 10.0),
              ["add_long", "add_short", "width_long", "width_short"])
    check("GT3", a == wa, f"GBPUSD A {a}")


def gt4_exit_probe_and_cap(g):
    d = cell(g, "GBPUSD", "D")
    n = cell(g, "NZDCAD", "D")
    wd = live(8, (2.5, 2.5), (9.0, 9.0), (9.0, 9.0), ["exit_long", "exit_short"])
    wn = live(10, (2.0, 2.0), (8.0, 8.0), (10.0, 10.0), ["cap"])
    check("GT4", d == wd and n == wn, f"GBPUSD D {d}; NZDCAD D {n}")


def gt5_not_live_absent_no_anchor(g):
    # NZDCHF: B and C silent -> {"live": false}; D live with no anchor to compare -> vs_anchor null;
    # AUDCAD on A: A has no such instance -> null
    nb = cell(g, "NZDCHF", "B")
    nc = cell(g, "NZDCHF", "C")
    nd = cell(g, "NZDCHF", "D")
    wd = live(8, (1.0, 1.0), (3.0, 3.0), (9.0, 9.0), None)
    ok = nb == {"live": False} and nc == {"live": False} and nd == wd and cell(g, "AUDCAD", "A") is None
    check("GT5", ok, f"NZDCHF B {nb}; C {nc}; D {nd}; AUDCAD A {cell(g, 'AUDCAD', 'A')}")


def gt6_zero_side_falls_back_and_order(g, books):
    # B AUDCHF add_pips_long 0.0 -> the base 4.0; rows in the books table's order
    a = cell(g, "AUDCHF", "B")
    wa = live(8, (1.0, 1.0), (4.0, 4.0), (10.0, 10.0), [])
    rows_g = [r["pair"] for r in (g or {}).get("rows", [])]
    rows_b = [r["pair"] for r in (books or {}).get("rows", [])]
    same = rows_g == rows_b and (g or {}).get("fleets") == (books or {}).get("fleets")
    check("GT6", a == wa and same, f"AUDCHF B {a}; order same as books {same}")


NODE = r"""
const src = require('fs').readFileSync(process.argv[2], 'utf8');
eval(src + '\n;global.geoHtml = geoHtml;');
const cells = [
  {live: true, cap: 8, width: [2.5, 2.5], add: [9, 9], exit: [10, 10], vs_anchor: []},
  {live: true, cap: 8, width: [1, 1], add: [2.5, 4], exit: [5, 5], vs_anchor: ['add_long', 'add_short']},
  {live: true, cap: 10, width: [2, 2], add: [8, 8], exit: [10, 10], vs_anchor: ['cap']},
  {live: true, cap: 8, width: [1, 1], add: [4, 4], exit: [11, 9], vs_anchor: ['exit_long']},
  {live: true, cap: 8, width: [5, 5], add: [6, 6], exit: [10, 10], vs_anchor: null},
];
console.log(JSON.stringify(cells.map(geoHtml)));
"""


def gt7_page():
    with open(os.path.join(ROOT, "templates", "dashboard.html"), encoding="utf-8") as f:
        t = f.read()
    fetch_fn = re.search(r"async function fetchFleetStrip\(\).*?\n  \}\n", t, re.S)
    body = fetch_fn.group(0) if fetch_fn else ""
    passes = "renderFleetGeometry(data && data.geometry)" in body and "renderFleetGeometry(null)" in body
    div = 'id="fleetGeometry"' in t
    title = '"tbl-title">geometry' in t
    css = ".g-diff" in t
    m = re.search(r"function geoHtml\(.*?\n  \}\n", t, re.S)
    got = None
    if m:
        helpers = re.search(r"function geoNum\(.*?\n  \}\n", t, re.S)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write((helpers.group(0) if helpers else "") + m.group(0))
            helper = f.name
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(NODE)
            harness = f.name
        try:
            out = subprocess.run(["node", harness, helper], capture_output=True, text=True, timeout=30)
            got = json.loads(out.stdout.strip().splitlines()[-1])
        except Exception as exc:  # noqa: BLE001
            got = f"node failed: {exc}"
    want = [
        "W2.5 A9 X10 c8",
        'W1 <span class="g-diff">A2.5/4</span> X5 c8',
        'W2 A8 X10 <span class="g-diff">c10</span>',
        'W1 A4 <span class="g-diff">X11/9</span> c8',
        "W5 A6 X10 c8",
    ]
    ok = passes and div and title and css and got == want
    check("GT7", ok, f"fetch passes geometry {passes}; div {div}; title {title}; css {css}; geoHtml {got}")


def gt8_earlier_tables():
    bad = []
    for s in ("verify_c113_fleet_books.py", "verify_c114_quote_gap.py", "verify_c115_quotes.py",
              "verify_c119_twins_retired.py"):
        out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", s)], capture_output=True, text=True)
        if out.returncode != 0:
            bad.append(s)
    check("GT8", not bad, f"failing: {bad or 'none'}")


def main():
    pipshed.r = fixture()
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets/1").get_json() or {}
    g = data.get("geometry")
    gt1_anchor_and_add_probe(g)
    gt2_sides_differ(g)
    gt3_ftmo_base_values(g)
    gt4_exit_probe_and_cap(g)
    gt5_not_live_absent_no_anchor(g)
    gt6_zero_side_falls_back_and_order(g, data.get("books"))
    gt7_page()
    gt8_earlier_tables()
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"verify_c129_geometry {passed}/{len(results)}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
