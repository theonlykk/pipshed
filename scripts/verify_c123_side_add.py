"""Verification: C123, the lattice's next level uses EACH SIDE'S OWN add.

fxmatrix backlog C123 (HANDOFF s52, 4 Oct 2026): round 2's presets may give
a pair different adds per side (scripts/ic_presets.py writes InpAddPipsLong /
InpAddPipsShort when the sides differ). The heartbeat already carries both
(`add_pips_long`, `add_pips_short`: fxgrind.mq5 Grind_BuildHeartbeatJson),
and its plain `add_pips` is the LONG side's resolved add (g_geo_add_long). C115
priced both sides' next level from `add_pips`, so a short side whose add
differs showed the wrong italic level and virtual gap.

Rule (C123): in `_fleet_quote_cell`, a side's add = the heartbeat's
`add_pips_long` (long) / `add_pips_short` (short) when it is a number > 0
(not a bool); otherwise the heartbeat's `add_pips` (as C115). Nothing else in
C115 changes.

Tests first. Predicted at the tests-only commit: SA1 and SA2 FAIL (the side's
own add ignored); SA3, SA4 and SA5 are guards (fallback, invalid per-side
values, C115 unchanged).

    python scripts/verify_c123_side_add.py
"""
import json
import os
import subprocess
import sys
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


def state(orders, layers=(), add=3.0, long_n=1, short_n=1, max_layers=8, extra=None):
    d = {"_received_at": NOW, "open_layers_long": long_n, "open_layers_short": short_n,
         "net_mtm": -1.0, "max_layers": max_layers, "add_pips": add, "halted": False,
         "book": {"orders": orders, "positions": []}, "layers": list(layers)}
    d.update(extra or {})
    return json.dumps(d)


# The C115 fixtures, reused: D EURGBP 8 long (0.8540 down by 3), three rolled to
# 0.8516 / 0.8513 / 0.8510, only sells resting; C CADCHF 8 short (0.5800 up by 3),
# L0 rolled to 0.5827, only a buy (a short exit) resting.
EURGBP_LONG = [lay("L", i, round(0.8540 - 0.0003 * i, 5)) for i in range(8)]
for i, vl in enumerate((0.8516, 0.8513, 0.8510)):
    EURGBP_LONG[i]["virtual_level"] = vl
CADCHF_SHORT = [lay("S", i, round(0.5800 + 0.0003 * i, 5)) for i in range(8)]
CADCHF_SHORT[0]["virtual_level"] = 0.5827
# B CADCHF and B EURGBP: the same books, per-side fields invalid (fallback)
# D AUDCAD: 8 short, none rolled, heartbeat WITHOUT per-side fields
AUDCAD_SHORT = [lay("S", i, round(0.9900 + 0.0006 * i, 5)) for i in range(8)]


def fixture():
    fake = FakeRedis()
    plain = state([o("BUY_LIMIT", 1.0, "GRIND|OPT|L|L00|ENT"), o("SELL_LIMIT", 1.001, "GRIND|OPT|S|L00|ENT")])
    for inst in pipshed.GRIND_A_STRIP_INSTANCES:
        fake.set(f"fxmatrix:state:{inst}", plain)
    for inst in pipshed.GRIND_B_INSTANCES:
        if inst == "GRIND_CADCHF_OPTB":
            fake.set(f"fxmatrix:state:{inst}", state(
                [o("BUY_LIMIT", 0.5795, "GRIND|OPT|S|L01|EXT")], CADCHF_SHORT, long_n=0, short_n=8,
                extra={"add_pips_long": 3.0, "add_pips_short": -1.0}))
        elif inst == "GRIND_EURGBP_OPTB":
            fake.set(f"fxmatrix:state:{inst}", state(
                [o("SELL_LIMIT", 0.8521, "GRIND|OPT|S|L00|ENT")], EURGBP_LONG, long_n=8, short_n=0,
                extra={"add_pips_long": True, "add_pips_short": None}))
        else:
            fake.set(f"fxmatrix:state:{inst}", plain)
    for inst in pipshed.GRIND_C_INSTANCES:
        if inst == "GRIND_CADCHF_OPTC":
            fake.set(f"fxmatrix:state:{inst}", state(
                [o("BUY_LIMIT", 0.5795, "GRIND|OPT|S|L01|EXT")], CADCHF_SHORT, add=3.0, long_n=0, short_n=8,
                extra={"add_pips_long": 3.0, "add_pips_short": 5.0}))
        else:
            fake.set(f"fxmatrix:state:{inst}", plain)
    for inst in pipshed.GRIND_D_INSTANCES:
        if inst == "GRIND_EURGBP_OPTD":
            fake.set(f"fxmatrix:state:{inst}", state(
                [o("SELL_LIMIT", 0.8521, "GRIND|OPT|S|L00|ENT")], EURGBP_LONG, add=3.0, long_n=8, short_n=0,
                extra={"add_pips_long": 4.0, "add_pips_short": 3.0}))
        elif inst == "GRIND_AUDCAD_OPTD":
            fake.set(f"fxmatrix:state:{inst}", state(
                [o("BUY_LIMIT", 0.9890, "GRIND|OPT|S|L01|EXT")], AUDCAD_SHORT, add=6.0, long_n=0, short_n=8))
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


