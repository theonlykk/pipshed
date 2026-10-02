"""Verification: C114, the quote gap beside the fleet books table.

Operator 2 Oct 2026 (~19:56Z): "is it also possible to have a table next
to it that shows the distance in pips between the highest bid and the
lowest offer for each fx pair and each fleet. it gives an idea of how much
we have trapped the market before it trades."

Rule (C114):
1. Server: the fleet strip response carries `gaps`, from the cards the strip
   already built (no new reads): the same fleets and row order as `books`;
   a cell is null when the fleet has no such instance, {"live": false} when
   listed but not reporting, else {"live": true, "bid", "offer",
   "gap_pips"}: bid = the highest resting BUY_LIMIT in the instance's broker
   book (a long entry or a short exit), offer = the lowest resting
   SELL_LIMIT (a short entry or a long exit), gap = (offer - bid) / pip,
   1 dp, pip 0.01 for a JPY pair else 0.0001. Positions never count; a side
   with no limit order gives null there and a null gap. `means[letter]` =
   the mean gap over live cells with a gap (1 dp) and their count.
2. Page: drawn beside the books table inside #fleetBooks by
   renderFleetBooks(books, gaps) from fetchFleetStrip (still no new
   poller); gapHeat(gap): green rgba(0,200,83) at alpha
   0.35 x clamp(1 - gap / 20, 0, 1), clear at 20 pips or more or with no
   gap; the caption explains it.

Tests first. Predicted at the tests-only commit: QG1-QG5 FAIL; QG6 (the
C113 checks still pass) is a guard.

    python scripts/verify_c114_quote_gap.py
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


def order(kind, price):
    return {"type": kind, "price": price, "comment": "GRIND|OPT|L|L00|ENT", "ticket": 1}


def state(orders=None, positions=None):
    payload = {"_received_at": NOW, "open_layers_long": 1, "open_layers_short": 1,
               "net_mtm": -1.0, "max_layers": 8, "halted": False}
    if orders is not None or positions is not None:
        payload["book"] = {"orders": orders or [], "positions": positions or []}
    return json.dumps(payload)


def fixture():
    fake = FakeRedis()
    for inst in pipshed.GRIND_A_STRIP_INSTANCES:
        fake.set(f"fxmatrix:state:{inst}", state())
    for inst in pipshed.GRIND_B_INSTANCES:
        if inst == "GRIND_GBPUSD_OPTB":
            orders = [order("SELL_LIMIT", 1.32392), order("BUY_LIMIT", 1.32192),
                      order("BUY_LIMIT", 1.32206), order("SELL_LIMIT", 1.32406)]
            fake.set(f"fxmatrix:state:{inst}", state(orders))
        elif inst == "GRIND_EURUSD_OPTB":
            # a BUY position above the bid must not count
            fake.set(f"fxmatrix:state:{inst}", state(
                [order("BUY_LIMIT", 1.125), order("SELL_LIMIT", 1.1258)],
                [{"type": "BUY", "price": 1.127, "profit": -1.0}]))
        elif inst == "GRIND_EURGBP_OPTB":
            fake.set(f"fxmatrix:state:{inst}", state([order("BUY_LIMIT", 0.8501)]))
        else:
            fake.set(f"fxmatrix:state:{inst}", state())
    for inst in pipshed.GRIND_C_INSTANCES:
        if inst != "GRIND_NZDCHF_OPTC":
            fake.set(f"fxmatrix:state:{inst}", state())
    for inst in pipshed.GRIND_D_INSTANCES:
        fake.set(f"fxmatrix:state:{inst}", state())
    return fake


results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")


def strip():
    pipshed.r = fixture()
    return pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets/1").get_json() or {}


def cell(gaps, pair, letter):
    for row in (gaps or {}).get("rows", []):
        if row["pair"] == pair:
            return row["cells"].get(letter, "MISSING")
    return "NO ROW"


def qg1_gap_by_hand(gaps):
    want = {
        # bid = max(1.32206, 1.32192); offer = min(1.32392, 1.32406); 18.6 pips
        ("GBPUSD", "B"): {"live": True, "bid": 1.32206, "offer": 1.32392, "gap_pips": 18.6},
        # 1.12580 - 1.12500 = 8.0 pips; the BUY position at 1.127 is ignored
        ("EURUSD", "B"): {"live": True, "bid": 1.125, "offer": 1.1258, "gap_pips": 8.0},
    }
    bad = [f"{k}: {cell(gaps, *k)}" for k, v in want.items() if cell(gaps, *k) != v]
    check("QG1", gaps and not bad, "; ".join(bad) if bad else "two cells as derived by hand")


def qg2_one_sided_and_absent(gaps):
    want = {
        ("EURGBP", "B"): {"live": True, "bid": 0.8501, "offer": None, "gap_pips": None},
        ("AUDCHF", "B"): {"live": True, "bid": None, "offer": None, "gap_pips": None},
        ("NZDCHF", "C"): {"live": False},
        ("AUDCAD", "A"): None,
    }
    bad = [f"{k}: {cell(gaps, *k)}" for k, v in want.items() if cell(gaps, *k) != v]
    check("QG2", gaps and not bad, "; ".join(bad) if bad else "one-sided, no book, not live, absent")


def qg3_order_and_fleets(gaps, data):
    books = data.get("books") or {}
    ok = (gaps and gaps.get("fleets") == books.get("fleets")
          and [r["pair"] for r in gaps.get("rows", [])] == [r["pair"] for r in books.get("rows", [])])
    check("QG3", ok, "same fleets and row order as books" if ok else f"gaps fleets {gaps and gaps.get('fleets')}")


def qg4_means_and_jpy(gaps):
    m = (gaps or {}).get("means", {})
    # B: (18.6 + 8.0) / 2 = 13.3 over 2 cells; C, D: no gap anywhere
    ok_means = m.get("B") == {"gap_pips": 13.3, "n": 2} and m.get("C") == {"gap_pips": None, "n": 0}
    fn = getattr(pipshed, "_fleet_gap_cell", None)
    jpy = fn("USDJPY", {"connection": "live", "book": {"orders": [
        order("BUY_LIMIT", 147.12), order("SELL_LIMIT", 147.25)]}}) if fn else None
    ok_jpy = jpy == {"live": True, "bid": 147.12, "offer": 147.25, "gap_pips": 13.0}
    check("QG4", ok_means and ok_jpy, f"means B {m.get('B')} C {m.get('C')}; USDJPY {jpy}")


NODE = r"""
const src = require('fs').readFileSync(process.argv[2], 'utf8');
eval(src + '\n;global.gapHeat = gapHeat;');
console.log(JSON.stringify([gapHeat(0), gapHeat(4), gapHeat(10), gapHeat(16), gapHeat(20),
  gapHeat(25), gapHeat(-2), gapHeat(null), gapHeat(undefined)]));
