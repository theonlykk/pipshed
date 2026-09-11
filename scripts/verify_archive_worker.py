"""Verification for archive_worker (FakeRedis + FakeConnection)."""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import psycopg2


class FakeRedis:
    def __init__(self):
        self._lists = {}
        self._kv = {}

    def _list(self, key):
        return self._lists.setdefault(key, [])

    def lmove(self, src, dest, src_pos, dest_pos):
        src_list = self._list(src)
        if not src_list:
            return None
        if src_pos == "LEFT":
            item = src_list.pop(0)
        elif src_pos == "RIGHT":
            item = src_list.pop()
        else:
            raise ValueError(f"unknown src_pos {src_pos}")
        dest_list = self._list(dest)
        if dest_pos == "LEFT":
            dest_list.insert(0, item)
        elif dest_pos == "RIGHT":
            dest_list.append(item)
        else:
            raise ValueError(f"unknown dest_pos {dest_pos}")
        return item

    def lrange(self, key, start, end):
        items = self._list(key)
        if end == -1:
            end = len(items) - 1
        if not items or start > end:
            return []
        return items[start : end + 1]

    def ltrim(self, key, start, end):
        items = self._list(key)
        if end == -1:
            end = len(items) - 1
        self._lists[key] = items[start : end + 1] if items and start <= end else []

    def rpush(self, key, value):
        self._list(key).append(value)
        return len(self._lists[key])

    def llen(self, key):
        return len(self._list(key))

    def set(self, key, value, ex=None):
        self._kv[key] = value

    def get(self, key):
        return self._kv.get(key)


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._last_sql = None
        self._last_params = None
        self.rowcount = 0

    def execute(self, sql, params=None):
        placeholders = re.findall(r"%\(([^)]+)\)s", sql)
        if isinstance(params, dict):
            for name in placeholders:
                if name not in params:
                    raise KeyError(name)
        self._last_sql = sql
        self._last_params = params
        self._conn.executed.append((sql.strip(), params))
        if sql.strip().startswith("DELETE"):
            self.rowcount = 3
        if self._conn.fail_on_statement and self._conn.fail_on_statement in sql:
            raise self._conn.fail_on_statement_error
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self):
        self.executed = []
        self.commit_count = 0
        self.rollback_count = 0
        self.fail_on_commit = False
        self.commit_failures_remaining = 0
        self.fail_on_statement = None
        self.fail_on_statement_error = psycopg2.DataError("bad data")
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        if self.fail_on_commit and self.commit_failures_remaining > 0:
            self.commit_failures_remaining -= 1
            raise psycopg2.OperationalError("commit failed")
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1

    def close(self):
        self.closed = True


def make_queue_item(event_type, event, instance_id="INST1", session_id="sess1"):
    return json.dumps({
        "type": event_type,
        "instance_id": instance_id,
        "session_id": session_id,
        "received_at": "2026-09-11T10:00:00.000000+00:00",
        "event": event,
    })


def test_w0_lmove():
    fake = FakeRedis()
    fake._lists["queue"] = ["a", "b", "c"]
    fake._lists["processing"] = []

    item = fake.lmove("queue", "processing", "LEFT", "RIGHT")
    assert item == "a"
    assert fake._lists["queue"] == ["b", "c"]
    assert fake._lists["processing"] == ["a"]

    item = fake.lmove("queue", "processing", "LEFT", "RIGHT")
    assert item == "b"
    assert fake._lists["processing"] == ["a", "b"]

    item = fake.lmove("empty", "processing", "LEFT", "RIGHT")
    assert item is None
    assert fake._lists["processing"] == ["a", "b"]
    print("W0 OK: FakeRedis lmove behaves atomically")


