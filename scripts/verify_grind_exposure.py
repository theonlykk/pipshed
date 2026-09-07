"""Verification for grind inclusion in macro net_exposure (mock Redis)."""
import json
import math
import os
import sys


class MockRedis:
    def __init__(self):
        self._data = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value, ex=None):
        self._data[key] = value

    def lrange(self, key, start, end):
        return []


def v2_payload(symbol, direction, lot=0.01):
    return json.dumps({
        "engine_state": {"account_daily_api_count": 42},
        "active_pods": {
            symbol: {
                "layers": 1,
                "net_pnl": 0.0,
                "layer_detail": [{"direction": direction, "lot_size": lot}],
            }
        },
        "working_orders": {},
        "system_alerts": [],
    })


def grind_payload(open_long=0, open_short=0):
    return json.dumps({
        "open_layers_long": open_long,
        "open_layers_short": open_short,
        "api_count": 11,
    })


def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()

    # 4d baseline — v2 only, no grind
    mock.set("fxmatrix:state:MM_SHORT_EURGBP", v2_payload("EURGBP", -1, 0.01))
    baseline = client.get("/api/telemetry/aggregate").get_json()
    baseline_exposure = dict(baseline["net_exposure"])
    assert baseline_exposure.get("EURGBP") == -0.01
    print("4d OK: v2-only EURGBP net exposure -0.01")

    # 4a — live state: v2 0.01 short + grind OPT 0.01 + grind ALT 0.01 = 0.03 short
    mock.set(
        "fxmatrix:state:GRIND_EURGBP_OPT",
        grind_payload(open_short=1),
    )
    mock.set(
        "fxmatrix:state:GRIND_EURGBP_ALT",
        grind_payload(open_short=1),
    )
    resp = client.get("/api/telemetry/aggregate").get_json()
    eurgbp = resp["net_exposure"]["EURGBP"]
    assert eurgbp == -0.03, f"expected -0.03, got {eurgbp}"
    print("4a OK: EURGBP net exposure -0.03 (v2 + grind OPT + grind ALT)")

    # 4b — bidirectional instance nets within instance
    mock.set("fxmatrix:state:GRIND_GBPUSD_OPT", grind_payload(open_long=2, open_short=1))
    resp = client.get("/api/telemetry/aggregate").get_json()
    gbp = resp["net_exposure"].get("GBPUSD", 0.0)
    assert gbp == 0.01, f"expected +0.01 net long (2L-1S)*0.01, got {gbp}"
    print("4b OK: grind 2 long / 1 short nets to +0.01 lots on GBPUSD")

    # 4c — zero layers contributes 0.0, no NaN
    mock.set("fxmatrix:state:GRIND_EURUSD_OPT", grind_payload(open_long=0, open_short=0))
    resp = client.get("/api/telemetry/aggregate").get_json()
    eurusd = resp["net_exposure"].get("EURUSD", 0.0)
    assert eurusd == 0.0
    assert not math.isnan(eurusd)
    print("4c OK: zero-layer grind contributes 0.0 on EURUSD")

    # v2 exposure unchanged when grind added for other symbols — EURGBP still -0.03
    assert resp["net_exposure"]["EURGBP"] == -0.03
    print("4d OK: v2 EURGBP component still present in combined figure")

    # unknown symbol skipped
    net = {}
    pipshed._accumulate_grind_net_exposure(
        net, "GRIND_XXXYYY_OPT", {"open_layers_long": 5, "open_layers_short": 0}
    )
    assert net == {}
    print("Symbol guard OK: unknown grind symbol skipped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
