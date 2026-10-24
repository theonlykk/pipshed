"""Verification: C119, the IC twins retire (fxmatrix monday-build-2026-10-05,
backlog C96; operator 3 Oct: one instance per pair from compass round 2).

At the Monday build (5 Oct after 22:00Z) the six IC twins are removed by
hand: GRIND_AUDNZD_ALT{B,C,D} and GRIND_NZDCAD_ALT{B,C,D}. pipshed then:
1. lists them in GRIND_RETIRED_INSTANCES (their critical rows read
   "resolved: instance retired", C108), beside cycle 3's four;
2. strips B, C and D to their nine _OPT instances in FLEET_STRIP (cards,
   counts, books / gap / quote tables: no "AUDNZD*" or "NZDCAD*" row), as
   A's strip did in C107;
3. keeps the full eleven-id lists for each fleet's own page (a retired
   tile says CONNECTION LOST, which is true), unchanged.

Deployed AFTER the twins are removed, never before.

Tests first. Predicted at the tests-only commit: TR1-TR5 FAIL; TR6 (the
full lists are unchanged) is a guard.

    python scripts/verify_c119_twins_retired.py
"""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "verify_fleet_strip_helpers_c119", os.path.join(ROOT, "scripts", "verify_fleet_strip.py"))
fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fs)

TOKEN = fs.TOKEN
TWINS = {f"GRIND_{p}_ALT{f}" for p in ("AUDNZD", "NZDCAD") for f in "BCD"}
CYCLE3 = {"GRIND_AUDNZD_ALT", "GRIND_NZDCAD_ALT", "GRIND_AUDCAD_OPT", "GRIND_NZDCHF_OPT"}
TWOARM = {
    "GRIND_NZDCHF_OPTD", "GRIND_NZDCAD_OPTD", "GRIND_AUDNZD_OPTD",
    "GRIND_GBPUSD_OPTC", "GRIND_EURGBP_OPTC", "GRIND_AUDCHF_OPTC",
    "GRIND_CADCHF_OPTC", "GRIND_NZDCHF_OPTC", "GRIND_NZDCAD_OPTC", "GRIND_AUDNZD_OPTC",
}
PAIRS = ["GBPUSD", "EURUSD", "EURGBP", "AUDCAD", "AUDCHF", "CADCHF", "NZDCHF", "NZDCAD", "AUDNZD"]
LOGIN = {"B": 53066709, "C": 53071896, "D": 53077984}
STRIP_B = [f"GRIND_{p}_OPTB" for p in PAIRS]
STRIP_C = [
    "GRIND_EURUSD_OPTC", "GRIND_AUDCAD_OPTC", "GRIND_EURUSD_ALTC", "GRIND_AUDCAD_ALTC",
    "GRIND_GBPCHF_OPTC", "GRIND_GBPCHF_ALTC",
]
STRIP_D = [
    "GRIND_GBPUSD_OPTD", "GRIND_EURUSD_OPTD", "GRIND_EURGBP_OPTD", "GRIND_AUDCAD_OPTD",
    "GRIND_AUDCHF_OPTD", "GRIND_CADCHF_OPTD", "GRIND_GBPUSD_ALTD", "GRIND_EURUSD_ALTD",
    "GRIND_EURGBP_ALTD", "GRIND_AUDCAD_ALTD", "GRIND_AUDCHF_ALTD", "GRIND_CADCHF_ALTD",
]
STRIPS = {"B": STRIP_B, "C": STRIP_C, "D": STRIP_D}
STRIP_COUNTS = {"B": 9, "C": 6, "D": 12}
BOOK_ROWS = [
    # C158: A retired; first appearance across B's nine, then C, D, E (by hand)
    "GBPUSD", "EURUSD", "EURGBP", "AUDCAD", "AUDCHF", "CADCHF", "NZDCHF", "NZDCAD", "AUDNZD",
    "EURUSD*", "AUDCAD*", "GBPCHF", "GBPCHF*", "GBPUSD*", "EURGBP*", "AUDCHF*", "CADCHF*",
]


