"""Verification: C90 (a DUPLICATE_MAGIC CRITICAL greys once its instance runs
again) and Fleet D's commission rate (account 53077984).

C90. A duplicate-magic CRITICAL means that instance's EA failed OnInit and
was unloaded (fxmatrix 02_TRAPS 1 Oct D1). Once the same instance is live,
not halted and invariant_ok true, the event is history, exactly like the
halt codes: the fleet strip shows it as "resolved" (grey) and /critical adds
"resolved": true. Any other non-halt CRITICAL still stays red.

Commission. COMMISSION_PER_CLOSE_BY_ACCOUNT lists FTMO, B and C; D's IC Raw
account 53077984 is missing, so D's daily summary printed "commission
unknown". IC Raw is $3.5/lot/side, booked 0.04 + 0.04 per closed 0.01 layer
on B and C; D is the same account type (to be confirmed on D's ledger
before push). Unknown accounts stay unknown.

Tests first. Predicted at the tests-only commit: DM1, DM3 and CM1 FAIL;
DM2, DM4, DM5 and CM2 are guards that pass in both states.

    python scripts/verify_c90_d_commission.py
"""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "verify_fleet_strip_helpers", os.path.join(ROOT, "scripts", "verify_fleet_strip.py"))
fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fs)

TOKEN = fs.TOKEN
DUP_INST = "GRIND_NZDCAD_OPTD"


def _crit_rows():
    return {
        "generated_at": fs.now.isoformat(),
        "rows": [
            {"instance_id": DUP_INST, "level": "CRITICAL", "code": "DUPLICATE_MAGIC",
             "count": 1, "first_at": "2026-10-01T06:24:17Z", "last_at": "2026-10-01T06:24:17Z"},
            {"instance_id": "GRIND_EURUSD_OPTD", "level": "CRITICAL",
             "code": "STARTUP_EXIT_SHORTFALL_SIDE",
             "count": 1, "first_at": "2026-10-01T06:30:00Z", "last_at": "2026-10-01T06:30:00Z"},
        ],
    }


def _fleet_d(fake, dup_hb="live"):
    """Every D instance live and healthy; the duplicate's instance per dup_hb:
    'live' healthy, 'missing' no heartbeat, 'halted' halted."""
    for inst in fs.GRIND_D_INSTANCES:
        if inst == DUP_INST and dup_hb == "missing":
            continue
        if inst == DUP_INST and dup_hb == "halted":
            fake.set(f"fxmatrix:state:{inst}",
                     fs.HBB(30, account_login=53077984, halted=True,
                            halt_reason="TEST", invariant_ok=True))
            continue
        fake.set(f"fxmatrix:state:{inst}", fs.HBB(30, account_login=53077984, invariant_ok=True))
    fake.set(fs.DAILY_TABLE_KEY, json.dumps({"generated_at": fs.now.isoformat(), "rows": []}))
    fake.set(fs.CRITICAL_KEY, json.dumps(_crit_rows()))


def _d_events(fake):
    import app as pipshed

    pipshed.r = fake
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets/c90").get_json()
    d = fs._fleet_by_letter(data, "D")
    return [a for a in d.get("alerts") or [] if a.get("kind") == "EVENT"]


def _critical(fake):
    import app as pipshed

    pipshed.r = fake
    resp = pipshed.app.test_client().get(f"/api/g/{TOKEN}/critical/c90")
    if resp.status_code != 200:
        raise AssertionError(f"status {resp.status_code}")
    return {(r.get("instance_id"), r.get("code")): r.get("resolved") is True
            for r in resp.get_json().get("rows") or []}


def check_dm1():
    fake = fs.FakeRedis()
    _fleet_d(fake, "live")
    dup = [a for a in _d_events(fake) if a.get("code") == "DUPLICATE_MAGIC"]
    if len(dup) != 1 or dup[0].get("level") != "resolved":
        raise AssertionError(f"DUPLICATE_MAGIC on a running instance must be resolved, got {dup}")
    if not str(dup[0].get("detail", "")).endswith("resolved: instance running again"):
        raise AssertionError(f"resolved detail must say so: {dup[0]}")
    return "strip: DUPLICATE_MAGIC greys once its instance runs again"


def check_dm2():
    """GUARD: no heartbeat from that instance -> the event stays red."""
    fake = fs.FakeRedis()
    _fleet_d(fake, "missing")
    dup = [a for a in _d_events(fake) if a.get("code") == "DUPLICATE_MAGIC"]
    if len(dup) != 1 or dup[0].get("level") != "red":
        raise AssertionError(f"an instance not running keeps DUPLICATE_MAGIC red, got {dup}")
    return "strip: DUPLICATE_MAGIC stays red while its instance does not run"


def check_dm3():
    fake = fs.FakeRedis()
    _fleet_d(fake, "live")
    got = _critical(fake)
    if got.get((DUP_INST, "DUPLICATE_MAGIC")) is not True:
        raise AssertionError(f"/critical must mark the DUPLICATE_MAGIC row resolved, got {got}")
    if got.get(("GRIND_EURUSD_OPTD", "STARTUP_EXIT_SHORTFALL_SIDE")) is not False:
        raise AssertionError(f"other non-halt CRITICALs are not resolved, got {got}")
    return "/critical: DUPLICATE_MAGIC resolved on a running instance; others not"


def check_dm4():
    """GUARD: a halted instance resolves nothing."""
    fake = fs.FakeRedis()
    _fleet_d(fake, "halted")
    got = _critical(fake)
    if any(got.values()):
        raise AssertionError(f"a halted instance is never resolved, got {got}")
    return "/critical: a halted instance resolves nothing"


def check_dm5():
    """GUARD: a non-halt CRITICAL other than DUPLICATE_MAGIC stays red."""
    fake = fs.FakeRedis()
    _fleet_d(fake, "live")
    row = [a for a in _d_events(fake) if a.get("code") == "STARTUP_EXIT_SHORTFALL_SIDE"]
    if len(row) != 1 or row[0].get("level") != "red":
        raise AssertionError(f"STARTUP_EXIT_SHORTFALL_SIDE stays red, got {row}")
    return "strip: other non-halt CRITICALs stay red"


def check_cm1():
    import app as pipshed

    got = pipshed._commission_for_records([{"account_login": 53077984}] * 4)
    if got != (-0.32, 0):
        raise AssertionError(f"Fleet D (53077984): 4 closes at 0.08 -> (-0.32, 0), got {got}")
    return "Fleet D commission 0.08 per close"


def check_cm2():
    """GUARD: an unlisted account is still unknown, never guessed."""
    import app as pipshed

    got = pipshed._commission_for_records([{"account_login": 53077984}, {"account_login": 12345}])
    if got[0] is not None or got[1] < 1:
        raise AssertionError(f"an unknown account keeps the total unknown, got {got}")
    return "unknown accounts stay unknown"


CHECKS = [
    ("DM1", check_dm1),
    ("DM2", check_dm2),
    ("DM3", check_dm3),
    ("DM4", check_dm4),
    ("DM5", check_dm5),
    ("CM1", check_cm1),
    ("CM2", check_cm2),
]


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
