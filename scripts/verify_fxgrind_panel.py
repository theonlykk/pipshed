"""Local verification for fxgrind panel (no Redis required — in-memory mock)."""
import json
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


def sample_v2_payload(api_count=42, net_pnl=123.45):
    return json.dumps({
        "engine_state": {
            "account_daily_api_count": api_count,
            "account_daily_api_warning": False,
            "intraday_mae_usd": -50.0,
        },
        "active_pods": {
            "GBPUSD": {
                "net_pnl": net_pnl,
                "layer_detail": [
                    {"direction": 1, "lot_size": 0.1},
                    {"direction": -1, "lot_size": 0.05},
                ],
            }
        },
        "working_orders": {},
        "system_alerts": [],
    })


def sample_grind_payload(halted=False, invariant_ok=True, peer_read_failed=False):
    return json.dumps({
        "instance_id": "GRIND_GBPUSD_OPT",
        "open_layers_long": 2,
        "open_layers_short": 1,
        "fills": 10,
        "scalps": 5,
        "api_count": 99,
        "api_counter_broken": False,
        "cap_blocked": False,
        "halted": halted,
        "halt_reason": "test halt" if halted else "",
        "recon_ok": True,
        "invariant_ok": invariant_ok,
        "cap_leg_a": 1.25,
        "cap_leg_b": 0.75,
        "cap_total_leg_a": 10.0,
        "cap_total_leg_b": 8.0,
        "peer_read_failed": peer_read_failed,
        "magic": 123456789,
        "slot": "OPT",
        "width_pips": 5.0,
        "add_pips": 10.0,
        "exit_pips": 5.0,
        "max_layers": 5,
        "cap_leg_a_name": "GBP",
        "cap_leg_b_name": "USD",
    })


def main():
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()

    # Seed one live v2 instance for aggregate regression baseline
    mock.set("fxmatrix:state:MM_LONG_V2", sample_v2_payload(api_count=42, net_pnl=123.45))

    # 4a — no grind data
    resp = client.get("/api/telemetry/aggregate")
    assert resp.status_code == 200
    baseline = resp.get_json()
    grind = baseline.get("grind_cards", {})
    assert len(grind) == 6
    assert all(c["connection"] == "no_data" for c in grind.values())
    assert "grind_cards" in baseline
    # existing keys present
    for key in (
        "net_exposure", "system_alerts", "instance_status", "instance_cards",
        "arm_summaries", "best_quotes", "full_best_quotes",
        "account_daily_api_count", "account_daily_api_warning",
        "account_daily_api_limit", "intraday_mae",
    ):
        assert key in baseline, f"missing key {key}"
    print("4a OK: grind_cards all no_data; existing aggregate keys unchanged")

    baseline_api = baseline["account_daily_api_count"]
    baseline_exposure = dict(baseline["net_exposure"])
    baseline_mae = baseline["intraday_mae"]

    # 4b — grind live, not halted
    mock.set("fxmatrix:state:GRIND_GBPUSD_OPT", sample_grind_payload(halted=False))
    resp = client.get("/api/telemetry/aggregate")
    data = resp.get_json()
    card = data["grind_cards"]["GRIND_GBPUSD_OPT"]
    assert card["connection"] == "live"
    assert card["open_layers_long"] == 2
    assert card["open_layers_short"] == 1
    assert card["halted"] is False
    assert card["slot"] == "OPT"
    assert card["width_pips"] == 5.0
    print("4b OK (halted=false): grind card fields populated correctly")

    # 4b — halted + invariant fail + peer read fail
    mock.set(
        "fxmatrix:state:GRIND_GBPUSD_OPT",
        sample_grind_payload(halted=True, invariant_ok=False, peer_read_failed=True),
    )
    resp = client.get("/api/telemetry/aggregate")
    card = resp.get_json()["grind_cards"]["GRIND_GBPUSD_OPT"]
    assert card["halted"] is True
    assert card["halt_reason"] == "test halt"
    assert card["invariant_ok"] is False
    assert card["peer_read_failed"] is True
    print("4b OK (halted=true): halt/invariant/peer flags correct")

    # 4c — v2 aggregates unchanged with grind present
    assert data["account_daily_api_count"] == baseline_api
    assert data["net_exposure"] == baseline_exposure
    assert data["intraday_mae"] == baseline_mae
    print("4c OK: account API, net exposure, MAE identical with grind data present")

    # Summariser isolation — v2 summariser untouched
    v2 = pipshed._summarize_instance_state("MM_LONG_V2", sample_v2_payload(), pipshed._broker_today())
    assert v2["open_long_layers"] == 1
    assert v2["net_mtm"] == 123.45
    print("Summariser isolation OK: _summarize_instance_state still works for v2")

    return 0


if __name__ == "__main__":
    sys.exit(main())
