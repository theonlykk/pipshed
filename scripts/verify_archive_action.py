"""Verification for POST /api/telemetry/action (mock Redis)."""
import json
import os
import sys

import redis


class MockPipeline:
    def __init__(self, mock_redis):
        self._mock = mock_redis
        self._ops = []

    def rpush(self, key, value):
        self._ops.append(("rpush", key, value))
        return self

    def execute(self):
        if self._mock._pipeline_raises:
            raise self._mock._pipeline_raises
        count = len(self._ops)
        for op, key, value in self._ops:
            if op == "rpush":
                self._mock._lists.setdefault(key, []).append(value)
        self._ops = []
        return [None] * count


class MockRedis:
    def __init__(self):
        self._lists = {}
        self._pipeline_raises = None

    def pipeline(self):
        return MockPipeline(self)

    def llen(self, key):
        return len(self._lists.get(key, []))

    def lrange(self, key, start, end):
        items = self._lists.get(key, [])
        if end == -1:
            end = len(items) - 1
        if not items or start >= len(items):
            return []
        return items[start : end + 1]


def auth_headers():
    return {"Authorization": "Bearer test-telemetry-key"}


def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    pipshed.TELEMETRY_API_KEY = "test-telemetry-key"
    client = pipshed.app.test_client()
    queue_key = pipshed.ARCHIVE_QUEUE_KEY

    resp = client.post("/api/telemetry/action", json={"events": []})
    assert resp.status_code == 401
    print("401 OK: missing Bearer key")

    resp = client.post(
        "/api/telemetry/action",
        data="not json",
        headers={**auth_headers(), "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Invalid JSON"
    print("400 OK: body not JSON")

    resp = client.post(
        "/api/telemetry/action",
        json={"session_id": "s1", "events": [{"type": "send_log", "seq": 0, "ea_time_ms": 1}]},
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "instance_id required"
    print("400 OK: instance_id missing")

    resp = client.post(
        "/api/telemetry/action",
        json={"instance_id": "", "session_id": "s1", "events": [{"type": "send_log", "seq": 0, "ea_time_ms": 1}]},
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "instance_id required"
    print("400 OK: instance_id empty")

    resp = client.post(
        "/api/telemetry/action",
        json={"instance_id": "INST1", "events": [{"type": "send_log", "seq": 0, "ea_time_ms": 1}]},
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "session_id required"
    print("400 OK: session_id missing")

    resp = client.post(
        "/api/telemetry/action",
        json={"instance_id": "INST1", "session_id": "", "events": [{"type": "send_log", "seq": 0, "ea_time_ms": 1}]},
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "session_id required"
    print("400 OK: session_id empty")

    resp = client.post(
        "/api/telemetry/action",
        json={"instance_id": "INST1", "session_id": "s1"},
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "events required"
    print("400 OK: events missing")

    resp = client.post(
        "/api/telemetry/action",
        json={"instance_id": "INST1", "session_id": "s1", "events": "bad"},
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "events must be a list"
    print("400 OK: events not a list")

    resp = client.post(
        "/api/telemetry/action",
        json={"instance_id": "INST1", "session_id": "s1", "events": []},
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "events must not be empty"
    print("400 OK: events empty")

    resp = client.post(
        "/api/telemetry/action",
        json={
            "instance_id": "INST1",
            "session_id": "s1",
            "events": [{"type": "send_log", "seq": 0, "ea_time_ms": 1}] * 501,
        },
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "events exceeds maximum"
    print("400 OK: 501 events")

    resp = client.post(
        "/api/telemetry/action",
        json={"instance_id": "INST1", "session_id": "s1", "events": ["bad"]},
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "event must be an object"
    print("400 OK: event not object")

    resp = client.post(
        "/api/telemetry/action",
        json={
            "instance_id": "INST1",
            "session_id": "s1",
            "events": [{"type": "unknown", "seq": 0, "ea_time_ms": 1}],
        },
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "unknown event type"
    print("400 OK: unknown type")

    resp = client.post(
        "/api/telemetry/action",
        json={
            "instance_id": "INST1",
            "session_id": "s1",
            "events": [{"type": "send_log", "seq": -1, "ea_time_ms": 1}],
        },
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "seq must be a non-negative integer"
    print("400 OK: seq negative")

    resp = client.post(
        "/api/telemetry/action",
        json={
            "instance_id": "INST1",
            "session_id": "s1",
            "events": [{"type": "send_log", "seq": True, "ea_time_ms": 1}],
        },
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "seq must be a non-negative integer"
    print("400 OK: seq bool")

    resp = client.post(
        "/api/telemetry/action",
        json={
            "instance_id": "INST1",
            "session_id": "s1",
            "events": [{"type": "send_log", "seq": 0, "ea_time_ms": 1.5}],
        },
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "ea_time_ms must be an integer"
    print("400 OK: ea_time_ms not int")

    resp = client.post(
        "/api/telemetry/action",
        json={
            "instance_id": "INST1",
            "session_id": "s1",
            "events": [{"type": "send_log", "seq": 0, "ea_time_ms": True}],
        },
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "ea_time_ms must be an integer"
    print("400 OK: ea_time_ms bool")

    events = [
        {"type": "send_log", "seq": 0, "ea_time_ms": 100, "action": "OPEN"},
        {"type": "fill_log", "seq": 1, "ea_time_ms": 101, "deal_ticket": 42},
        {"type": "ea_event", "seq": 2, "ea_time_ms": 102, "level": "INFO", "code": "X"},
    ]
    resp = client.post(
        "/api/telemetry/action",
        json={"instance_id": "INST1", "session_id": "sess-abc", "events": events},
        headers=auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["queued"] == 3
    assert mock.llen(queue_key) == 3
    for idx, raw in enumerate(mock.lrange(queue_key, 0, -1)):
        item = json.loads(raw)
        assert item["instance_id"] == "INST1"
        assert item["session_id"] == "sess-abc"
        assert item["type"] == events[idx]["type"]
        assert item["received_at"].endswith("+00:00")
        assert item["event"] == events[idx]
    print("200 OK: 3 events queued with correct envelope")

    mock._lists = {}
    mock._pipeline_raises = redis.ConnectionError("down")
    resp = client.post(
        "/api/telemetry/action",
        json={
            "instance_id": "INST1",
            "session_id": "s1",
            "events": [{"type": "send_log", "seq": 0, "ea_time_ms": 1}],
        },
        headers=auth_headers(),
    )
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "queue unavailable"
    assert mock.llen(queue_key) == 0
    print("503 OK: pipeline failure leaves queue empty")

    resp = client.post(
        "/api/telemetry/action",
        json=[1, 2],
        headers=auth_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "body must be an object"
    print("A1 OK: non-object JSON body returns 400")

    print("All archive action checks passed.")


if __name__ == "__main__":
    main()