def test_w1_batch_insert():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import archive_worker as worker

    fake_redis = FakeRedis()
    conn = FakeConnection()
    conn_factory_calls = {"n": 0}

    def conn_factory():
        conn_factory_calls["n"] += 1
        return conn

    items = [
        make_queue_item("send_log", {"type": "send_log", "seq": 0, "ea_time_ms": 1, "action": "OPEN"}),
        make_queue_item("fill_log", {"type": "fill_log", "seq": 1, "ea_time_ms": 2, "deal_ticket": 99}),
        json.dumps({
            "type": "scalp",
            "instance_id": "INST1",
            "session_id": None,
            "received_at": "2026-09-11T10:00:00.000000+00:00",
            "event": {
                "close_time": "2026-09-11T03:46:27Z",
                "direction": "BUY",
                "entry_price": 1.1,
                "exit_price": 1.2,
            },
        }),
    ]
    fake_redis._lists[worker.ARCHIVE_QUEUE] = items[:]
    fake_redis._lists[worker.ARCHIVE_PROCESSING] = []

    state = {"inserted_total": 0}
    worker.worker_cycle(fake_redis, conn, state, lambda _s: None)

    inserts = [sql for sql, _ in conn.executed if sql.startswith("INSERT")]
    assert len(inserts) == 3
    for sql in inserts:
        assert "ON CONFLICT DO NOTHING" in sql
    assert conn.commit_count == 1
    assert fake_redis.llen(worker.ARCHIVE_QUEUE) == 0
    assert fake_redis.llen(worker.ARCHIVE_PROCESSING) == 0
    print("W1 OK: batch of 3 inserted once, queues empty")


def test_w2_scalp_close_time():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import archive_worker as worker

    fake_redis = FakeRedis()
    conn = FakeConnection()
    item = json.dumps({
        "type": "scalp",
        "instance_id": "INST1",
        "session_id": None,
        "received_at": "2026-09-11T10:00:00.000000+00:00",
        "event": {
            "close_time": "2026-09-11T03:46:27Z",
            "direction": "BUY",
            "entry_price": 1.1,
            "exit_price": 1.2,
        },
    })
    fake_redis._lists[worker.ARCHIVE_PROCESSING] = [item]

    state = {"inserted_total": 0}
    worker.worker_cycle(fake_redis, conn, state, lambda _s: None)

    _, params = conn.executed[-1]
    assert params["close_time_broker"] == datetime(2026, 9, 11, 3, 46, 27)
    assert params["source"] == "scalp_closed"
    print("W2 OK: scalp close_time parsed as naive broker timestamp")


def test_w3_operational_error_on_commit():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import archive_worker as worker

    fake_redis = FakeRedis()
    conn = FakeConnection()
    conn.fail_on_commit = True
    conn.commit_failures_remaining = 1
    sleeps = []

    item = make_queue_item("send_log", {"type": "send_log", "seq": 0, "ea_time_ms": 1})
    fake_redis._lists[worker.ARCHIVE_PROCESSING] = [item]

    state = {"inserted_total": 0}
    try:
        worker.process_processing_batch(fake_redis, conn, [item])
    except psycopg2.OperationalError:
        pass

    assert fake_redis.llen(worker.ARCHIVE_PROCESSING) == 1

    conn.fail_on_commit = False
    inserted = worker.process_processing_batch(fake_redis, conn, [item])
    assert inserted == 1
    assert fake_redis.llen(worker.ARCHIVE_PROCESSING) == 0

    attempt = worker.reconnect_with_backoff(1, sleeps.append)
    assert sleeps == [1]
    assert attempt == 2
    print("W3 OK: commit failure keeps processing, retry succeeds")


def test_w4_data_error_deadletter():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import archive_worker as worker

    fake_redis = FakeRedis()
    conn = FakeConnection()
    good = make_queue_item("send_log", {"type": "send_log", "seq": 0, "ea_time_ms": 1})
    bad = make_queue_item("fill_log", {"type": "fill_log", "seq": 1, "ea_time_ms": 2, "deal_ticket": 1})
    conn.fail_on_statement = "INSERT INTO fill_logs"
    fake_redis._lists[worker.ARCHIVE_PROCESSING] = [good, bad]

    inserted = worker.process_processing_batch(fake_redis, conn, [good, bad])
    assert inserted == 1
    assert fake_redis.llen(worker.ARCHIVE_PROCESSING) == 0
    assert fake_redis.llen(worker.ARCHIVE_DEADLETTER) == 1
    dead = json.loads(fake_redis.lrange(worker.ARCHIVE_DEADLETTER, 0, 0)[0])
    assert "error" in dead
    print("W4 OK: bad item deadlettered, good item committed")


