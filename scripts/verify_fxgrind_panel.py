"""Local verification for fxgrind panel (no Redis required — in-memory mock)."""
import json
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
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import app as pipshed

    expected_grind_count = len(pipshed.GRIND_INSTANCES)
    expected_ring_count = len(pipshed.GRIND_RINGS)

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()

    # 4a — no grind data
    resp = client.get("/api/telemetry/aggregate")
    assert resp.status_code == 200
    baseline = resp.get_json()
    grind = baseline.get("grind_cards", {})
    assert len(grind) == expected_grind_count
    assert all(c["connection"] == "no_data" for c in grind.values())
    assert "grind_cards" in baseline
    assert "grind_rings" in baseline
    assert len(baseline["grind_rings"]) == expected_ring_count
    for ring_id in pipshed.GRIND_RINGS:
        ring = baseline["grind_rings"][ring_id]
        assert ring["arm_summaries"]["opt"]["status"] == "no_data"
        assert ring["arm_summaries"]["alt"]["status"] == "no_data"
        ring_instances = pipshed._grind_instances_for_ring(ring_id)
        assert len(ring["instances"]) == len(ring_instances)
    for key in (
        "net_exposure",
        "grind_api_count",
        "grind_api_count_limit",
        "intraday_mae",
    ):
        assert key in baseline, f"missing key {key}"
    print(
        f"4a OK: {expected_grind_count} grind_cards all no_data; "
        f"{expected_ring_count} rings present"
    )

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

    # 4c — grind exposure accumulates; MAE values absent when payload has no MAE fields
    expected_lots = (2 - 1) * pipshed.GRIND_ASSUMED_LOT_SIZE
    assert data["net_exposure"].get("GBPUSD") == expected_lots
    assert data["intraday_mae"]["mae_equity_low"] == baseline_mae["mae_equity_low"]
    assert data["intraday_mae"]["source_instance"] == "GRIND_GBPUSD_OPT"
    print(
        f"4c OK: GBPUSD net exposure {expected_lots} lots; MAE values still absent"
    )

    # Layer + drift summariser
    layer_payload = json.dumps({
        "instance_id": "GRIND_GBPUSD_OPT",
        "layers": [{
            "layer_index": 0,
            "side": "long",
            "entry_price": 1.1,
            "exit_target": 1.2,
            "has_exit_order": True,
            "has_exit_position": False,
        }],
        "l0_pending_long": 1.05,
        "resting_entries_long": 2,
    })
    card = pipshed._summarize_grind_instance_state("GRIND_GBPUSD_OPT", layer_payload)
    assert card["layers"][0]["entry_price"] == 1.1
    assert card["resting_drift_long"]["expected"] == 1
    assert card["resting_drift_long"]["actual"] == 2
    print("Summariser OK: layers and resting-entry drift parsed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
