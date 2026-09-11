"""Verification for archive tap on telemetry_scalp_closed (mock Redis)."""
import json
import os
import sys


class MockPipeline:
    def __init__(self, mock_redis):
        self._mock = mock_redis
        self._ops = []

    def lpush(self, key, value):
        self._ops.append(("lpush", key, value))
        return self

    def ltrim(self, key, start, end):
        self._ops.append(("ltrim", key, start, end))
        return self

    def expire(self, key, seconds):
        self._ops.append(("expire", key, seconds))
        return self

    def rpush(self, key, value):
        self._ops.append(("rpush", key, value))
        return self

    def execute(self):
        for op, key, *args in self._ops:
            if op == "lpush":
                self._mock._lists.setdefault(key, []).insert(0, args[0])
            elif op == "ltrim":
                start, end = args
                items = self._mock._lists.get(key, [])
                if end == -1:
                    end = len(items) - 1
                self._mock._lists[key] = items[start : end + 1] if items else []
            elif op == "rpush":
                self._mock._lists.setdefault(key, []).append(args[0])
        self._ops = []
        return []


class MockRedis:
    def __init__(self):
        self._lists = {}

    def pipeline(self):
        return MockPipeline(self)

    def llen(self, key):
        return len(self._lists.get(key, []))

    def lrange(self, key, start, end):
        items = self._lists.get(key, [])
        if end == -1:
            end = len(items) - 1
        if not items:
            return []
        return items[start : end + 1]


def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    pipshed.TELEMETRY_API_KEY = "test-telemetry-key"
    client = pipshed.app.test_client()

    payload = {
        "instance_id": "GRIND_EURUSD_OPT",
        "close_time": "2026-09-11T03:46:27Z",
        "direction": "BUY",
        "entry_price": 1.1050,
        "exit_price": 1.1060,
        "gross_pnl": 1.0,
        "layer_depth": 1,
        "stack_depth": 1,
        "instrument": "EURUSD",
    }

    resp = client.post(
        "/api/telemetry/scalp_closed",
        json=payload,
        headers={"Authorization": "Bearer test-telemetry-key"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"

    scalp_key = "fxmatrix:scalp_history:GRIND_EURUSD_OPT"
    archive_key = pipshed.ARCHIVE_QUEUE_KEY
    assert mock.llen(scalp_key) == 1
    stored_scalp = json.loads(mock.lrange(scalp_key, 0, 0)[0])
    assert stored_scalp == payload
    print("scalp list OK: 1 entry unchanged")

    assert mock.llen(archive_key) == 1
    archive_item = json.loads(mock.lrange(archive_key, 0, 0)[0])
    assert archive_item["type"] == "scalp"
    assert archive_item["instance_id"] == "GRIND_EURUSD_OPT"
    assert archive_item["session_id"] is None
    assert archive_item["event"] == payload
    assert archive_item["received_at"].endswith("+00:00")
    print("archive queue OK: 1 scalp item with session_id null")

    print("All archive scalp tap checks passed.")


if __name__ == "__main__":
    main()
