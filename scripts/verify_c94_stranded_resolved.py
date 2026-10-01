"""Verification: C94, a ROLL_STRANDED alert greys once no side of that
instance is fully rolled at cap.

ROLL_STRANDED (WARN) is sent once per episode and nothing is sent when a
side recovers, so the strip and the banner kept it amber for 24 h after the
side was unstranded (fxmatrix 1 Oct: five sides unstranded by commanded
eject still showed amber). From the live heartbeat: a side is FULLY ROLLED
AT CAP when its depth equals max_layers and every layer on it is rolled (a
long's exit target below its entry, a short's above). If no side of the
instance is, the event is history: the strip shows it "resolved" (grey,
"resolved: no side fully rolled at cap") and /critical adds "resolved": true
with that note. A side still fully rolled at cap stays amber even if the
market came back near (one push from stranding again). No heartbeat, a
halted instance, or a payload without layer detail at cap: stays amber.

Tests first. Predicted at the tests-only commit: SR1, SR2, SR3 and SR7
FAIL; SR4, SR5 and SR6 are guards that pass in both states. CR5 in
verify_critical_resolved.py is updated in the same commit (the banner's
resolved text now comes from the row) and fails there until the fix.

    python scripts/verify_c94_stranded_resolved.py
"""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "verify_fleet_strip_helpers_c94", os.path.join(ROOT, "scripts", "verify_fleet_strip.py"))
fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fs)

TOKEN = fs.TOKEN
INST = "GRIND_AUDCHF_OPTD"
NOTE = "resolved: no side fully rolled at cap"


def _longs(n, rolled):
    """n long layers from 0.58100 down by 4 pips; the first `rolled` of them
    rolled (exit 22 pips BELOW entry), the rest unrolled (exit 10 pips above)."""
    out = []
    for k in range(n):
        entry = round(0.58100 - 0.0004 * k, 5)
        exit_target = round(entry - 0.0022, 5) if k < rolled else round(entry + 0.0010, 5)
        out.append({"layer_index": k, "side": "L", "entry_price": entry, "exit_target": exit_target,
                    "has_exit_order": k in (0, n - 1), "has_exit_position": False})
    return out


def _shorts(n, rolled):
    out = []
    for k in range(n):
        entry = round(0.57000 + 0.0004 * k, 5)
        exit_target = round(entry + 0.0022, 5) if k < rolled else round(entry - 0.0010, 5)
        out.append({"layer_index": k, "side": "S", "entry_price": entry, "exit_target": exit_target,
                    "has_exit_order": k in (0, n - 1), "has_exit_position": False})
    return out


def _hb(layers, **over):
    longs = sum(1 for l in layers if l["side"] == "L")
    shorts = sum(1 for l in layers if l["side"] == "S")
    return fs.HBB(30, account_login=53077984, invariant_ok=True, max_layers=8,
                  layers=layers, **dict({"open_layers_long": longs, "open_layers_short": shorts}, **over))


def _crit():
    return {"generated_at": fs.now.isoformat(), "rows": [
        {"instance_id": INST, "level": "WARN", "code": "ROLL_STRANDED", "count": 1,
         "first_at": "2026-10-01T15:14:32Z", "last_at": "2026-10-01T15:14:32Z"},
        {"instance_id": "GRIND_EURUSD_OPTD", "level": "WARN", "code": "QUARANTINE_ENTER", "count": 3,
         "first_at": "2026-10-01T15:00:00Z", "last_at": "2026-10-01T15:10:00Z"},
    ]}


def _fixture(fake, inst_hb):
    for inst in fs.GRIND_D_INSTANCES:
        if inst == INST:
            if inst_hb is not None:
                fake.set(f"fxmatrix:state:{inst}", inst_hb)
            continue
        fake.set(f"fxmatrix:state:{inst}", fs.HBB(30, account_login=53077984, invariant_ok=True))
    fake.set(fs.DAILY_TABLE_KEY, json.dumps({"generated_at": fs.now.isoformat(), "rows": []}))
    fake.set(fs.CRITICAL_KEY, json.dumps(_crit()))


def _strip(fake):
    import app as pipshed

    pipshed.r = fake
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets/c94").get_json()
    d = fs._fleet_by_letter(data, "D")
    return {a.get("code"): a for a in d.get("alerts") or [] if a.get("kind") == "EVENT"}


def _critical(fake):
    import app as pipshed

    pipshed.r = fake
    rows = pipshed.app.test_client().get(f"/api/g/{TOKEN}/critical/c94").get_json().get("rows") or []
    return {(r.get("instance_id"), r.get("code")): r for r in rows}


