"""Verification: C80 (ADR-164 markers on the banner), C74 (a released
quarantine is not an alert), C81 (the fleet card keeps the previous broker
day until the FTMO roll).

Tests first. Predicted at the tests-only commit: MQ1, MQ2, MQ3, MQ4, MQ6,
MQ7, MQ8 FAIL; MQ5 is a guard that passes in both states.

    python scripts/verify_c80_c74_c81.py
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

T0 = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
NOW = T0 + timedelta(hours=1)


def _codes(groups):
    return [(g["instance_id"], g["code"], g["count"]) for g in groups]


def check_mq1():
    import ftmo_daily as fd
    rows = [
        ("GRIND_GBPUSD_OPTC", "WARN", "DEAL_EVENT_MISSED", T0),
        ("GRIND_GBPUSD_OPTC", "WARN", "REPLAY_INIT_DEFERRED", T0),
        ("GRIND_EURUSD_OPTB", "WARN", "REPLAY_SEED_FAILED", T0),
        ("GRIND_GBPUSD_OPTC", "INFO", "DEAL_REPLAYED", T0),
        ("GRIND_GBPUSD_OPTC", "INFO", "DEAL_EVENT_AFTER_REPLAY", T0),
        ("GRIND_GBPUSD_OPTC", "INFO", "CONNECTION_RESTORED", T0),
    ]
    got = sorted(g["code"] for g in fd.critical_groups(rows, NOW))
    want = ["DEAL_EVENT_MISSED", "REPLAY_INIT_DEFERRED", "REPLAY_SEED_FAILED"]
    if got != want:
        raise AssertionError(f"expected {want}, got {got}")
    return "the three ADR-164 WARNs reach the banner; the INFO markers do not"


def check_mq2():
    import ftmo_daily as fd
    rows = [("GRIND_AUDNZD_OPT", "WARN", "QUARANTINE_ENTER", T0),
            ("GRIND_AUDNZD_OPT", "INFO", "QUARANTINE_RELEASE", T0 + timedelta(milliseconds=200))]
    got = _codes(fd.critical_groups(rows, NOW))
    if got:
        raise AssertionError(f"a released quarantine must not be an alert, got {got}")
    return "enter + release 200 ms later: no alert"


def check_mq3():
    import ftmo_daily as fd
    t2 = T0 + timedelta(minutes=5)
    rows = [("GRIND_AUDNZD_OPT", "WARN", "QUARANTINE_ENTER", T0),
            ("GRIND_AUDNZD_OPT", "INFO", "QUARANTINE_RELEASE", T0 + timedelta(seconds=1)),
            ("GRIND_AUDNZD_OPT", "WARN", "QUARANTINE_ENTER", t2)]
    g = fd.critical_groups(rows, NOW)
    if _codes(g) != [("GRIND_AUDNZD_OPT", "QUARANTINE_ENTER", 1)] or g[0]["first_at"] != t2:
        raise AssertionError(f"only the unreleased enter (t2) stays, got {g}")
    return "released enter hidden, open enter shown (count 1, first_at the open one)"


def check_mq4():
    import ftmo_daily as fd
    # a release BEFORE the enter answers nothing; a release at the SAME time does
    rows = [("GRIND_EURGBP_OPTB", "INFO", "QUARANTINE_RELEASE", T0 - timedelta(seconds=1)),
            ("GRIND_EURGBP_OPTB", "WARN", "QUARANTINE_ENTER", T0),
            ("GRIND_CADCHF_OPTB", "WARN", "QUARANTINE_ENTER", T0),
            ("GRIND_CADCHF_OPTB", "INFO", "QUARANTINE_RELEASE", T0)]
    got = _codes(fd.critical_groups(rows, NOW))
    if got != [("GRIND_EURGBP_OPTB", "QUARANTINE_ENTER", 1)]:
        raise AssertionError(f"expected only EURGBP's enter, got {got}")
    return "an earlier release answers nothing; a same-time release answers the enter"


def check_mq5():
    import ftmo_daily as fd
    # guard: a halt stays, and one instance's release never answers another's enter
    rows = [("GRIND_GBPUSD_OPTC", "WARN", "QUARANTINE_ENTER", T0),
            ("GRIND_GBPUSD_OPTC", "CRITICAL", "QUARANTINE_HALT", T0 + timedelta(seconds=3)),
            ("GRIND_EURUSD_OPTC", "INFO", "QUARANTINE_RELEASE", T0 + timedelta(seconds=1))]
    got = sorted(_codes(fd.critical_groups(rows, NOW)))
    want = [("GRIND_GBPUSD_OPTC", "QUARANTINE_ENTER", 1), ("GRIND_GBPUSD_OPTC", "QUARANTINE_HALT", 1)]
    if got != want:
        raise AssertionError(f"expected {want}, got {got}")
    return "halt kept; releases are per instance"


class _Cur:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None

    def execute(self, sql):
        self.sql = sql

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self, rows):
        self.cur = _Cur(rows)

    def cursor(self):
        return self.cur


def check_mq6():
    import archive_worker as aw
    rows = [("GRIND_AUDNZD_OPT", "WARN", "QUARANTINE_ENTER", T0),
            ("GRIND_AUDNZD_OPT", "INFO", "QUARANTINE_RELEASE", T0 + timedelta(seconds=1)),
            ("GRIND_NZDCHF_OPT", "WARN", "QUARANTINE_ENTER", T0)]
    conn = _Conn(rows)
    payload = aw.build_critical_list(conn)
    if "QUARANTINE_RELEASE" not in conn.cur.sql:
        raise AssertionError("the critical query must also read QUARANTINE_RELEASE (INFO)")
    if payload.get("quarantines_released_24h") != 1:
        raise AssertionError(f"quarantines_released_24h: {payload.get('quarantines_released_24h')}")
    if [r["instance_id"] for r in payload["rows"]] != ["GRIND_NZDCHF_OPT"]:
        raise AssertionError(f"rows {payload['rows']}")
    return "query reads releases; payload counts released quarantines"


def check_mq7():
    import app as pipshed
    cases = [("2026-09-29T20:59:00", "2026-09-29"),    # before the broker roll
             ("2026-09-29T21:30:00", "2026-09-29"),    # broker day already 30 Sep
             ("2026-09-29T22:00:00", "2026-09-30"),    # FTMO roll (CEST)
             ("2026-10-26T22:30:00", "2026-10-26"),    # winter: broker rolls 22:00Z
             ("2026-10-26T23:10:00", "2026-10-27")]    # FTMO rolls 23:00Z (CET)
    for text, want in cases:
        got = pipshed._card_summary_day(datetime.fromisoformat(text + "+00:00"))
        if got != want:
            raise AssertionError(f"{text}Z: expected {want}, got {got}")
    return "card day = FTMO day's date (summer and winter)"


def check_mq8():
    import app as pipshed
    from verify_fleet_strip import (FakeRedis, _apply_fixture_fb2, _fleet_by_letter, _push,
                                    _scalp_rec, _strip)
    # the gap hour: broker day already 30 Sep, the FTMO day still 29 Sep
    old = (pipshed._broker_today, getattr(pipshed, "_card_summary_day", None))
    try:
        pipshed._broker_today = lambda: "2026-09-30"
        pipshed._card_summary_day = lambda now_utc=None: "2026-09-29"
        fake = FakeRedis()
        _apply_fixture_fb2(fake)
        _push(fake, "GRIND_GBPUSD_OPTB", _scalp_rec("GRIND_GBPUSD_OPTB", 1.32000, 1.32100, 1.00,
                                                    trade_date="2026-09-29"))
        sm = _fleet_by_letter(_strip(fake), "B").get("summary") or {}
    finally:
        pipshed._broker_today = old[0]
        if old[1] is not None:
            pipshed._card_summary_day = old[1]
        else:
            del pipshed._card_summary_day
    if sm.get("broker_day") != "2026-09-29" or (sm.get("scalps") or {}).get("count") != 1:
        raise AssertionError(f"card must show 29 Sep with its scalp, got {sm.get('broker_day')}, "
                             f"{sm.get('scalps')}")
    return "in the gap hour the card keeps the previous broker day and its scalps"


CHECKS = [("MQ1", check_mq1), ("MQ2", check_mq2), ("MQ3", check_mq3), ("MQ4", check_mq4),
          ("MQ5", check_mq5), ("MQ6", check_mq6), ("MQ7", check_mq7), ("MQ8", check_mq8)]


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