def sa1_short_uses_its_own_add(q):
    # C CADCHF: add_pips 3.0 (= the long side's), add_pips_short 5.0.
    # max effective = 0.5827 (the rolled L0); + 5 pips = 0.5832; rolls left 7;
    # gap (0.5832 - 0.5795) / 0.0001 = 37.0. (C115 gave 0.5830 / 35.0.)
    w = want(bid=0.5795, bid_kind="exit", rolls_left_short=7, virtual_offer=0.5832, virtual_gap_pips=37.0)
    got = cell(q, "CADCHF", "C")
    check("SA1", got == w, f"CADCHF C {got}")


def sa2_long_uses_its_own_add(q):
    # D EURGBP: add_pips 3.0, add_pips_long 4.0. min effective 0.8510 - 4 pips = 0.8506;
    # rolls left 5; gap (0.8521 - 0.8506) = 15.0. (C115 gave 0.8507 / 14.0.)
    w = want(offer=0.8521, offer_kind="entry", rolls_left_long=5, virtual_bid=0.8506, virtual_gap_pips=15.0)
    got = cell(q, "EURGBP", "D")
    check("SA2", got == w, f"EURGBP D {got}")


def sa3_fallback_without_side_fields(q):
    """GUARD: a heartbeat without the per-side fields prices from add_pips.
    D AUDCAD: 8 short, none rolled, max entry 0.9942 + 6 pips = 0.9948;
    rolls left 8; gap (0.9948 - 0.9890) = 58.0."""
    w = want(bid=0.989, bid_kind="exit", rolls_left_short=8, virtual_offer=0.9948, virtual_gap_pips=58.0)
    got = cell(q, "AUDCAD", "D")
    check("SA3", got == w, f"AUDCAD D {got}")


def sa4_invalid_side_values_fall_back(q):
    """GUARD: a per-side value of -1, true or null is not an add: add_pips decides.
    B CADCHF (short -1.0) -> 0.5830 / 35.0 as C115; B EURGBP (long true) -> 0.8507 / 14.0."""
    wc = want(bid=0.5795, bid_kind="exit", rolls_left_short=7, virtual_offer=0.583, virtual_gap_pips=35.0)
    we = want(offer=0.8521, offer_kind="entry", rolls_left_long=5, virtual_bid=0.8507, virtual_gap_pips=14.0)
    c, e = cell(q, "CADCHF", "B"), cell(q, "EURGBP", "B")
    check("SA4", c == wc and e == we, f"CADCHF B {c}; EURGBP B {e}")


def sa5_c115_unchanged():
    """GUARD: the C115 suite (no per-side fields in its fixture) still passes."""
    out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "verify_c115_quotes.py")],
                         capture_output=True, text=True)
    check("SA5", out.returncode == 0, out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr[-200:])


def main():
    pipshed.r = fixture()
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets/1").get_json() or {}
    q = data.get("quotes")
    sa1_short_uses_its_own_add(q)
    sa2_long_uses_its_own_add(q)
    sa3_fallback_without_side_fields(q)
    sa4_invalid_side_values_fall_back(q)
    sa5_c115_unchanged()
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"verify_c123_side_add {passed}/{len(results)}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