def _strip(fake):
    import app as pipshed

    pipshed.r = fake
    return pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json()


def _fake_all_ic(include_twins):
    fake = fs.FakeRedis()
    for letter in "BCD":
        for inst in STRIPS[letter]:
            fake.set(f"fxmatrix:state:{inst}", fs.HB(30, account_login=LOGIN[letter]))
        if include_twins:
            for p in ("AUDNZD", "NZDCAD"):
                fake.set(f"fxmatrix:state:GRIND_{p}_ALT{letter}", fs.HB(30, account_login=LOGIN[letter]))
    return fake


def check_tr1():
    import app as pipshed

    got = set(pipshed.GRIND_RETIRED_INSTANCES)
    if got != CYCLE3 | TWINS | TWOARM:
        raise AssertionError(f"retired must be cycle 3 + twins + two-arm ten, got {sorted(got)}")
    return "GRIND_RETIRED_INSTANCES = 20"


def check_tr2():
    import app as pipshed

    for entry in pipshed.FLEET_STRIP:
        if entry["letter"] in STRIPS:
            if list(entry["instances"]) != STRIPS[entry["letter"]]:
                raise AssertionError(f"{entry['letter']} strip mismatch: {entry['instances']}")
    return "B, C, D strips match two-arm lists"


def check_tr3():
    data = _strip(_fake_all_ic(include_twins=False))
    for letter in "BCD":
        card = fs._fleet_by_letter(data, letter)
        h = card.get("health") or {}
        n = STRIP_COUNTS[letter]
        if card.get("badge") != "LIVE" or h.get("instances_total") != n or h.get("instances_live") != n:
            raise AssertionError(f"{letter}: LIVE {n}/{n} expected, got {card.get('badge')}, {h}")
    return "strip instances live: B 9/9, C 6/6, D 12/12"


def check_tr4():
    # a twin still reporting (before the deploy order is followed) does not count
    data = _strip(_fake_all_ic(include_twins=True))
    h = fs._fleet_by_letter(data, "B").get("health") or {}
    if h.get("instances_total") != 9 or h.get("instances_live") != 9:
        raise AssertionError(f"B counts only its strip nine: got {h}")
    return "a twin heartbeat is not counted on the strip"


def check_tr5():
    data = _strip(_fake_all_ic(include_twins=True))
    rows = [r["pair"] for r in (data.get("books") or {}).get("rows", [])]
    if rows != BOOK_ROWS:
        raise AssertionError(f"books rows must be TA10 order (17), got {rows}")
    for key in ("gaps", "quotes"):
        prow = [r["pair"] for r in (data.get(key) or {}).get("rows", [])]
        if prow != BOOK_ROWS:
            raise AssertionError(f"{key} rows must match books (17): {prow}")
        if any(p in ("AUDNZD*", "NZDCAD*") for p in prow):
            raise AssertionError(f"{key} must not list retired IC twin rows: {prow}")
    return "books, gaps, quotes: seventeen rows including ALT arms"


def check_tr6():
    """GUARD: each fleet's own page keeps its full eleven-id list."""
    import app as pipshed

    want_len = {"B": 11, "C": 15, "D": 17}
    for letter, lst in (("B", pipshed.GRIND_B_INSTANCES), ("C", pipshed.GRIND_C_INSTANCES),
                        ("D", pipshed.GRIND_D_INSTANCES)):
        if len(lst) != want_len[letter]:
            raise AssertionError(f"{letter} page list len {want_len[letter]}, got {len(lst)}")
    return "fleet pages: B 11, C 15, D 17 tiles"


CHECKS = [("TR1", check_tr1), ("TR2", check_tr2), ("TR3", check_tr3),
          ("TR4", check_tr4), ("TR5", check_tr5), ("TR6", check_tr6)]


def main():
    passed = failed = 0
    for name, fn in CHECKS:
        try:
            print(f"{name} OK: {fn()}")
            passed += 1
        except Exception as exc:
            print(f"{name} FAIL: {exc}")
            failed += 1
    print(f"SUMMARY passed={passed} failed={failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
