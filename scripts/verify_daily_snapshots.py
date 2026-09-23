"""Verification for ADR-159 daily snapshots, critical banner, and s4 counts."""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeRedis:
    def __init__(self):
        self._kv = {}
        self._lists = {}

    def set(self, key, value, ex=None):
        self._kv[key] = value

    def get(self, key):
        return self._kv.get(key)

    def llen(self, key):
        return len(self._lists.get(key, []))

    def lmove(self, src, dest, src_pos, dest_pos):
        src_list = self._lists.setdefault(src, [])
        if not src_list:
            return None
        item = src_list.pop(0)
        self._lists.setdefault(dest, []).append(item)
        return item

    def lrange(self, key, start, end):
        items = self._lists.get(key, [])
        if end == -1:
            end = len(items) - 1
        if not items or start > end:
            return []
        return items[start : end + 1]

    def ltrim(self, key, start, end):
        items = self._lists.get(key, [])
        if end == -1:
            end = len(items) - 1
        self._lists[key] = items[start : end + 1] if items and start <= end else []


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._last_sql = None
        self._last_params = None
        self.executed = []

    def execute(self, sql, params=None):
        self._last_sql = sql
        self._last_params = params
        self._conn.executed.append((sql, params))
        if self._conn.fail_on_sql and sql and self._conn.fail_on_sql in sql:
            raise self._conn.fail_on_sql_exc
        if self._conn.fail_on_insert and "INSERT INTO" in sql:
            raise self._conn.fail_on_insert
        return self

    @property
    def description(self):
        sql = self._last_sql or ""
        if "daily_snapshots" in sql and "WHERE ftmo_day >=" in sql:
            return [(name,) for name in (
                "id", "account_login", "ftmo_day", "instance_id", "session_id",
                "ea_time_ms", "received_at", "balance_start", "equity_start",
                "balance_end", "equity_end", "realised", "nontrade", "inventory_pnl",
                "total", "swap_day", "positions_long", "positions_short", "orders",
                "guard_total", "guard_age_s", "breaker_tripped", "premidnight_seen",
                "broker_utc_offset_s", "start_known", "balance_start_source",
                "ejections_auto", "ejections_command", "ejected_fills",
                "ejected_realised", "eject_filled_events", "eject_mismatch",
                "carry_clamps", "critical_events", "derived_at",
            )]
        return []

    def fetchall(self):
        sql = self._last_sql or ""
        if "daily_snapshots" in sql and "WHERE ftmo_day >=" in sql:
            return list(self._conn.daily_snapshot_rows)
        if "ea_events e JOIN session_accounts" in sql:
            return list(self._conn.daily_events)
        if "scalp_history" in sql and "ejected IS TRUE" in sql:
            return list(self._conn.daily_scalps)
        if "FROM ea_events WHERE" in sql and "received_at >" in sql:
            return list(self._conn.critical_rows)
        return []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self):
        self.daily_snapshot_rows = []
        self.daily_events = []
        self.daily_scalps = []
        self.critical_rows = []
        self.fail_on_sql = None
        self.fail_on_sql_exc = psycopg2.DataError("daily sql failed")
        self.fail_on_insert = None
        self.commit_count = 0
        self.executed = []
        self.rollback_count = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1

    def close(self):
        pass


def make_daily_queue_item(detail, code="DAILY_SNAPSHOT"):
    return json.dumps({
        "type": "ea_event",
        "instance_id": "GRIND_EURUSD_OPT",
        "session_id": "sess-daily",
        "received_at": "2026-09-23T22:00:00.000000+00:00",
        "event": {
            "seq": 99,
            "ea_time_ms": 1758664800000,
            "magic": 22260101,
            "level": "INFO",
            "code": code,
            "reason": "",
            "ticket": 0,
            "detail": detail,
        },
    })


