"""Verification: C108, a critical-feed row for a RETIRED instance is history.

fxmatrix 2 Oct 2026 (geometry-cycle3 A7): cycle 3 retired GRIND_AUDNZD_ALT,
GRIND_NZDCAD_ALT, GRIND_AUDCAD_OPT and GRIND_NZDCHF_OPT. Their rows in the
24 h critical feed (e.g. AUDCAD_OPT's 1 Oct INVARIANT_FAIL) can never clear
by the "instance running again" rule, because the instance never runs again,
so the banner stayed red for a fixed problem. Rule: every row whose instance
is in GRIND_RETIRED_INSTANCES gets "resolved": true and the note
"resolved: instance retired", whatever its level or code. Rows of kept
instances follow the existing rules unchanged.

Tests first. Predicted at the tests-only commit: RC1, RC2, RC3 and RC6
FAIL; RC4 and RC5 are guards that pass in both states.

    python scripts/verify_c108_retired_critical.py
"""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "verify_fleet_strip_helpers_c108", os.path.join(ROOT, "scripts", "verify_fleet_strip.py"))
fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fs)

TOKEN = fs.TOKEN
NOTE = "resolved: instance retired"
RETIRED = {"GRIND_AUDNZD_ALT", "GRIND_NZDCAD_ALT", "GRIND_AUDCAD_OPT", "GRIND_NZDCHF_OPT"}


def _row(inst, level, code):
    return {"instance_id": inst, "level": level, "code": code, "count": 1,
            "first_at": "2026-10-01T17:55:00Z", "last_at": "2026-10-01T17:55:30Z"}


def _critical(rows, heartbeats=None):
    import app as pipshed

    fake = fs.FakeRedis()
    for inst, hb in (heartbeats or {}).items():
        fake.set(f"fxmatrix:state:{inst}", hb)
    fake.set(fs.CRITICAL_KEY, json.dumps({"generated_at": fs.now.isoformat(), "rows": rows}))
    pipshed.r = fake
    return pipshed.app.test_client().get(f"/api/g/{TOKEN}/critical").get_json()["rows"]


def check_rc1():
    out = _critical([_row("GRIND_AUDCAD_OPT", "CRITICAL", "INVARIANT_FAIL")])
    if not (out[0].get("resolved") is True and out[0].get("resolved_note") == NOTE):
        raise AssertionError(f"a retired instance's halt row must be resolved with {NOTE!r}: {out[0]}")
    return "retired instance, halt code: resolved, retired note"


def check_rc2():
    out = _critical([_row("GRIND_AUDCAD_OPT", "CRITICAL", "STARTUP_EXIT_SHORTFALL")])
    if not (out[0].get("resolved") is True and out[0].get("resolved_note") == NOTE):
        raise AssertionError(f"a retired instance's non-halt CRITICAL must be resolved too: {out[0]}")
    return "retired instance, non-halt CRITICAL: resolved"


def check_rc3():
    out = _critical([_row("GRIND_NZDCHF_OPT", "WARN", "ROLL_STRANDED"),
                     _row("GRIND_AUDNZD_ALT", "WARN", "QUARANTINE_ENTER")])
    for row in out:
        if not (row.get("resolved") is True and row.get("resolved_note") == NOTE):
            raise AssertionError(f"every row of a retired instance is history: {row}")
    return "retired instance, WARN rows: resolved"


def check_rc4():
    # guard: a KEPT instance with no heartbeat keeps its halt row open
    out = _critical([_row("GRIND_AUDNZD_OPT", "CRITICAL", "INVARIANT_FAIL")])
    if out[0].get("resolved"):
        raise AssertionError(f"a kept instance without a heartbeat must stay open: {out[0]}")
    return "kept instance, no heartbeat: open (unchanged)"


def check_rc5():
    # guard: a kept, healthy instance's halt row still resolves by the old rule and note
    hb = fs.HBB(30, account_login=1514731800, invariant_ok=True)
    out = _critical([_row("GRIND_AUDNZD_OPT", "CRITICAL", "INVARIANT_FAIL")],
                    {"GRIND_AUDNZD_OPT": hb})
    if out[0].get("resolved") is not True or out[0].get("resolved_note") == NOTE:
        raise AssertionError(f"a kept healthy instance resolves as 'running again', not retired: {out[0]}")
    return "kept healthy instance: resolved by the existing rule"


def check_rc6():
    import app as pipshed

    if set(getattr(pipshed, "GRIND_RETIRED_INSTANCES", ())) != RETIRED:
        raise AssertionError(f"GRIND_RETIRED_INSTANCES must be {sorted(RETIRED)}")
    if set(pipshed.GRIND_A_STRIP_INSTANCES) & RETIRED:
        raise AssertionError("a retired instance is still on the A strip")
    with open(os.path.join(ROOT, "templates", "dashboard.html"), encoding="utf-8") as fh:
        html = fh.read()
    if NOTE not in html:
        raise AssertionError("the alerts legend must explain 'resolved: instance retired'")
    return "retired list, strip and legend agree"


CHECKS = [("RC1", check_rc1), ("RC2", check_rc2), ("RC3", check_rc3),
          ("RC4", check_rc4), ("RC5", check_rc5), ("RC6", check_rc6)]


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
