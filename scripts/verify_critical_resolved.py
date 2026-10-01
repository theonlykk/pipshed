"""Verification: the ADR-159 critical banner marks resolved halt events.

A halt clears only when the EA restarts (g_grind_halted is reset in
OnInit). So a halt-code CRITICAL row (INVARIANT_FAIL, QUARANTINE_HALT,
RECON_FAIL, REBUILD_EXIT_*) whose instance is live, not halted and
invariant_ok true NOW is history: /critical adds "resolved": true to that
row (the Redis payload is not changed), and the page leaves resolved rows
out of the banner colour and greys them.

Tests first. Predicted at the tests-only commit: CR1 and CR5 FAIL;
CR2, CR3, CR4 are guards that pass in both states.

    python scripts/verify_critical_resolved.py
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TOKEN = "k7m9p2x4q"
CRITICAL_KEY = "fxmatrix:critical:last24h"
now = datetime.now(timezone.utc)


class FakeRedis:
    def __init__(self):
        self._kv = {}

    def get(self, key):
        return self._kv.get(key)

    def set(self, key, value, ex=None):
        self._kv[key] = value


def HB(**overrides):
    payload = {
        "_received_at": (now - timedelta(seconds=20)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "halted": False,
        "invariant_ok": True,
        "open_layers_long": 1,
        "open_layers_short": 6,
        "account_login": 53071896,
    }
    payload.update(overrides)
    return json.dumps(payload)


def _rows():
    return {
        "generated_at": now.isoformat(),
        "rows": [
            {"instance_id": "GRIND_GBPUSD_OPTC", "level": "CRITICAL", "code": "INVARIANT_FAIL",
             "count": 2, "first_at": "2026-09-28T16:27:38Z", "last_at": "2026-09-28T16:27:40Z"},
            {"instance_id": "GRIND_GBPUSD_OPTC", "level": "CRITICAL", "code": "QUARANTINE_HALT",
             "count": 1, "first_at": "2026-09-28T16:27:38Z", "last_at": "2026-09-28T16:27:38Z"},
            {"instance_id": "GRIND_GBPUSD_OPT", "level": "WARN", "code": "QUARANTINE_ENTER",
             "count": 16, "first_at": "2026-09-28T09:00:00Z", "last_at": "2026-09-28T17:37:00Z"},
            {"instance_id": "GRIND_EURUSD_OPTB", "level": "CRITICAL", "code": "STARTUP_EXIT_SHORTFALL_SIDE",
             "count": 1, "first_at": "2026-09-28T16:00:00Z", "last_at": "2026-09-28T16:00:00Z"},
        ],
    }


def _get(fake):
    import app as pipshed

    fake.set(CRITICAL_KEY, json.dumps(_rows()))
    pipshed.r = fake
    resp = pipshed.app.test_client().get(f"/api/g/{TOKEN}/critical/cr1")
    if resp.status_code != 200:
        raise AssertionError(f"status {resp.status_code}")
    return resp.get_json()


def _resolved(payload):
    return [(row.get("instance_id"), row.get("code"), row.get("resolved") is True)
            for row in payload.get("rows") or []]


def check_cr1():
    fake = FakeRedis()
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPTC", HB())
    fake.set("fxmatrix:state:GRIND_EURUSD_OPTB", HB())
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPT", HB())
    got = _resolved(_get(fake))
    want = [
        ("GRIND_GBPUSD_OPTC", "INVARIANT_FAIL", True),
        ("GRIND_GBPUSD_OPTC", "QUARANTINE_HALT", True),
        ("GRIND_GBPUSD_OPT", "QUARANTINE_ENTER", False),
        ("GRIND_EURUSD_OPTB", "STARTUP_EXIT_SHORTFALL_SIDE", False),
    ]
    if got != want:
        raise AssertionError(f"expected {want}, got {got}")
    stored = json.loads(fake.get(CRITICAL_KEY))
    if any("resolved" in row for row in stored["rows"]):
        raise AssertionError("the Redis payload must not be modified")
    return "halt rows on a recovered instance carry resolved: true; order and others unchanged"


def check_cr2():
    fake = FakeRedis()
    # halted with invariant_ok TRUE (REBUILD_EXIT_FAILED is not an invariant)
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPTC",
             HB(halted=True, halt_reason="REBUILD_EXIT_FAILED", invariant_ok=True))
    got = _resolved(_get(fake))
    if any(r[2] for r in got):
        raise AssertionError(f"a halted instance is never resolved, got {got}")
    return "halted instance: nothing resolved"


def check_cr3():
    fake = FakeRedis()
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPTC", HB(invariant_ok=False))
    got = _resolved(_get(fake))
    if any(r[2] for r in got):
        raise AssertionError(f"invariant_ok false: nothing resolved, got {got}")
    fake2 = FakeRedis()
    raw = json.loads(HB())
    raw.pop("invariant_ok")
    fake2.set("fxmatrix:state:GRIND_GBPUSD_OPTC", json.dumps(raw))
    got2 = _resolved(_get(fake2))
    if any(r[2] for r in got2):
        raise AssertionError(f"missing invariant_ok: nothing resolved, got {got2}")
    return "quarantined or unknown invariant state: nothing resolved"


def check_cr4():
    fake = FakeRedis()          # no heartbeat at all for GBPUSD_OPTC (not live)
    got = _resolved(_get(fake))
    if any(r[2] for r in got):
        raise AssertionError(f"no heartbeat: nothing resolved, got {got}")
    return "no heartbeat: nothing resolved"


def check_cr5():
    import app as pipshed

    html = pipshed.app.test_client().get("/").get_data(as_text=True)
    need = [
        "r.level === 'CRITICAL' && !r.resolved",
        "#criticalBanner.resolved-bg",
        "crit-line resolved",
        # C94: the resolved text comes from the row (resolved_note), default as before
        "(r.resolved ? '  ' + (r.resolved_note || 'resolved: instance running again') : '')",
        ".concat(rows.filter(function(r) { return r.resolved; }))",   # resolved rows last
    ]
    missing = [n for n in need if n not in html]
    if missing:
        raise AssertionError(f"banner template lacks {missing}")
    return "banner colour ignores resolved rows; resolved rows grey"


CHECKS = [
    ("CR1", check_cr1),
    ("CR2", check_cr2),
    ("CR3", check_cr3),
    ("CR4", check_cr4),
    ("CR5", check_cr5),
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