def full_snapshot_detail():
    return {
        "account_login": 12345678,
        "ftmo_day": "2026.09.23",
        "balance_start": "100000.00",
        "equity_start": "100050.00",
        "balance_end": "100100.00",
        "equity_end": "100120.00",
        "realised": "50.00",
        "nontrade": "0.00",
        "inventory_pnl": "20.00",
        "total": "70.00",
        "swap_day": "-1.50",
        "positions_long": 2,
        "positions_short": 1,
        "orders": 3,
        "guard_total": 5,
        "guard_age_s": 3600,
        "breaker_tripped": False,
        "premidnight_seen": True,
        "broker_utc_offset_s": 10800,
        "start_known": True,
        "balance_start_source": "snapshot",
    }


def check_ds1():
    import ftmo_daily as fd

    start, end = fd.ftmo_day_bounds_utc(date(2026, 9, 23))
    assert start == datetime(2026, 9, 22, 22, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 23, 22, 0, tzinfo=timezone.utc)
    return "summer bounds 2026-09-23"


def check_ds2():
    import ftmo_daily as fd

    start, end = fd.ftmo_day_bounds_utc(date(2026, 11, 10))
    assert start == datetime(2026, 11, 9, 23, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 10, 23, 0, tzinfo=timezone.utc)
    return "winter bounds 2026-11-10"


def check_ds3():
    import ftmo_daily as fd

    start, end = fd.ftmo_day_bounds_utc(date(2026, 10, 25))
    assert start == datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 25, 23, 0, tzinfo=timezone.utc)
    return "October switch 25h day"


def check_ds4():
    import ftmo_daily as fd

    start, end = fd.ftmo_day_bounds_utc(date(2026, 3, 29))
    assert start == datetime(2026, 3, 28, 23, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 3, 29, 22, 0, tzinfo=timezone.utc)
    return "March switch 23h day"


def check_ds5():
    import ftmo_daily as fd

    d1 = fd.ftmo_day_of_utc(datetime(2026, 9, 22, 21, 59, 59, tzinfo=timezone.utc))
    d2 = fd.ftmo_day_of_utc(datetime(2026, 9, 22, 22, 0, 0, tzinfo=timezone.utc))
    assert d1 == date(2026, 9, 22)
    assert d2 == date(2026, 9, 23)
    return "ftmo_day_of_utc boundary at 22:00Z summer"


def check_ds6():
    import ftmo_daily as fd

    assert fd.parse_ftmo_day("2026.09.23") == date(2026, 9, 23)
    assert fd.parse_ftmo_day("2026-09-23") == date(2026, 9, 23)
    try:
        fd.parse_ftmo_day("23/09/2026")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    return "parse_ftmo_day formats and rejection"


def check_ds7():
    import ftmo_daily as fd

    row = fd.snapshot_row_from_detail(full_snapshot_detail())
    assert row["account_login"] == 12345678
    assert row["ftmo_day"] == date(2026, 9, 23)
    assert row["balance_start"] == 100000.0
    assert row["equity_start"] == 100050.0
    assert row["inventory_pnl"] == 20.0
    assert row["total"] == 70.0
    assert row["swap_day"] == -1.5
    assert row["positions_long"] == 2
    assert row["breaker_tripped"] is False
    assert row["premidnight_seen"] is True
    assert row["broker_utc_offset_s"] == 10800
    assert row["balance_start_source"] == "snapshot"

    unknown = full_snapshot_detail()
    unknown["start_known"] = False
    unknown["equity_start"] = "999"
    unknown["inventory_pnl"] = "1"
    unknown["total"] = "2"
    unknown["swap_day"] = "3"
    row2 = fd.snapshot_row_from_detail(unknown)
    assert row2["equity_start"] is None
    assert row2["inventory_pnl"] is None
    assert row2["total"] is None
    assert row2["swap_day"] is None
    return "snapshot_row_from_detail contract mapping"