"""


def qg5_page():
    with open(os.path.join(ROOT, "templates", "dashboard.html"), encoding="utf-8") as f:
        t = f.read()
    fetch_fn = re.search(r"async function fetchFleetStrip\(\).*?\n  \}\n", t, re.S)
    passes_gaps = bool(fetch_fn) and "renderFleetBooks(data && data.books, data && data.gaps)" in fetch_fn.group(0)
    caption = re.search(r"quote gap.*?highest.*?bid.*?lowest.*?offer", t, re.S | re.I) is not None
    m = re.search(r"function gapHeat\(.*?\n\s*\}\n", t, re.S)
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
    # by hand: 0.35 x (1 - g/20), clamped: 0 -> 0.35, 4 -> 0.28, 10 -> 0.175,
    # 16 -> 0.07, 20 and 25 -> clear, -2 -> 0.35 (clamp), no gap -> clear
    want = ["rgba(0,200,83,0.35)", "rgba(0,200,83,0.28)", "rgba(0,200,83,0.175)",
            "rgba(0,200,83,0.07)", "transparent", "transparent", "rgba(0,200,83,0.35)",
            "transparent", "transparent"]
    ok = passes_gaps and caption and heat == want
    check("QG5", ok, f"fetchFleetStrip passes gaps {passes_gaps}; caption {caption}; gapHeat {heat}")


def qg6_c113_still_passes():
    out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "verify_c113_fleet_books.py")],
                         capture_output=True, text=True)
    last = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr[-200:]
    check("QG6", out.returncode == 0, last)


def main():
    data = strip()
    gaps = data.get("gaps")
    qg1_gap_by_hand(gaps)
    qg2_one_sided_and_absent(gaps)
    qg3_order_and_fleets(gaps, data)
    qg4_means_and_jpy(gaps)
    qg5_page()
    qg6_c113_still_passes()
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"verify_c114_quote_gap {passed}/{len(results)}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