def test_w5_startup_processing():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import archive_worker as worker

    fake_redis = FakeRedis()
    conn = FakeConnection()
    p1 = make_queue_item("send_log", {"type": "send_log", "seq": 0, "ea_time_ms": 1})
    p2 = make_queue_item("send_log", {"type": "send_log", "seq": 1, "ea_time_ms": 2})
    fake_redis._lists[worker.ARCHIVE_PROCESSING] = [p1, p2]
    fake_redis._lists[worker.ARCHIVE_QUEUE] = [
        make_queue_item("send_log", {"type": "send_log", "seq": 99, "ea_time_ms": 99}),
    ]

    state = {"inserted_total": 0}
    worker.worker_cycle(fake_redis, conn, state, lambda _s: None)

    inserts = [params for sql, params in conn.executed if sql.startswith("INSERT")]
    assert len(inserts) == 2
    assert inserts[0]["seq"] == 0
    assert inserts[1]["seq"] == 1
    assert fake_redis.llen(worker.ARCHIVE_QUEUE) == 1
    print("W5 OK: processing backlog drained before queue")


def test_w6_retention():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import archive_worker as worker

    fake_redis = FakeRedis()
    conn = FakeConnection()

    deleted = worker.run_retention_if_due(conn, fake_redis)
    assert deleted is not None
    deletes = [sql for sql, _ in conn.executed if sql.startswith("DELETE")]
    assert len(deletes) == 2
    assert fake_redis.get(worker.ARCHIVE_RETENTION_LAST) is not None
    conn.executed.clear()

    deleted_again = worker.run_retention_if_due(conn, fake_redis)
    assert deleted_again is None
    assert len([sql for sql, _ in conn.executed if sql.startswith("DELETE")]) == 0

    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    fake_redis.set(worker.ARCHIVE_RETENTION_LAST, old)
    conn.executed.clear()
    deleted_old = worker.run_retention_if_due(conn, fake_redis)
    assert deleted_old is not None
    assert len([sql for sql, _ in conn.executed if sql.startswith("DELETE")]) == 2
    print("W6 OK: retention runs at most once per 24h")


def test_w7_invalid_json_deadletter():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import archive_worker as worker

    fake_redis = FakeRedis()
    conn = FakeConnection()
    fake_redis._lists[worker.ARCHIVE_PROCESSING] = ["not-json"]

    inserted = worker.process_processing_batch(fake_redis, conn, ["not-json"])
    assert inserted == 0
    assert fake_redis.llen(worker.ARCHIVE_DEADLETTER) == 1
    assert fake_redis.llen(worker.ARCHIVE_PROCESSING) == 0
    print("W7 OK: invalid JSON deadlettered")


class _Stop(BaseException):
    pass


def test_w8_live_scalp_payload():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import archive_worker as worker

    fake_redis = FakeRedis()
    conn = FakeConnection()
    live_event = {
        "close_time": "2026-09-11T03:46:27Z",
        "direction": "BUY",
        "entry_price": 1.1050,
        "exit_price": 1.1060,
        "gross_pnl": 1.0,
        "instance_id": "GRIND_EURUSD_OPT",
        "instrument": "EURUSD",
        "layer_depth": 1,
        "stack_depth": 1,
    }
    item = json.dumps({
        "type": "scalp",
        "instance_id": "GRIND_EURUSD_OPT",
        "session_id": None,
        "received_at": "2026-09-11T10:00:00.000000+00:00",
        "event": live_event,
    })
    fake_redis._lists[worker.ARCHIVE_QUEUE] = [item]
    fake_redis._lists[worker.ARCHIVE_PROCESSING] = []

    state = {"inserted_total": 0}
    worker.worker_cycle(fake_redis, conn, state, lambda _s: None)

    scalp_inserts = [
        params for sql, params in conn.executed
        if sql.startswith("INSERT") and "scalp_history" in sql
    ]
    assert len(scalp_inserts) == 1
    params = scalp_inserts[0]
    assert params["entry_deal_ticket"] is None
    assert params["exit_deal_ticket"] is None
    assert conn.commit_count == 1
    assert fake_redis.llen(worker.ARCHIVE_PROCESSING) == 0
    print("W8 OK: live scalp payload inserts with null deal tickets")