def check_ds8():
    import archive_worker as aw

    conn = FakeConnection()
    detail = full_snapshot_detail()
    del detail["account_login"]
    raw = make_daily_queue_item(detail)
    aw.insert_batch(conn, [raw])
    assert conn.commit_count == 1
    inserts = [e for e in conn.executed if "INSERT INTO" in e[0]]
    assert len(inserts) == 1
    assert "ea_events" in inserts[0][0]
    return "missing account_login skips snapshot, ea_events commits"


def check_ds9():
    import archive_worker as aw

    conn = FakeConnection()
    raw = make_daily_queue_item(full_snapshot_detail())
    aw.insert_batch(conn, [raw])
    assert conn.commit_count == 1
    inserts = [e for e in conn.executed if "INSERT INTO" in e[0]]
    assert len(inserts) == 2
    assert "ea_events" in inserts[0][0]
    assert "daily_snapshots" in inserts[1][0]
    assert "ON CONFLICT (account_login, ftmo_day) DO NOTHING" in inserts[1][0]
    return "valid DAILY_SNAPSHOT dual insert one commit"


def check_ds10():
    import archive_worker as aw

    item = {
        "type": "scalp",
        "instance_id": "GRIND_EURUSD_OPT",
        "received_at": "2026-09-23T12:00:00+00:00",
        "event": {
            "close_time": "2026-09-23 15:00:00",
            "instrument": "EURUSD",
            "direction": "L",
            "entry_price": 1.1,
            "exit_price": 1.11,
            "gross_pnl": 10.0,
            "ejected": True,
            "broker_utc_offset_s": 10800,
            "account_login": 12345678,
        },
    }
    table, row = aw.build_row(item)
    assert table == "scalp_history"
    assert row["ejected"] is True
    assert row["broker_utc_offset_s"] == 10800
    assert row["account_login"] == 12345678

    old_item = dict(item)
    old_item["event"] = {
        "close_time": "2026-09-23 15:00:00",
        "instrument": "EURUSD",
        "direction": "L",
        "entry_price": 1.1,
        "exit_price": 1.11,
        "gross_pnl": 10.0,
    }
    _, row2 = aw.build_row(old_item)
    assert row2["ejected"] is None
    assert row2["broker_utc_offset_s"] is None
    assert row2["account_login"] is None
    return "scalp ejected fields pass through or None"


def check_ds11():
    import ftmo_daily as fd

    start = datetime(2026, 9, 22, 22, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 23, 22, 0, tzinfo=timezone.utc)
    account = 12345678
    events = [
        ("EJECT_ACCEPTED", "INFO", {"source": "auto"}),
        ("EJECT_ACCEPTED", "INFO", {"source": "command"}),
        ("EJECT_FILLED", "INFO", {}),
        ("EJECT_FILLED", "INFO", {}),
        ("CARRY_PASS_SUMMARY", "INFO", {"clamped": 2}),
        ("CARRY_PASS_INCOMPLETE", "INFO", {"clamped": 1}),
        ("ANY_CODE", "CRITICAL", {}),
    ]
    inside1 = datetime(2026, 9, 23, 12, 0, 0)
    inside2 = datetime(2026, 9, 23, 1, 0, 0)
    outside = datetime(2026, 9, 24, 12, 0, 0)
    offset = 10800
    offset_only_inside = datetime(2026, 9, 24, 0, 30, 0)
    out_without_offset = datetime(2026, 9, 23, 0, 30, 0)
    scalps = [
        (inside1, offset, account, 5.0),
        (inside2, offset, account, 7.0),
        (outside, offset, account, 100.0),
        (inside1, None, account, 1.0),
        (inside1, offset, 99999999, 3.0),
        (offset_only_inside, offset, account, 11.0),
        (out_without_offset, offset, account, 13.0),
    ]
    counts = fd.derive_counts(events, scalps, start, end, account)
    assert counts["ejections_auto"] == 1
    assert counts["ejections_command"] == 1
    assert counts["eject_filled_events"] == 2
    assert counts["carry_clamps"] == 3
    assert counts["critical_events"] == 1
    assert counts["ejected_fills"] == 3
    assert counts["ejected_realised"] == 23.0
    assert counts["eject_mismatch"] == 1
    return "derive_counts fixture totals"


