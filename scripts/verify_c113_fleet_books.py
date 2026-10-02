"""Verification: C113, the fleet books table under the fleet cards.

Operator 2 Oct 2026 (~19:40Z), after a hand-made table of open layers per
pair and fleet: "could we put it below the cards on pipshed.com? perhaps
with a subtle heatmap colour grading to show skewed books".

Rule (C113):
1. Server: the fleet strip response (`/api/g/<token>/fleets/...`) carries
   `books`, built from the SAME state reads as the cards (no new Redis
   reads, no new poll):
   - `fleets`: the strip's letters in order, placeholders left out;
   - `rows`: one per pair in order of first appearance across the
     strip's instance lists (A, B, C, D); a twin (`_ALT*` slot) is its own
     row, `PAIR*`;
   - each row's `cells[letter]`: null when that fleet has no such
     instance; `{"live": false}` when it is listed but not reporting;
     else `{"live": true, "long", "short", "net" = long - short, "mtm",
     "skew"}` with skew = net / cap (cap = the instance's max_layers,
     8 when absent), clamped to [-1, 1], 3 decimals;
   - `totals[letter]`: long, short, net, mtm (2 dp) and live count over the
     live cells only.
   Retired instances never appear (A lists its strip seven).
2. Page: `<div id="fleetBooks">` directly after the fleet strip, drawn by
   `renderFleetBooks(data.books)` from `fetchFleetStrip`, beside
   `renderFleetStrip` (no new setInterval or pollNoOverlap; renderFleetStrip
   stays a renderer of the cards only, which verify_fleet_strip_slots
   runs on its own); `bookHeat(skew)` tints a cell: clear at
   0, blue (long, --blue #2979ff) or amber (short, --amber #ffa000) with
   alpha 0.35 x |skew|; a caption explains the colours.

Tests first. Predicted at the tests-only commit: BK1-BK6 FAIL (no books);
BK7 is a guard (pollers stay 13) that passes in both states.

    python scripts/verify_c113_fleet_books.py
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
        self.lists = {}

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value, ex=None):
        self.kv[key] = value

    def mget(self, keys):
        return [self.kv.get(k) for k in keys]

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        n = len(items)
        s = start + n if start < 0 else start
        e = end + n if end < 0 else end
        return items[max(s, 0):e + 1] if e >= max(s, 0) else []

    def hgetall(self, key):
        return {}

    def hget(self, key, field):
        return None


def state(long_, short, mtm, max_layers=8):
    payload = {"_received_at": NOW, "open_layers_long": long_,
               "open_layers_short": short, "net_mtm": mtm, "halted": False,
               "account_login": 53066709, "account_balance": 10000.0,
               "account_equity": 9800.0}
    if max_layers is not None:
        payload["max_layers"] = max_layers
    return json.dumps(payload)


# B: the operator's 19:25Z snapshot, by hand (long, short, open MTM)
B_BOOK = {
    "GRIND_AUDCAD_OPTB": (3, 6, -17.24),
    "GRIND_AUDCHF_OPTB": (5, 6, -20.58),
    "GRIND_AUDNZD_ALTB": (1, 7, -12.04),
    "GRIND_AUDNZD_OPTB": (2, 7, -8.54),
    "GRIND_CADCHF_OPTB": (6, 7, -28.43),
    "GRIND_EURGBP_OPTB": (8, 1, -33.26),
    "GRIND_EURUSD_OPTB": (8, 3, -30.99),
    "GRIND_GBPUSD_OPTB": (3, 6, -17.69),
    "GRIND_NZDCAD_ALTB": (3, 5, -10.74),
    "GRIND_NZDCAD_OPTB": (2, 6, -10.92),
    "GRIND_NZDCHF_OPTB": (8, 6, -35.79),
}
# B totals by hand: long 3+5+1+2+6+8+8+3+3+2+8 = 49; short 6+6+7+7+7+1+3+6+5+6+6 = 60;
# net -11; mtm -17.24-20.58-12.04-8.54-28.43-33.26-30.99-17.69-10.74-10.92-35.79 = -226.22
B_TOTALS = {"long": 49, "short": 60, "net": -11, "mtm": -226.22, "live": 11}


def fixture():
    fake = FakeRedis()
    for inst, (l, s, m) in B_BOOK.items():
        fake.set(f"fxmatrix:state:{inst}", state(l, s, m))
    # A: the seven, simple values
    for k, inst in enumerate(pipshed.GRIND_A_STRIP_INSTANCES):
        fake.set(f"fxmatrix:state:{inst}", state(k, 7 - k, -1.0 * k))
    # C: every instance live except NZDCHF (not reporting)
    for inst in pipshed.GRIND_C_INSTANCES:
        if inst == "GRIND_NZDCHF_OPTC":
            continue
        fake.set(f"fxmatrix:state:{inst}", state(2, 2, -0.5))
    # D: EURGBP with cap 10 and a big long skew; EURUSD with no max_layers;
    # NZDCHF short-skewed beyond cap (clamp); the rest balanced
    for inst in pipshed.GRIND_D_INSTANCES:
        if inst == "GRIND_EURGBP_OPTD":
            fake.set(f"fxmatrix:state:{inst}", state(8, 0, -11.91, max_layers=10))
        elif inst == "GRIND_EURUSD_OPTD":
            fake.set(f"fxmatrix:state:{inst}", state(5, 4, -9.33, max_layers=None))
        elif inst == "GRIND_NZDCHF_OPTD":
            fake.set(f"fxmatrix:state:{inst}", state(0, 9, -3.0, max_layers=8))
        else:
            fake.set(f"fxmatrix:state:{inst}", state(1, 1, 0.0))
    return fake


results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")


def strip_books():
    pipshed.r = fixture()
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets/1").get_json()
    return data, (data or {}).get("books")


def bk1_shape_and_order(books):
    want_fleets = ["A", "B", "C", "D"]
    # first appearance across A's seven, then B's list order (hand-written)
    want_rows = ["GBPUSD", "EURUSD", "EURGBP", "AUDCHF", "CADCHF", "NZDCAD",
                 "AUDNZD", "AUDCAD", "NZDCHF", "AUDNZD*", "NZDCAD*"]
    if not books:
        check("BK1", False, "no books in the strip response")
        return
    rows = [r["pair"] for r in books.get("rows", [])]
    ok = books.get("fleets") == want_fleets and rows == want_rows
    check("BK1", ok, f"fleets {books.get('fleets')}; rows {rows}")


def _cell(books, pair, letter):
    for row in books.get("rows", []):
        if row["pair"] == pair:
            return row["cells"].get(letter, "MISSING")
    return "NO ROW"


def bk2_cells_by_hand(books):
    if not books:
        check("BK2", False, "no books")
        return
    want = {
        ("EURUSD", "B"): {"live": True, "long": 8, "short": 3, "net": 5, "mtm": -30.99, "skew": 0.625},
        ("NZDCAD*", "B"): {"live": True, "long": 3, "short": 5, "net": -2, "mtm": -10.74, "skew": -0.25},
        ("NZDCHF", "B"): {"live": True, "long": 8, "short": 6, "net": 2, "mtm": -35.79, "skew": 0.25},
        # cap 10: 8 / 10
        ("EURGBP", "D"): {"live": True, "long": 8, "short": 0, "net": 8, "mtm": -11.91, "skew": 0.8},
        # no max_layers: cap 8, 1 / 8
        ("EURUSD", "D"): {"live": True, "long": 5, "short": 4, "net": 1, "mtm": -9.33, "skew": 0.125},
        # -9 / 8 clamped
        ("NZDCHF", "D"): {"live": True, "long": 0, "short": 9, "net": -9, "mtm": -3.0, "skew": -1.0},
    }
    bad = [f"{k}: {_cell(books, *k)}" for k, v in want.items() if _cell(books, *k) != v]
    check("BK2", not bad, "; ".join(bad) if bad else "six cells as derived by hand")


def bk3_absent_and_not_live(books):
    if not books:
        check("BK3", False, "no books")
        return
    bad = []
    if _cell(books, "NZDCHF", "C") != {"live": False}:
        bad.append(f"C NZDCHF not reporting -> {_cell(books, 'NZDCHF', 'C')}")
    if _cell(books, "AUDCAD", "A") is not None:
        bad.append(f"A has no AUDCAD -> {_cell(books, 'AUDCAD', 'A')}")
    if _cell(books, "NZDCAD*", "A") is not None:
        bad.append(f"A has no twin -> {_cell(books, 'NZDCAD*', 'A')}")
    check("BK3", not bad, "; ".join(bad) if bad else "absent = null, not reporting = live false")


def bk4_totals(books):
    if not books:
        check("BK4", False, "no books")
        return
    t = books.get("totals", {})
    # C: 10 live of 11, each 2/2/-0.5 -> long 20, short 20, net 0, mtm -5.0
    want_c = {"long": 20, "short": 20, "net": 0, "mtm": -5.0, "live": 10}
    # A: k = 0..6, long k, short 7-k, mtm -k -> long 21, short 28, net -7, mtm -21.0
    want_a = {"long": 21, "short": 28, "net": -7, "mtm": -21.0, "live": 7}
    ok = t.get("B") == B_TOTALS and t.get("C") == want_c and t.get("A") == want_a
    check("BK4", ok, f"A {t.get('A')}; B {t.get('B')}; C {t.get('C')}")


def bk5_no_retired(data, books):
    if not books:
        check("BK5", False, "no books")
        return
    ids = json.dumps(books)
    leaked = [i for i in pipshed.GRIND_RETIRED_INSTANCES if i in ids]
    a_rows = [r["pair"] for r in books["rows"] if r["cells"].get("A") is not None]
    ok = not leaked and len(a_rows) == len(pipshed.GRIND_A_STRIP_INSTANCES)
    check("BK5", ok, f"retired ids in books {leaked}; A rows {len(a_rows)}")


def _template():
    with open(os.path.join(ROOT, "templates", "dashboard.html"), encoding="utf-8") as f:
        return f.read()


NODE = r"""
const src = require('fs').readFileSync(process.argv[2], 'utf8');
eval(src + '\n;global.bookHeat = bookHeat;');
console.log(JSON.stringify([bookHeat(0), bookHeat(1), bookHeat(-1), bookHeat(0.5),
  bookHeat(-0.4), bookHeat(null), bookHeat(undefined)]));
