"""Verification for a second telemetry key during a key rotation (backlog C9, 1 Oct 2026).

Rules under test:
- every EA push endpoint (/api/telemetry/push, /action, /scalp_closed,
  /pod_closed) accepts `Bearer <TELEMETRY_API_KEY>` and, when
  TELEMETRY_API_KEY_NEXT is set, also `Bearer <TELEMETRY_API_KEY_NEXT>`;
- an EMPTY key never authorises anything (neither "Bearer " nor a
  missing header), current or next;
- each authorised push records WHICH key it used ("current" or "next",
  never the key itself) per instance in the Redis hash
  `fxmatrix:telemetry:key_slots`, so the changeover can be watched chart
  by chart; a refused push records nothing; a failure to record never
  changes the push's response;
- `GET /api/g/<token>/keyslots[/<anything>]` shows that hash (slot,
  endpoint, time per instance and counts per slot), never key text;
  a wrong token is 404;
- a non-ASCII Authorization header is a 401, not a 500.

Tests-first commit: KN2, KN6, KN7, KN8 and KN9 fail on the code before
the change; KN1, KN3, KN4, KN5, KN10, KN11 and KN12 are guards (they pass
before and after).
"""
import json
import os
import sys

import redis

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TOKEN = "k7m9p2x4q"
CUR = "cur-key-0123456789"
NXT = "next-key-9876543210"
SLOTS_KEY = "fxmatrix:telemetry:key_slots"

ACTION_BODY = {
    "instance_id": "GRIND_TEST_OPTB",
    "session_id": "s1",
    "events": [{"type": "send_log", "seq": 0, "ea_time_ms": 1}],
}
ENDPOINTS = [
    ("push", "/api/telemetry/push", {"instance_id": "GRIND_TEST_OPTB"}),
    ("action", "/api/telemetry/action", ACTION_BODY),
    ("scalp_closed", "/api/telemetry/scalp_closed", {"instance_id": "GRIND_TEST_OPTB"}),
    ("pod_closed", "/api/telemetry/pod_closed", {"instance_id": "GRIND_TEST_OPTB"}),
]


class MockPipeline:
    def __init__(self, mock):
        self._mock = mock
        self._ops = []

    def __getattr__(self, name):
        def op(*args):
            self._ops.append((name, args))
            return self
        return op

    def execute(self):
        out = []
        for name, args in self._ops:
            out.append(getattr(self._mock, name)(*args))
        self._ops = []
        return out


class MockRedis:
    def __init__(self):
        self.kv = {}
        self.lists = {}
        self.hashes = {}
        self.hset_raises = None

    def pipeline(self):
        return MockPipeline(self)

    def set(self, key, value, ex=None):
        self.kv[key] = value
        return True

    def get(self, key):
        return self.kv.get(key)

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    def ltrim(self, key, start, end):
        return True

    def expire(self, key, seconds):
        return True

    def lrange(self, key, start, end):
        items = self.lists.get(key, [])
        return items[start:] if end == -1 else items[start:end + 1]

    def hset(self, key, field, value):
        if self.hset_raises:
            raise self.hset_raises
        self.hashes.setdefault(key, {})[field] = value
        return 1

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))


import app as pipshed  # noqa: E402

client = pipshed.app.test_client()


def fresh(cur=CUR, nxt=None):
    mock = MockRedis()
    pipshed.r = mock
    pipshed.TELEMETRY_API_KEY = cur
    pipshed.TELEMETRY_API_KEY_NEXT = nxt
    return mock


def post(path, body, auth):
    headers = {} if auth is None else {"Authorization": auth}
    return client.post(path, json=body, headers=headers)


def codes(auth):
    return {name: post(path, body, auth).status_code for name, path, body in ENDPOINTS}


def check_kn1():
    fresh(CUR, NXT)
    got = codes(f"Bearer {CUR}")
    assert got == {n: 200 for n, _, _ in ENDPOINTS}, got
    return "current key 200 on all four endpoints (next set)"


def check_kn2():
    fresh(CUR, NXT)
    got = codes(f"Bearer {NXT}")
    assert got == {n: 200 for n, _, _ in ENDPOINTS}, got
    return "next key 200 on all four endpoints"


def check_kn3():
    for nxt in (None, ""):
        fresh(CUR, nxt)
        got = codes(f"Bearer {NXT}")
        assert got == {n: 401 for n, _, _ in ENDPOINTS}, (nxt, got)
    return "next key 401 when TELEMETRY_API_KEY_NEXT unset or empty"


def check_kn4():
    for cur, nxt in (("", None), ("", ""), (CUR, ""), ("", NXT)):
        fresh(cur, nxt)
        for auth in ("Bearer ", "Bearer", None, ""):
            got = codes(auth)
            assert got == {n: 401 for n, _, _ in ENDPOINTS}, (cur, nxt, auth, got)
    return "an empty key authorises nothing (16 combinations x 4 endpoints)"


def check_kn5():
    fresh(CUR, NXT)
    for auth in ("Bearer wrong", f"Bearer {CUR}x", f"Bearer {NXT[:-1]}", CUR, f"bearer {CUR}"):
        got = codes(auth)
        assert got == {n: 401 for n, _, _ in ENDPOINTS}, (auth, got)
    return "wrong, truncated, extended, unprefixed and lower-case keys 401"