def check_ds12():
    import archive_worker as aw
    import ftmo_daily as fd

    conn = FakeConnection()
    conn.daily_snapshot_rows = []
    fixed_now = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)
    expected_cutoff = fd.ftmo_day_of_utc(fixed_now) - timedelta(days=7)

    aw.build_daily_derived(conn, now=fixed_now)
    cutoffs = [
        params[0]
        for sql, params in conn.executed
        if sql and "WHERE ftmo_day >=" in sql and params
    ]
    assert cutoffs[0] == expected_cutoff
    aw.build_daily_derived(conn, now=fixed_now)
    return "build_daily_derived selects ftmo_day >= today-7"


def check_ds13():
    import ftmo_daily as fd

    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 23, 11, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    rows = [
        ("INST1", "CRITICAL", "FOO", t1),
        ("INST1", "CRITICAL", "FOO", t2),
        ("INST1", "CRITICAL", "FOO", t3),
        ("INST1", "WARN", "STARTUP_EXIT_SHORTFALL", t2),
        ("INST1", "WARN", "STRAY_L0_CANCEL", t2),
    ]
    groups = fd.critical_groups(rows, now)
    assert len(groups) == 2
    assert groups[0]["level"] == "CRITICAL"
    assert groups[0]["count"] == 3
    assert groups[0]["first_at"] == t1
    assert groups[0]["last_at"] == t3
    assert groups[1]["level"] == "WARN"
    assert groups[1]["code"] == "STARTUP_EXIT_SHORTFALL"
    return "critical_groups merge, filter, sort"


def check_ds14():
    import app as pipshed
    import archive_worker as aw

    fake = FakeRedis()
    payload = {"generated_at": "2026-09-23T12:00:00+00:00", "rows": [{"ftmo_day": "2026-09-23"}]}
    fake.set(aw.ARCHIVE_DAILY_KEY, json.dumps(payload))
    fake.set(aw.ARCHIVE_CRITICAL_KEY, json.dumps({"generated_at": "2026-09-23T12:00:00+00:00", "rows": []}))
    pipshed.r = fake
    client = pipshed.app.test_client()

    resp = client.get("/api/g/wrong-token/daily")
    assert resp.status_code == 404
    resp = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/daily")
    assert resp.status_code == 200
    assert len(resp.get_json()["rows"]) == 1

    resp = client.get("/api/g/wrong-token/critical")
    assert resp.status_code == 404
    resp = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/critical")
    assert resp.status_code == 200

    fake2 = FakeRedis()
    pipshed.r = fake2
    resp = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/daily")
    body = resp.get_json()
    assert body["generated_at"] is None
    assert body["rows"] == []
    return "daily and critical public routes"


def check_ds15():
    import archive_worker as aw

    assert hasattr(aw, "batch_contains_daily_snapshot")
    assert aw.batch_contains_daily_snapshot([make_daily_queue_item(full_snapshot_detail())])

    fake = FakeRedis()
    fake._lists[aw.ARCHIVE_QUEUE] = [make_daily_queue_item(full_snapshot_detail())]
    fake._lists[aw.ARCHIVE_PROCESSING] = []
    conn = FakeConnection()
    conn.fail_on_sql = "WHERE ftmo_day >="
    conn.fail_on_sql_exc = psycopg2.DataError("daily derived failed")

    state = {"inserted_total": 0, "last_batch": None, "last_error": None}
    sleeps = []
    aw.worker_cycle(fake, conn, state, lambda s: sleeps.append(s))

    assert fake.llen(aw.ARCHIVE_QUEUE) == 0
    assert fake.llen(aw.ARCHIVE_PROCESSING) == 0
    assert conn.commit_count == 1
    return "DAILY_SNAPSHOT batch drains despite daily build DataError"