def _assert_resolved(fake, why):
    a = _strip(fake).get("ROLL_STRANDED")
    if not a or a.get("level") != "resolved" or not str(a.get("detail", "")).endswith(NOTE):
        raise AssertionError(f"{why}: strip must show ROLL_STRANDED resolved with '{NOTE}', got {a}")
    row = _critical(fake).get((INST, "ROLL_STRANDED")) or {}
    if row.get("resolved") is not True or row.get("resolved_note") != NOTE:
        raise AssertionError(f"{why}: /critical must mark it resolved with the note, got {row}")


def _assert_amber(fake, why):
    a = _strip(fake).get("ROLL_STRANDED")
    if not a or a.get("level") != "amber":
        raise AssertionError(f"{why}: strip must keep ROLL_STRANDED amber, got {a}")
    row = _critical(fake).get((INST, "ROLL_STRANDED")) or {}
    if row.get("resolved") is True:
        raise AssertionError(f"{why}: /critical must not resolve it, got {row}")


def check_sr1():
    fake = fs.FakeRedis()
    _fixture(fake, _hb(_longs(7, 7) + _shorts(2, 0)))          # long side below cap after an eject
    _assert_resolved(fake, "both sides below cap")
    return "below cap on both sides: ROLL_STRANDED greys"


def check_sr2():
    fake = fs.FakeRedis()
    _fixture(fake, _hb(_longs(8, 7) + _shorts(1, 0)))          # at cap, one unrolled layer
    _assert_resolved(fake, "long side at cap with one unrolled layer")
    return "at cap with an unrolled layer: greys"


def check_sr3():
    fake = fs.FakeRedis()
    _fixture(fake, _hb(_longs(3, 0) + _shorts(8, 7)))          # short side at cap, one unrolled
    _assert_resolved(fake, "short side at cap with one unrolled layer")
    return "short side mirrors the long rule: greys"


def check_sr4():
    """GUARD: a side fully rolled at cap keeps the alert amber (long, then short)."""
    fake = fs.FakeRedis()
    _fixture(fake, _hb(_longs(8, 8) + _shorts(2, 0)))
    _assert_amber(fake, "long side fully rolled at cap")
    fake2 = fs.FakeRedis()
    _fixture(fake2, _hb(_longs(2, 0) + _shorts(8, 8)))
    _assert_amber(fake2, "short side fully rolled at cap")
    return "fully rolled at cap stays amber"


def check_sr5():
    """GUARD: no heartbeat, a halted instance, or no layer detail at cap: amber."""
    fake = fs.FakeRedis()
    _fixture(fake, None)
    _assert_amber(fake, "no heartbeat")
    fake2 = fs.FakeRedis()
    _fixture(fake2, _hb(_longs(7, 7), halted=True, halt_reason="TEST"))
    _assert_amber(fake2, "halted")
    fake3 = fs.FakeRedis()
    _fixture(fake3, fs.HBB(30, account_login=53077984, invariant_ok=True, max_layers=8,
                           open_layers_long=8, open_layers_short=1))   # at cap, no layers list
    _assert_amber(fake3, "at cap without layer detail")
    return "unknown or halted state stays amber"


def check_sr6():
    """GUARD: other amber codes are untouched."""
    fake = fs.FakeRedis()
    _fixture(fake, _hb(_longs(7, 7)))
    q = _strip(fake).get("QUARANTINE_ENTER")
    if not q or q.get("level") != "amber":
        raise AssertionError(f"QUARANTINE_ENTER stays amber, got {q}")
    row = _critical(fake).get(("GRIND_EURUSD_OPTD", "QUARANTINE_ENTER")) or {}
    if row.get("resolved") is True:
        raise AssertionError(f"QUARANTINE_ENTER is never resolved, got {row}")
    return "other WARN codes untouched"


def check_sr7():
    import app as pipshed

    html = pipshed.app.test_client().get("/").get_data(as_text=True)
    need = ["(r.resolved ? '  ' + (r.resolved_note || 'resolved: instance running again') : '')",
            "fully rolled at cap"]
    missing = [n for n in need if n not in html]
    if missing:
        raise AssertionError(f"banner/legend lack {missing}")
    return "banner prints the row's resolved note; legend explains the stranded grey"


CHECKS = [("SR1", check_sr1), ("SR2", check_sr2), ("SR3", check_sr3), ("SR4", check_sr4),
          ("SR5", check_sr5), ("SR6", check_sr6), ("SR7", check_sr7)]


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