def check_kn6():
    fresh("", NXT)
    got = codes(f"Bearer {NXT}")
    assert got == {n: 200 for n, _, _ in ENDPOINTS}, got
    return "next key alone (current empty) 200: the end state of a changeover"


def _slots(mock):
    raw = mock.hashes.get(SLOTS_KEY)
    assert raw is not None, "no key_slots hash written"
    return {k: json.loads(v) for k, v in raw.items()}


def check_kn7():
    mock = fresh(CUR, NXT)
    for name, path, body in ENDPOINTS:
        assert post(path, body, f"Bearer {CUR}").status_code == 200
        rec = _slots(mock)["GRIND_TEST_OPTB"]
        assert rec["slot"] == "current" and rec["endpoint"] == name, (name, rec)
        assert post(path, body, f"Bearer {NXT}").status_code == 200
        rec = _slots(mock)["GRIND_TEST_OPTB"]
        assert rec["slot"] == "next" and rec["endpoint"] == name, (name, rec)
        assert rec["at"].endswith("+00:00"), rec
    post("/api/telemetry/push", {"instance_id": "GRIND_OTHER_OPTC"}, f"Bearer {CUR}")
    assert _slots(mock)["GRIND_OTHER_OPTC"]["slot"] == "current"
    assert _slots(mock)["GRIND_TEST_OPTB"]["slot"] == "next"
    return "slot and endpoint recorded per instance on every endpoint"


def check_kn8():
    mock = fresh(CUR, NXT)
    for name, path, body in ENDPOINTS:
        post(path, body, f"Bearer {NXT}")
        post(path, body, f"Bearer {CUR}")
    raw = json.dumps(mock.hashes.get(SLOTS_KEY))
    assert mock.hashes.get(SLOTS_KEY), "no key_slots hash written"
    assert CUR not in raw and NXT not in raw and "Bearer" not in raw, raw
    resp = client.get(f"/api/g/{TOKEN}/keyslots/kn8")
    assert resp.status_code == 200, resp.status_code
    body = resp.get_data(as_text=True)
    assert CUR not in body and NXT not in body, body
    return "no key text in the hash or the read endpoint"


def check_kn9():
    mock = fresh(CUR, NXT)
    post("/api/telemetry/push", {"instance_id": "GRIND_A_OPTB"}, f"Bearer {CUR}")
    post("/api/telemetry/push", {"instance_id": "GRIND_B_OPTB"}, f"Bearer {NXT}")
    post("/api/telemetry/push", {"instance_id": "GRIND_C_OPTB"}, f"Bearer {NXT}")
    for path in (f"/api/g/{TOKEN}/keyslots", f"/api/g/{TOKEN}/keyslots/kn9"):
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.status_code)
        body = resp.get_json()
        assert body["counts"] == {"current": 1, "next": 2}, body["counts"]
        assert body["current_configured"] is True and body["next_configured"] is True, body
        assert set(body["instances"]) == {"GRIND_A_OPTB", "GRIND_B_OPTB", "GRIND_C_OPTB"}, body
        assert body["instances"]["GRIND_B_OPTB"]["slot"] == "next", body
        assert "generated_at" in body
    assert client.get("/api/g/wrongtoken/keyslots/kn9").status_code == 404
    pipshed.TELEMETRY_API_KEY_NEXT = ""
    body = client.get(f"/api/g/{TOKEN}/keyslots/kn9b").get_json()
    assert body["next_configured"] is False, body
    return "read endpoint: counts 1/2, instances, configured flags, 404 on a wrong token"


def check_kn10():
    fresh(CUR, NXT)
    for name, path, body in ENDPOINTS:
        resp = client.post(path, json=body, environ_overrides={"HTTP_AUTHORIZATION": "Bearer clé"})
        assert resp.status_code == 401, (name, resp.status_code)
    return "non-ASCII Authorization header 401 on all four endpoints"


def check_kn11():
    mock = fresh(CUR, NXT)
    mock.hset_raises = redis.ConnectionError("down")
    got = codes(f"Bearer {CUR}")
    assert got == {n: 200 for n, _, _ in ENDPOINTS}, got
    assert mock.kv.get("fxmatrix:state:GRIND_TEST_OPTB"), "push did not store state"
    return "a failing key-slot write leaves every push 200 and the state stored"


def check_kn12():
    mock = fresh(CUR, NXT)
    for auth in ("Bearer wrong", None):
        codes(auth)
    assert SLOTS_KEY not in mock.hashes, mock.hashes
    post("/api/telemetry/push", None, f"Bearer {CUR}")
    assert SLOTS_KEY not in mock.hashes, "a 400 (no JSON) recorded a slot"
    return "refused and invalid pushes record nothing"


CHECKS = [
    ("KN1", check_kn1), ("KN2", check_kn2), ("KN3", check_kn3), ("KN4", check_kn4),
    ("KN5", check_kn5), ("KN6", check_kn6), ("KN7", check_kn7), ("KN8", check_kn8),
    ("KN9", check_kn9), ("KN10", check_kn10), ("KN11", check_kn11), ("KN12", check_kn12),
]


def main():
    passed = failed = 0
    for name, fn in CHECKS:
        try:
            print(f"{name} OK: {fn()}")
            passed += 1
        except Exception as exc:
            print(f"{name} FAIL: {type(exc).__name__}: {exc}")
            failed += 1
    print(f"SUMMARY passed={passed} failed={failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
