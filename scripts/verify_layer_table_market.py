"""Verification for the instance card layer table: rows in trading-level order
and a market line (bid / ask derived from the heartbeat book), operator
30 Sep 2026.

Runs the dashboard's own JavaScript (functions extracted from
templates/dashboard.html) in node with hand-built fixtures.

Rules under test:
- Rows sort by the price that TRADES, descending: a layer by its exit
  target, a pending add / L0 by its order price. The Gap column is the gap
  between consecutive trading levels.
- A thin market row sits where the market is (mid if both prices are
  known, else the one known price): "bid X . ask Y".
- The price comes from the book: every position is 0.01 lot, so
  profit_usd = (bid - open) * 1000 * r for a long and (open - ask) * 1000 * r
  for a short. r = 1 when the quote currency is USD; otherwise r is fitted
  from the widest-spaced pair of positions on one side. No fit possible ->
  no market row (never a zero).

Expected values below are derived by hand in the comments.
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "templates", "dashboard.html")

FUNCTIONS = (
    "grindLayerPipSize",
    "grindSymbolFromInstanceId",
    "grindMarketFromBook",
    "renderGrindLayerTableHtml",
)


def extract_function(src, name):
    m = re.search(r"function " + re.escape(name) + r"\(", src)
    if not m:
        return None
    i = src.index("{", m.end())
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
    return None


def layer(idx, side, entry, exit_, covered=True):
    return {
        "layer_index": idx,
        "side": side,
        "entry_price": entry,
        "exit_target": exit_,
        "has_exit_order": covered,
        "has_exit_position": False,
    }


def pos(ptype, price, profit):
    return {"ticket": 1, "type": ptype, "price": price, "profit": profit}


# Fixture GBP: the operator's screenshot, 30 Sep ~22:54Z (GRIND_GBPUSD_OPT).
# Market chosen: bid 1.32601, ask 1.32609.
# Long profits (bid - open) * 1000:  L0 1.33047 -> -4.46, L1 1.32946 -> -3.45,
#   L2 1.32843 -> -2.42, L3 1.32744 -> -1.43, L4 1.32643 -> -0.42.
# Short profits (open - ask) * 1000: S5 1.32578 -> -0.31, S4 1.32479 -> -1.30,
#   S3 1.32374 -> -2.35.
GBP_CARD = {
    "instance_id": "GRIND_GBPUSD_OPT",
    "add_pending_long": 1.32543,
    "add_pending_short": 1.32679,
    "book": {"positions": [
        pos("BUY", 1.33047, -4.46), pos("BUY", 1.32946, -3.45),
        pos("BUY", 1.32843, -2.42), pos("BUY", 1.32744, -1.43),
        pos("BUY", 1.32643, -0.42),
        pos("SELL", 1.32578, -0.31), pos("SELL", 1.32479, -1.30),
        pos("SELL", 1.32374, -2.35),
    ], "orders": []},
}
GBP_LAYERS = [
    layer(0, "L", 1.33047, 1.33147, True),
    layer(1, "L", 1.32946, 1.33046, False),
    layer(2, "L", 1.32843, 1.32943, False),
    layer(3, "L", 1.32744, 1.32844, False),
    layer(4, "L", 1.32643, 1.32743, True),
    layer(5, "S", 1.32578, 1.32478, True),
    layer(4, "S", 1.32479, 1.32379, False),
    layer(3, "S", 1.32374, 1.32274, True),
]

# Fixture CAD: AUDCAD, quote CAD, true r = 0.72, bid 0.90123, ask 0.90140.
# Longs: 0.90400 -> (0.90123-0.90400)*720 = -1.9944 -> -1.99;
#        0.90340 -> -1.5624 -> -1.56; 0.90280 -> -1.1304 -> -1.13.
# Short: 0.90050 -> (0.90050-0.90140)*720 = -0.648 -> -0.65.
# Fit on the widest long pair (0.90400, 0.90280): r = (-1.13 - -1.99) / (0.0012*1000)
#   = 0.86 / 1.2 = 0.716667.
# bid = mean(open + profit / (1000 r)) = 0.901223 (each long gives 0.901223)
# ask = 0.90050 + 0.65 / 716.667 = 0.901407
CAD_CARD = {
    "instance_id": "GRIND_AUDCAD_OPTB",
    "book": {"positions": [
        pos("BUY", 0.90400, -1.99), pos("BUY", 0.90340, -1.56),
        pos("BUY", 0.90280, -1.13), pos("SELL", 0.90050, -0.65),
    ], "orders": []},
}
CAD_LAYERS = [
    layer(0, "L", 0.90400, 0.90500), layer(1, "L", 0.90340, 0.90440),
    layer(2, "L", 0.90280, 0.90380), layer(0, "S", 0.90050, 0.89950),
]

# Fixture ONE: a cross with a single position -> r cannot be fitted.
ONE_CARD = {
    "instance_id": "GRIND_NZDCHF_OPTC",
    "book": {"positions": [pos("BUY", 0.46200, -0.37)], "orders": []},
}
ONE_LAYERS = [layer(0, "L", 0.46200, 0.46300)]

# Fixture NOBOOK: no book at all.
NOBOOK_CARD = {"instance_id": "GRIND_EURUSD_OPT", "add_pending_long": 1.16950}
NOBOOK_LAYERS = [layer(0, "L", 1.17020, 1.17120), layer(1, "L", 1.16950, 1.17050)]

# Fixture LONGONLY: EURUSD longs only, bid 1.16880:
# 1.17020 -> -1.40, 1.16950 -> -0.70.  bid = 1.16880, ask unknown.
# Levels: exits 1.17120, 1.17050; pending add 1.16850 (below the bid).
LONG_CARD = {
    "instance_id": "GRIND_EURUSD_OPT",
    "add_pending_long": 1.16850,
    "book": {"positions": [pos("BUY", 1.17020, -1.40), pos("BUY", 1.16950, -0.70)],
             "orders": []},
}
LONG_LAYERS = [layer(0, "L", 1.17020, 1.17120), layer(1, "L", 1.16950, 1.17050)]


HARNESS = r"""
const out = {};
function rows(html) {
  const res = [];
  const re = /<tr([^>]*)>([\s\S]*?)<\/tr>/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    const attrs = m[1];
    const cells = [];
    const cre = /<t[dh][^>]*>([\s\S]*?)<\/t[dh]>/g;
    let c;
    while ((c = cre.exec(m[2])) !== null) cells.push(c[1]);
    res.push({ cls: attrs, cells: cells });
  }
  return res.slice(1);
}
function run(name, layers, card) {
  let html = null, market = null, err = null;
  try { html = renderGrindLayerTableHtml(layers, card); } catch (e) { err = String(e); }
  try { market = (typeof grindMarketFromBook === 'function') ? grindMarketFromBook(card) : 'MISSING'; }
  catch (e) { market = 'ERR ' + String(e); }
  out[name] = { rows: html ? rows(html) : null, market: market, err: err };
}
const F = __FIXTURES__;
for (const k of Object.keys(F)) run(k, F[k][0], F[k][1]);
console.log(JSON.stringify(out));
"""


def run_js():
    src = open(TEMPLATE, encoding="utf-8").read()
    parts = []
    missing = []
    for name in FUNCTIONS:
        body = extract_function(src, name)
        if body is None:
            missing.append(name)
        else:
            parts.append(body)
    fixtures = {
        "gbp": [GBP_LAYERS, GBP_CARD],
        "cad": [CAD_LAYERS, CAD_CARD],
        "one": [ONE_LAYERS, ONE_CARD],
        "nobook": [NOBOOK_LAYERS, NOBOOK_CARD],
        "longonly": [LONG_LAYERS, LONG_CARD],
    }
    js = "\n".join(parts) + "\n" + HARNESS.replace("__FIXTURES__", json.dumps(fixtures))
    res = subprocess.run(["node", "-e", js], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr)
    return json.loads(res.stdout.strip().splitlines()[-1]), missing


def market_rows(rows):
    return [r for r in rows if "grind-market-row" in r["cls"]]


def level_rows(rows):
    return [r for r in rows if "grind-market-row" not in r["cls"]]


def first_cells(rows):
    return ["MKT" if "grind-market-row" in r["cls"] else r["cells"][0] for r in rows]


def near(a, b, tol):
    return a is not None and abs(float(a) - b) <= tol


def check_lt1(res):
    rows = res["gbp"]["rows"]
    # trading levels desc: L0 exit 1.33147, L1 1.33046, L2 1.32943, L3 1.32844,
    # L4 1.32743, add S 1.32679, [mid 1.32605], add L 1.32543, S5 exit 1.32478,
    # S4 1.32379, S3 1.32274
    got = [r["cells"][0] for r in level_rows(rows)]
    want = ["0", "1", "2", "3", "4", "add", "add", "5", "4", "3"]
    if got != want:
        raise AssertionError(f"order {got} != {want}")
    return "rows in trading-level (exit / order price) order, descending"


def check_lt2(res):
    m = res["gbp"]["market"]
    if not isinstance(m, dict):
        raise AssertionError(f"grindMarketFromBook -> {m}")
    if not (near(m.get("bid"), 1.32601, 0.000005) and near(m.get("ask"), 1.32609, 0.000005)):
        raise AssertionError(f"USD pair bid/ask {m}")
    return "USD-quoted pair: bid 1.32601 / ask 1.32609 exact from the book"


def check_lt3(res):
    m = res["cad"]["market"]
    if not isinstance(m, dict):
        raise AssertionError(f"grindMarketFromBook -> {m}")
    # hand-derived 0.901223 / 0.901407; within 0.3 pip of the true 0.90123 / 0.90140
    if not (near(m.get("bid"), 0.901223, 0.000002) and near(m.get("ask"), 0.901407, 0.000002)):
        raise AssertionError(f"cross bid/ask {m}")
    rows = res["cad"]["rows"]
    mk = market_rows(rows)
    if len(mk) != 1 or "0.90122" not in mk[0]["cells"][0] or "0.90141" not in mk[0]["cells"][0]:
        raise AssertionError(f"cross market row {mk}")
    return "cross: rate fitted from the widest long pair, bid 0.90122 / ask 0.90141"


def check_lt4(res):
    # guard: one position on a cross cannot fit r -> no market row, no zeros
    rows = res["one"]["rows"]
    if rows is None or market_rows(rows):
        raise AssertionError(f"single-position cross must have no market row: {rows}")
    m = res["one"]["market"]
    if isinstance(m, dict) and (m.get("bid") not in (None,) or m.get("ask") not in (None,)):
        raise AssertionError(f"market must be null, got {m}")
    return "single-position cross: no market row, nulls (guard)"


def check_lt5(res):
    # guard: no book -> table renders, no market row
    rows = res["nobook"]["rows"]
    if not rows or market_rows(rows):
        raise AssertionError(f"no-book table {rows}")
    return "no book: table renders without a market row (guard)"


def check_lt6(res):
    rows = res["gbp"]["rows"]
    got = first_cells(rows)
    want = ["0", "1", "2", "3", "4", "add", "MKT", "add", "5", "4", "3"]
    if got != want:
        raise AssertionError(f"market row position {got}")
    txt = market_rows(rows)[0]["cells"][0]
    if "bid 1.32601" not in txt or "ask 1.32609" not in txt:
        raise AssertionError(f"market text {txt!r}")
    return "market row between add S 1.32679 and add L 1.32543, text 'bid 1.32601 . ask 1.32609'"


def check_lt7(res):
    rows = level_rows(res["gbp"]["rows"])
    gaps = [r["cells"][3] for r in rows]
    # 1.33147-1.33046=10.1, 1.33046-1.32943=10.3, -1.32844=9.9, -1.32743=10.1,
    # -1.32679=6.4, -1.32543=13.6 (across the market row), -1.32478=6.5,
    # -1.32379=9.9, -1.32274=10.5
    want = ["", "10.1", "10.3", "9.9", "10.1", "6.4", "13.6", "6.5", "9.9", "10.5"]
    if gaps != want:
        raise AssertionError(f"gaps {gaps} != {want}")
    return "Gap = pips between consecutive trading levels"


def check_lt8(res):
    rows = res["longonly"]["rows"]
    # levels 1.17120, 1.17050, [bid 1.16880], add 1.16850
    got = first_cells(rows)
    if got != ["0", "1", "MKT", "add"]:
        raise AssertionError(f"long-only order {got}")
    txt = market_rows(rows)[0]["cells"][0]
    if "bid 1.16880" not in txt or "ask —" not in txt:
        raise AssertionError(f"long-only text {txt!r}")
    return "longs only: market row placed by the bid, ask shown as a dash"


CHECKS = [
    ("LT1", check_lt1), ("LT2", check_lt2), ("LT3", check_lt3), ("LT4", check_lt4),
    ("LT5", check_lt5), ("LT6", check_lt6), ("LT7", check_lt7), ("LT8", check_lt8),
]


def main():
    res, missing = run_js()
    if missing:
        print("functions missing from the template:", ", ".join(missing))
    failed = 0
    for name, fn in CHECKS:
        try:
            print(f"PASS {name} {fn(res)}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name} {exc}")
    print(f"{len(CHECKS) - failed}/{len(CHECKS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