"""


def bk6_template(t):
    strip_at = t.find('<div id="fleetStrip"')
    books_at = t.find('<div id="fleetBooks"')
    between = t[strip_at:books_at] if 0 <= strip_at < books_at else ""
    placed = books_at > strip_at >= 0 and between.count("<div") == 1
    fetch_fn = re.search(r"async function fetchFleetStrip\(\).*?\n  \}\n", t, re.S)
    hooked = bool(fetch_fn) and fetch_fn.group(0).count("renderFleetBooks(") == 2
    strip_fn = re.search(r"function renderFleetStrip\(.*?\n  \}\n", t, re.S)
    hooked = hooked and bool(strip_fn) and "renderFleetBooks(" not in strip_fn.group(0)
    caption = re.search(r"fleetBooks.*?(blue|Blue).*?long.*?(amber|Amber).*?short", t, re.S) is not None
    m = re.search(r"function bookHeat\(.*?\n\s*\}\n", t, re.S)
    heat = None
    if m:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(m.group(0))
            helper = f.name
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(NODE)
            harness = f.name
        try:
            out = subprocess.run(["node", harness, helper], capture_output=True, text=True, timeout=30)
            heat = json.loads(out.stdout.strip().splitlines()[-1])
        except Exception as exc:  # noqa: BLE001
            heat = f"node failed: {exc}"
    # hand-derived: alpha = 0.35 x |skew|, 3 dp
    want_heat = ["transparent", "rgba(41,121,255,0.35)", "rgba(255,160,0,0.35)",
                 "rgba(41,121,255,0.175)", "rgba(255,160,0,0.14)", "transparent", "transparent"]
    ok = placed and hooked and caption and heat == want_heat
    check("BK6", ok, f"placed under the strip {placed}; drawn from fetchFleetStrip (ok and error paths) {hooked}; "
                     f"caption {caption}; bookHeat {heat}")


def bk7_no_new_poller(t):
    uses = len(re.findall(r"pollNoOverlap\(\s*fetch\w+\s*,\s*\d+\s*\)", t))
    bare = len(re.findall(r"setInterval\(\s*fetch\w+", t))
    check("BK7", uses == 13 and bare == 0, f"pollers {uses}, bare setInterval {bare}")


def main():
    data, books = strip_books()
    bk1_shape_and_order(books)
    bk2_cells_by_hand(books)
    bk3_absent_and_not_live(books)
    bk4_totals(books)
    bk5_no_retired(data, books)
    t = _template()
    bk6_template(t)
    bk7_no_new_poller(t)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"verify_c113_fleet_books {passed}/{len(results)}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
