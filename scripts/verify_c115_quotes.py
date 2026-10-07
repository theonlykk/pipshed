"""Verification: C115, our best bid and offer per pair and fleet, with the
lattice's virtual level where a side has no real order.

Operator 2 Oct 2026 (~20:08Z), after the C114 quote gap showed EURGBP on D
one-sided at 8/0: "a virtual buy limit in italics is a nice idea ... can we
have one more table that shows the actual limit order prices? maybe a
colour to indicate if it is add or exit?"

Rule (C115):
1. FLEET_STRIP entries carry "lattice" (B, C, D: True, the ADR-162 lattice
   live since C63 / D0; A: False, cycle 3 runs ADR-157 ejection).
2. The strip response carries `quotes` (same fleets and row order as
   `books`), from the reads the strip already makes. A live cell:
   - bid / bid_kind: the highest resting BUY_LIMIT and "exit" or "entry"
     from its comment (`...|EXT` / `...|ENT`); offer / offer_kind: the
     lowest resting SELL_LIMIT, likewise; null when that side has none;
   - rolls_left_long / rolls_left_short: on a lattice fleet with the side at
     cap (layers >= max_layers), the number of its layers WITHOUT a
     virtual_level in the heartbeat (unrolled); else null;
   - virtual_bid: only when bid is null and the long side is at cap on a
     lattice fleet with rolls_left_long > 0: the long side's next level =
     min(effective entry) - add, effective = virtual_level if present else
     entry_price; virtual_offer likewise for the short side = max + add;
     rounded to the pair's digits (3 for JPY, else 5);
   - virtual_gap_pips: (offer or virtual_offer - bid or virtual_bid) / pip,
     1 dp, only when a virtual level was used and both sides exist.
   Not reporting = {"live": false}; absent = null.
3. Page: a third table "best bid / offer" beside the other two, drawn by
   renderFleetBooks(books, gaps, quotes) from fetchFleetStrip;
   quoteSpan(price, kind, digits): exit -> <span class="q-exit">,
   entry -> <span class="q-entry">, virtual -> <span class="q-virtual">~...;
   the gap table shows virtual_gap_pips in italics (class q-virtual) where
   the real gap is null.

Tests first. Predicted at the tests-only commit: QT1-QT6 FAIL; QT7 (C113
and C114 still pass) is a guard.

    python scripts/verify_c115_quotes.py
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


def o(kind, price, comment):
    return {"type": kind, "price": price, "comment": comment, "ticket": 1}


def lay(side, idx, entry, vl=None):
    d = {"layer_index": idx, "side": side, "entry_price": entry, "exit_target": entry,
         "has_exit_order": False, "has_exit_position": False, "comment": None}
    if vl is not None:
        d["virtual_level"] = vl
    return d


def state(orders, layers=(), add=3.0, long_n=1, short_n=1, max_layers=8):
    return json.dumps({
        "_received_at": NOW, "open_layers_long": long_n, "open_layers_short": short_n,
        "net_mtm": -1.0, "max_layers": max_layers, "add_pips": add, "halted": False,
        "book": {"orders": orders, "positions": []}, "layers": list(layers)})


# D EURGBP: 8 long (L0..L7 at 0.8540 down by 3 pips), the three oldest rolled
# to 0.8516 / 0.8513 / 0.8510; short flat; only sells resting.
EURGBP_LONG = [lay("L", i, round(0.8540 - 0.0003 * i, 5)) for i in range(8)]
for i, vl in enumerate((0.8516, 0.8513, 0.8510)):
    EURGBP_LONG[i]["virtual_level"] = vl
# D NZDCHF: 8 long, every one rolled
NZDCHF_LONG = [lay("L", i, round(0.4700 - 0.0003 * i, 5), vl=round(0.4650 - 0.0003 * i, 5))
               for i in range(8)]
# C CADCHF: 8 short (0.5800 up by 3 pips), L0 rolled to 0.5827; long flat
CADCHF_SHORT = [lay("S", i, round(0.5800 + 0.0003 * i, 5)) for i in range(8)]
CADCHF_SHORT[0]["virtual_level"] = 0.5827
# D AUDCHF: 8 long, two rolled, AND a real bid (a short exit): no virtual
AUDCHF_LONG = [lay("L", i, round(0.5790 - 0.0004 * i, 5)) for i in range(8)]
AUDCHF_LONG[0]["virtual_level"] = 0.5755
AUDCHF_LONG[1]["virtual_level"] = 0.5751
# B NZDCHF: 5 long, below cap, no bid: no rolls count, no virtual
NZDCHF_B_LONG = [lay("L", i, round(0.4700 - 0.0003 * i, 5)) for i in range(5)]
# A EURGBP: 8 long, no lattice on A
A_EURGBP_LONG = [lay("L", i, round(0.8540 - 0.0003 * i, 5)) for i in range(8)]


def fixture():
    fake = FakeRedis()
    plain = state([o("BUY_LIMIT", 1.0, "GRIND|OPT|L|L00|ENT"), o("SELL_LIMIT", 1.001, "GRIND|OPT|S|L00|ENT")])
    for inst in pipshed.GRIND_A_STRIP_INSTANCES:
        if inst == "GRIND_EURGBP_OPT":
            fake.set(f"fxmatrix:state:{inst}", state(
                [o("SELL_LIMIT", 0.8521, "GRIND|OPT|S|L00|ENT")], A_EURGBP_LONG, long_n=8, short_n=0))
        else:
            fake.set(f"fxmatrix:state:{inst}", plain)
    for inst in pipshed.GRIND_B_INSTANCES:
        if inst == "GRIND_NZDCHF_OPTB":
            fake.set(f"fxmatrix:state:{inst}", state(
                [o("SELL_LIMIT", 0.4705, "GRIND|OPT|S|L00|ENT")], NZDCHF_B_LONG, long_n=5, short_n=0))
        elif inst == "GRIND_GBPUSD_OPTB":
            fake.set(f"fxmatrix:state:{inst}", state(
                [o("BUY_LIMIT", 1.32206, "GRIND|OPT|S|L03|EXT"), o("BUY_LIMIT", 1.32192, "GRIND|OPT|L|L02|ENT"),
                 o("SELL_LIMIT", 1.32392, "GRIND|OPT|S|L04|ENT"), o("SELL_LIMIT", 1.32406, "GRIND|OPT|L|L02|EXT")],
                add=9.0, long_n=3, short_n=4))
        else:
            fake.set(f"fxmatrix:state:{inst}", plain)
    for inst in pipshed.GRIND_C_INSTANCES:
        if inst == "GRIND_NZDCHF_OPTC":
            continue
        if inst == "GRIND_CADCHF_OPTC":
            fake.set(f"fxmatrix:state:{inst}", state(
                [o("BUY_LIMIT", 0.5795, "GRIND|OPT|S|L01|EXT")], CADCHF_SHORT, long_n=0, short_n=8))
        else:
            fake.set(f"fxmatrix:state:{inst}", plain)
    for inst in pipshed.GRIND_D_INSTANCES:
        if inst == "GRIND_EURGBP_OPTD":
            fake.set(f"fxmatrix:state:{inst}", state(
                [o("SELL_LIMIT", 0.8526, "GRIND|OPT|L|L03|EXT"), o("SELL_LIMIT", 0.8521, "GRIND|OPT|S|L00|ENT")],
                EURGBP_LONG, long_n=8, short_n=0))
        elif inst == "GRIND_AUDCHF_OPTD":
            fake.set(f"fxmatrix:state:{inst}", state(
                [o("BUY_LIMIT", 0.5740, "GRIND|OPT|S|L02|EXT"), o("SELL_LIMIT", 0.5770, "GRIND|OPT|L|L07|EXT")],
                AUDCHF_LONG, add=4.0, long_n=8, short_n=3))
        elif inst == "GRIND_NZDCHF_OPTD":
            fake.set(f"fxmatrix:state:{inst}", state(
                [o("SELL_LIMIT", 0.4660, "GRIND|OPT|L|L00|EXT")], NZDCHF_LONG, long_n=8, short_n=0))
        else:
            fake.set(f"fxmatrix:state:{inst}", plain)
    return fake


results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")


def cell(q, pair, letter):
    for row in (q or {}).get("rows", []):
        if row["pair"] == pair:
            return row["cells"].get(letter, "MISSING")
    return "NO ROW"


BASE = {"live": True, "bid": None, "bid_kind": None, "offer": None, "offer_kind": None,
        "rolls_left_long": None, "rolls_left_short": None, "virtual_bid": None,
        "virtual_offer": None, "virtual_gap_pips": None}


def want(**kw):
    d = dict(BASE)
    d.update(kw)
    return d


def qt1_real_both_sides(q):
    w = want(bid=1.32206, bid_kind="exit", offer=1.32392, offer_kind="entry")
    got = cell(q, "GBPUSD", "B")
    check("QT1", got == w, f"GBPUSD B {got}")


def qt2_virtual_bid(q):
    # min effective = min(0.8516, 0.8513, 0.8510, 0.8531, 0.8528, 0.8525, 0.8522, 0.8519) = 0.8510;
    # virtual bid = 0.8510 - 3 pips = 0.8507; rolls left = 8 - 3 = 5; gap (0.8521 - 0.8507) = 14.0
    w = want(offer=0.8521, offer_kind="entry", rolls_left_long=5, virtual_bid=0.8507, virtual_gap_pips=14.0)
    got = cell(q, "EURGBP", "D")
    check("QT2", got == w, f"EURGBP D {got}")


def qt3_no_roll_left(q):
    w = want(offer=0.466, offer_kind="exit", rolls_left_long=0)
    got = cell(q, "NZDCHF", "D")
    check("QT3", got == w, f"NZDCHF D (all rolled) {got}")


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


def qt5_virtual_offer(q):
    # max effective = max(0.5827, 0.5803 .. 0.5821) = 0.5827; + 3 pips = 0.5830; rolls left 7;
    # gap (0.5830 - 0.5795) = 35.0
    w = want(bid=0.5795, bid_kind="exit", rolls_left_short=7, virtual_offer=0.583, virtual_gap_pips=35.0)
    got = cell(q, "CADCHF", "C")
    nl = cell(q, "NZDCHF", "C")
    ok = got == w and nl == {"live": False} and cell(q, "AUDCAD", "A") is None
    check("QT5", ok, f"CADCHF C {got}; NZDCHF C {nl}")


def qt8_virtual_only_where_it_belongs(q):
    """Added after the mutation round (two rules survived): a capped lattice
    side WITH a real bid shows no virtual level (rolls still counted); a
    lattice side below cap counts no rolls and shows no virtual level."""
    a = cell(q, "AUDCHF", "D")
    n = cell(q, "NZDCHF", "B")
    wa = want(bid=0.574, bid_kind="exit", offer=0.577, offer_kind="exit", rolls_left_long=6)
    wn = want(offer=0.4705, offer_kind="entry")
    check("QT8", a == wa and n == wn, f"AUDCHF D {a}; NZDCHF B {n}")


NODE = r"""
const src = require('fs').readFileSync(process.argv[2], 'utf8');
eval(src + '\n;global.quoteSpan = quoteSpan;');
console.log(JSON.stringify([quoteSpan(1.32391, 'exit', 5), quoteSpan(0.8521, 'entry', 5),
  quoteSpan(0.8507, 'virtual', 5), quoteSpan(147.12, 'exit', 3), quoteSpan(null, 'exit', 5)]));