def check_ds16():
    import ftmo_daily as fd

    day = date(2026, 9, 23)
    ms_base = int(datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)
    fill_rows = []
    opt_positions = {101: (1001, 1002), 102: (2001, 2002), 103: (3001, 3002)}
    for ticket, (p1, p2) in opt_positions.items():
        fill_rows.append(("GRIND_EURUSD_OPT", ticket, p1, ms_base))
        fill_rows.append(("GRIND_EURUSD_OPT", ticket, p2, ms_base + 1))
    fill_rows.append(("GRIND_EURUSD_ALT", 201, 5001, ms_base))
    fill_rows.append(("GRIND_EURUSD_ALT", 201, 5002, ms_base))
    fill_rows.append(("GRIND_EURUSD_ALT", 202, 5003, ms_base))
    fill_rows.append(("GRIND_EURUSD_ALT", 202, 5004, ms_base))
    fill_rows.append(("GRIND_EURUSD_ALT", 203, 5005, ms_base))
    fill_rows.append(("GRIND_EURUSD_ALT", 203, 5006, ms_base))
    fill_rows.append(("GRIND_EURUSD_ALT", 204, 5007, ms_base))
    fill_rows.append(("GRIND_EURUSD_ALT", 204, 5008, ms_base))
    eject = {2001}
    counts = fd.s4_counts(fill_rows, eject, day)
    assert counts[("GRIND_EURUSD_OPT", day)] == 2
    assert counts[("GRIND_EURUSD_ALT", day)] == 4
    opt_instances = [k[0] for k in counts if k[0].endswith("_OPT")]
    alt = [k for k in counts if k[0].endswith("_ALT")]
    assert len(alt) == 1
    opt_vals = sorted(
        v for (inst, d), v in counts.items() if inst.endswith("_OPT") and d == day
    )
    median = opt_vals[len(opt_vals) // 2]
    assert counts[("GRIND_EURUSD_OPT", day)] / median == 1.0
    return "s4_counts CloseBy pairs and median ratio"


def check_ds17():
    import archive_worker as aw

    fake = FakeRedis()
    conn = FakeConnection()
    conn.fail_on_sql = "WHERE ftmo_day >="
    conn.fail_on_sql_exc = psycopg2.DataError("daily derived failed")
    result = aw.try_daily_build(conn, fake, force=True)
    assert result is None
    assert conn.rollback_count == 1

    conn2 = FakeConnection()
    conn2.fail_on_sql = "received_at > now()"
    conn2.fail_on_sql_exc = psycopg2.DataError("critical list failed")
    result2 = aw.try_critical_build(conn2, fake, force=True)
    assert result2 is None
    assert conn2.rollback_count == 1
    return "swallowed build errors roll back"


CHECKS = [
    ("DS1", check_ds1),
    ("DS2", check_ds2),
    ("DS3", check_ds3),
    ("DS4", check_ds4),
    ("DS5", check_ds5),
    ("DS6", check_ds6),
    ("DS7", check_ds7),
    ("DS8", check_ds8),
    ("DS9", check_ds9),
    ("DS10", check_ds10),
    ("DS11", check_ds11),
    ("DS12", check_ds12),
    ("DS13", check_ds13),
    ("DS14", check_ds14),
    ("DS15", check_ds15),
    ("DS16", check_ds16),
    ("DS17", check_ds17),
]


def main():
    passed = 0
    failed = 0
    for name, fn in CHECKS:
        try:
            msg = fn()
            print(f"{name} OK: {msg}")
            passed += 1
        except Exception as exc:
            print(f"{name} FAIL: {exc}")
            failed += 1
    print(f"SUMMARY passed={passed} failed={failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
