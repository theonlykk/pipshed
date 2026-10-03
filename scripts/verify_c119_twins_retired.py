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
PAIRS = ["GBPUSD", "EURUSD", "EURGBP", "AUDCAD", "AUDCHF", "CADCHF", "NZDCHF", "NZDCAD", "AUDNZD"]
LOGIN = {"B": 53066709, "C": 53071896, "D": 53077984}


def _strip(fake):
    import app as pipshed

    pipshed.r = fake
    return pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json()


def _fake_all_ic(include_twins):
    fake = fs.FakeRedis()
    for letter in "BCD":
        for p in PAIRS:
            fake.set(f"fxmatrix:state:GRIND_{p}_OPT{letter}", fs.HB(30, account_login=LOGIN[letter]))
        if include_twins:
            for p in ("AUDNZD", "NZDCAD"):
                fake.set(f"fxmatrix:state:GRIND_{p}_ALT{letter}", fs.HB(30, account_login=LOGIN[letter]))
    return fake


def check_tr1():
    import app as pipshed

    got = set(pipshed.GRIND_RETIRED_INSTANCES)
    if got != CYCLE3 | TWINS:
        raise AssertionError(f"retired must be cycle 3's four + the six twins, got {sorted(got)}")
    return "GRIND_RETIRED_INSTANCES = 4 + 6"


def check_tr2():
    import app as pipshed

    for entry in pipshed.FLEET_STRIP:
        if entry["letter"] in "BCD":
            want = [f"GRIND_{p}_OPT{entry['letter']}" for p in PAIRS]
            if list(entry["instances"]) != want:
                raise AssertionError(f"{entry['letter']} strip must be the nine _OPT ids, got {entry['instances']}")
    return "B, C, D strips = the nine _OPT ids, pair order kept"


def check_tr3():
    # all nine OPT reporting and the twins silent: LIVE 9/9 on B, C and D
    data = _strip(_fake_all_ic(include_twins=False))
    for letter in "BCD":
        card = fs._fleet_by_letter(data, letter)
        h = card.get("health") or {}
        if card.get("badge") != "LIVE" or h.get("instances_total") != 9 or h.get("instances_live") != 9:
            raise AssertionError(f"{letter}: LIVE 9/9 expected, got {card.get('badge')}, {h}")
    return "twins silent: B, C, D LIVE 9/9 (not PARTIAL)"


def check_tr4():
    # a twin still reporting (before the deploy order is followed) does not count
    data = _strip(_fake_all_ic(include_twins=True))
    h = fs._fleet_by_letter(data, "B").get("health") or {}
    if h.get("instances_total") != 9 or h.get("instances_live") != 9:
        raise AssertionError(f"B counts only its nine: got {h}")
    return "a twin heartbeat is not counted on the strip"


def check_tr5():
    data = _strip(_fake_all_ic(include_twins=True))
    rows = [r["pair"] for r in (data.get("books") or {}).get("rows", [])]
    starred = [p for p in rows if p.endswith("*")]
    if starred or set(rows) != set(PAIRS):
        raise AssertionError(f"books rows must be the nine pairs, no twin rows: {rows}")
    for key in ("gaps", "quotes"):
        prow = [r["pair"] for r in (data.get(key) or {}).get("rows", [])]
        if any(p.endswith("*") for p in prow):
            raise AssertionError(f"{key} still has a twin row: {prow}")
    return "books, gaps, quotes: nine rows, no AUDNZD* / NZDCAD*"


def check_tr6():
    """GUARD: each fleet's own page keeps its full eleven-id list."""
    import app as pipshed

    for letter, lst in (("B", pipshed.GRIND_B_INSTANCES), ("C", pipshed.GRIND_C_INSTANCES),
                        ("D", pipshed.GRIND_D_INSTANCES)):
        if len(lst) != 11 or not {f"GRIND_AUDNZD_ALT{letter}", f"GRIND_NZDCAD_ALT{letter}"} <= set(lst):
            raise AssertionError(f"{letter} page list must stay eleven with its twins")
    return "fleet pages keep eleven tiles"


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