"""


def qt6_page():
    with open(os.path.join(ROOT, "templates", "dashboard.html"), encoding="utf-8") as f:
        t = f.read()
    fetch_fn = re.search(r"async function fetchFleetStrip\(\).*?\n  \}\n", t, re.S)
    passes = bool(fetch_fn) and "renderFleetBooks(data && data.books, data && data.gaps, data && data.quotes)" in fetch_fn.group(0)
    title = "best bid / offer" in t
    css = all(c in t for c in (".q-exit", ".q-entry", ".q-virtual"))
    italic_gap = re.search(r"virtual_gap_pips.*?q-virtual", t, re.S) is not None
    m = re.search(r"function quoteSpan\(.*?\n\s*\}\n", t, re.S)
    got = None
    if m:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(m.group(0))
            helper = f.name
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(NODE)
            harness = f.name
        try:
            out = subprocess.run(["node", harness, helper], capture_output=True, text=True, timeout=30)
            got = json.loads(out.stdout.strip().splitlines()[-1])
        except Exception as exc:  # noqa: BLE001
            got = f"node failed: {exc}"
    want_spans = ['<span class="q-exit">1.32391</span>', '<span class="q-entry">0.85210</span>',
                  '<span class="q-virtual">~0.85070</span>', '<span class="q-exit">147.120</span>', '']
    ok = passes and title and css and italic_gap and got == want_spans
    check("QT6", ok, f"passes quotes {passes}; title {title}; css {css}; virtual gap italic {italic_gap}; quoteSpan {got}")


def qt7_earlier_tables():
    bad = []
    for s in ("verify_c113_fleet_books.py", "verify_c114_quote_gap.py"):
        out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", s)], capture_output=True, text=True)
        if out.returncode != 0:
            bad.append(s)
    check("QT7", not bad, f"failing: {bad or 'none'}")


def main():
    pipshed.r = fixture()
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets/1").get_json() or {}
    q = data.get("quotes")
    lattice = {e["letter"]: e.get("lattice") for e in pipshed.FLEET_STRIP}
    if lattice != {"A": True, "B": True, "C": True, "D": True}:
        print(f"NOTE lattice flags {lattice}")
    qt1_real_both_sides(q)
    qt2_virtual_bid(q)
    qt3_no_roll_left(q)
    qt4_no_lattice_on_a(q)
    qt5_virtual_offer(q)
    qt6_page()
    qt7_earlier_tables()
    qt8_virtual_only_where_it_belongs(q)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"verify_c115_quotes {passed}/{len(results)}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