def test_w9_keyerror_deadletter():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import archive_worker as worker

    fake_redis = FakeRedis()
    conn = FakeConnection()
    bad = json.dumps({
        "type": "send_log",
        "instance_id": "INST1",
        "session_id": "sess1",
        "event": {"type": "send_log", "seq": 0, "ea_time_ms": 1},
    })
    good = make_queue_item(
        "ea_event",
        {"type": "ea_event", "seq": 1, "ea_time_ms": 2, "level": "INFO", "code": "X"},
    )
    fake_redis._lists[worker.ARCHIVE_PROCESSING] = [bad, good]

    inserted = worker.process_processing_batch(fake_redis, conn, [bad, good])
    assert inserted == 1
    assert fake_redis.llen(worker.ARCHIVE_PROCESSING) == 0
    assert fake_redis.llen(worker.ARCHIVE_DEADLETTER) == 1
    dead = json.loads(fake_redis.lrange(worker.ARCHIVE_DEADLETTER, 0, 0)[0])
    assert dead["error"]
    assert "KeyError" in dead["error"]
    print("W9 OK: KeyError item deadlettered, valid item inserted")


def test_w10_startup_postgres_down():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import archive_worker as worker

    fake_redis = FakeRedis()
    conn = FakeConnection()
    factory_calls = [0]
    sleeps = []

    def conn_factory():
        factory_calls[0] += 1
        if factory_calls[0] <= 3:
            raise psycopg2.OperationalError("postgres down")
        return conn

    item = make_queue_item("send_log", {"type": "send_log", "seq": 0, "ea_time_ms": 1})
    fake_redis._lists[worker.ARCHIVE_QUEUE] = [item]
    fake_redis._lists[worker.ARCHIVE_PROCESSING] = []

    def sleep_fn(seconds):
        sleeps.append(seconds)

    original_commit = conn.commit

    def commit_and_stop():
        original_commit()
        if any(sql.startswith("INSERT") for sql, _ in conn.executed):
            raise _Stop()

    conn.commit = commit_and_stop

    state = {"inserted_total": 0, "last_error": None}
    try:
        worker.worker_loop(fake_redis, conn_factory, sleep_fn)
    except _Stop:
        pass

    assert sleeps == [1, 2, 4]
    assert len([sql for sql, _ in conn.executed if sql.startswith("INSERT")]) == 1
    print("W10 OK: startup postgres down retries with sleeps [1, 2, 4]")


def test_w11_mid_run_outage():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import archive_worker as worker

    fake_redis = FakeRedis()
    conn1 = FakeConnection()
    conn1.fail_on_commit = True
    conn1.commit_failures_remaining = 1
    conn2 = FakeConnection()
    factory_calls = [0]
    sleeps = []

    def conn_factory():
        factory_calls[0] += 1
        if factory_calls[0] == 1:
            return conn1
        if factory_calls[0] <= 4:
            raise psycopg2.OperationalError("postgres down")
        return conn2

    item = make_queue_item("send_log", {"type": "send_log", "seq": 0, "ea_time_ms": 1})
    fake_redis._lists[worker.ARCHIVE_PROCESSING] = [item]

    def sleep_fn(seconds):
        sleeps.append(seconds)

    original_batch = worker.process_processing_batch

    def batch_and_stop(redis_client, conn, raw_items):
        inserted = original_batch(redis_client, conn, raw_items)
        if inserted > 0 and conn is conn2:
            raise _Stop()
        return inserted

    worker.process_processing_batch = batch_and_stop

    state = {"inserted_total": 0, "last_error": None}
    try:
        worker.worker_loop(fake_redis, conn_factory, sleep_fn)
    except _Stop:
        pass
    finally:
        worker.process_processing_batch = original_batch

    assert sleeps == [1, 2, 4]
    assert len([sql for sql, _ in conn2.executed if sql.startswith("INSERT")]) == 1
    assert fake_redis.llen(worker.ARCHIVE_PROCESSING) == 0
    print("W11 OK: mid-run outage retries with sleeps [1, 2, 4]")


def main():
    test_w0_lmove()
    test_w1_batch_insert()
    test_w2_scalp_close_time()
    test_w3_operational_error_on_commit()
    test_w4_data_error_deadletter()
    test_w5_startup_processing()
    test_w6_retention()
    test_w7_invalid_json_deadletter()
    test_w8_live_scalp_payload()
    test_w9_keyerror_deadletter()
    test_w10_startup_postgres_down()
    test_w11_mid_run_outage()
    print("All archive worker checks passed.")


if __name__ == "__main__":
    main()
