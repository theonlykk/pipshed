"""Verification for carry table worker publish and public Redis route."""
import json
import os
import sys
from datetime import datetime, timezone

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
    CARRY_COLUMNS = (
        "symbol", "swap_long", "swap_short", "long_pips", "short_pips",
        "multiplier", "rollover3days", "swap_mode", "digits",
        "trade_mode_full", "received_at",
    )

    def __init__(self, conn):
        self._conn = conn
        self._last_sql = None

    def execute(self, sql, params=None):
        self._last_sql = sql
        if self._conn.fail_on_carry_sql and "CARRY_SNAPSHOT" in sql:
            raise self._conn.fail_on_carry_sql
        if self._conn.fail_on_insert and "INSERT INTO" in sql:
            raise self._conn.fail_on_insert
        return self

    def fetchall(self):
        if self._last_sql and "CARRY_SNAPSHOT" in self._last_sql:
            return list(self._conn.carry_rows)
        return []

    @property
    def description(self):
        return [(name,) for name in self.CARRY_COLUMNS]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self):
        self.carry_rows = []
        self.fail_on_carry_sql = None
        self.fail_on_insert = None
        self.commit_count = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        pass

    def close(self):
        pass


def make_carry_queue_item(code="CARRY_SNAPSHOT"):
    return json.dumps({
        "type": "ea_event",
        "instance_id": "GRIND_EURUSD_OPT",
        "session_id": "sess1",
        "received_at": "2026-09-11T22:34:00.000000+00:00",
        "event": {
            "seq": 1,
            "ea_time_ms": 1,
            "magic": 22260101,
            "level": "INFO",
            "code": code,
            "reason": "EURUSD",
            "ticket": 0,
            "detail": {"symbol": "EURUSD", "long_pips": "-0.876"},
        },
    })


def test_ct1_build_carry_table_types():
    import archive_worker as aw

    conn = FakeConnection()
    conn.carry_rows = [
        (
            "EURUSD", "-8.76", "0.37", "-0.876", "0.037", "3", "3", "1", "5",
            "true", datetime(2026, 9, 11, 22, 34, tzinfo=timezone.utc),
        ),
        (
            "GBPUSD", "-6.50", "0.20", "-0.650", "0.020", "1", "3", "1", "5",
            "false", datetime(2026, 9, 11, 22, 34, tzinfo=timezone.utc),
        ),
    ]
    table = aw.build_carry_table(conn)
    assert len(table["rows"]) == 2
    row0 = table["rows"][0]
    assert row0["symbol"] == "EURUSD"
    assert isinstance(row0["swap_long_pts"], float)
    assert isinstance(row0["long_pips"], float)
    assert isinstance(row0["mult"], int)
    assert row0["trade_mode_full"] is True
    assert row0["snapshot_at"] is not None
    row1 = table["rows"][1]
    assert row1["trade_mode_full"] is False
    print("CT1 OK: build_carry_table maps two rows with correct types")


def test_ct2_long_week_pips():
    import archive_worker as aw

    conn = FakeConnection()
    conn.carry_rows = [
        (
            "EURUSD", "-8.76", "0.37", "-0.876", "0.037", "1", "3", "1", "5",
            "true", datetime(2026, 9, 11, 22, 34, tzinfo=timezone.utc),
        ),
    ]
    table = aw.build_carry_table(conn)
    row = table["rows"][0]
    assert row["long_week_pips"] == -6.13
    assert row["short_week_pips"] == round(0.037 * 7, 2)
    print("CT2 OK: long_week_pips == round(long_pips * 7, 2)")


def test_ct3_skip_null_symbol():
    import archive_worker as aw

    conn = FakeConnection()
    conn.carry_rows = [
        (
            None, "-8.76", "0.37", "-0.876", "0.037", "1", "3", "1", "5",
            "true", datetime(2026, 9, 11, 22, 34, tzinfo=timezone.utc),
        ),
        (
            "EURUSD", "-8.76", "0.37", "-0.876", "0.037", "1", "3", "1", "5",
            "true", datetime(2026, 9, 11, 22, 34, tzinfo=timezone.utc),
        ),
    ]
    table = aw.build_carry_table(conn)
    assert len(table["rows"]) == 1
    assert table["rows"][0]["symbol"] == "EURUSD"
    print("CT3 OK: null symbol row skipped")


def test_ct4_publish_carry_table():
    import archive_worker as aw

    fake = FakeRedis()
    table = {
        "generated_at": "2026-09-11T22:34:00+00:00",
        "rows": [{"symbol": "EURUSD", "long_pips": -0.876}],
    }
    aw.publish_carry_table(fake, table)
    raw = fake.get(aw.ARCHIVE_CARRY_KEY)
    parsed = json.loads(raw)
    assert len(parsed["rows"]) == 1
    assert parsed["rows"][0]["symbol"] == "EURUSD"
    print("CT4 OK: publish_carry_table round-trips through json.loads")


def test_ct5_public_carry_route():
    import app as pipshed
    import archive_worker as aw

    fake = FakeRedis()
    payload = {
        "generated_at": "2026-09-11T22:34:00+00:00",
        "rows": [{"symbol": "EURUSD", "long_pips": -0.876}],
    }
    fake.set(aw.ARCHIVE_CARRY_KEY, json.dumps(payload))
    pipshed.r = fake
    client = pipshed.app.test_client()

    resp = client.get("/api/g/wrong-token/carry")
    assert resp.status_code == 404

    resp = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/carry")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["rows"]) == 1
    assert body["rows"][0]["symbol"] == "EURUSD"
    print("CT5 OK: route 404 wrong token, 200 with table for right token")


def test_ct6_absent_carry_key():
    import app as pipshed

    fake = FakeRedis()
    pipshed.r = fake
    client = pipshed.app.test_client()

    resp = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/carry")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["generated_at"] is None
    assert body["rows"] == []
    print("CT6 OK: absent Redis key returns empty table with generated_at null")


def test_ct7_carry_build_failure_does_not_stop_drain():
    import archive_worker as aw

    fake = FakeRedis()
    fake._lists[aw.ARCHIVE_QUEUE] = [make_carry_queue_item()]
    fake._lists[aw.ARCHIVE_PROCESSING] = []
    conn = FakeConnection()
    conn.fail_on_carry_sql = psycopg2.DataError("carry sql failed")

    state = {"inserted_total": 0, "last_batch": None, "last_error": None}
    sleeps = []
    aw.worker_cycle(fake, conn, state, lambda s: sleeps.append(s))

    assert fake.llen(aw.ARCHIVE_QUEUE) == 0
    assert fake.llen(aw.ARCHIVE_PROCESSING) == 0
    assert conn.commit_count == 1
    print("CT7 OK: carry build failure does not stop queue drain")


def main():
    test_ct1_build_carry_table_types()
    test_ct2_long_week_pips()
    test_ct3_skip_null_symbol()
    test_ct4_publish_carry_table()
    test_ct5_public_carry_route()
    test_ct6_absent_carry_key()
    test_ct7_carry_build_failure_does_not_stop_drain()
    print("All carry table checks passed.")


if __name__ == "__main__":
    main()
