"""Verification for grind P&L and microstructure rendering (mock Redis)."""
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


GRIND_OPT = [
    "GRIND_GBPUSD_OPT",
    "GRIND_EURUSD_OPT",
    "GRIND_EURGBP_OPT",
]


def sample_v2_payload(api_count=42, net_pnl=123.45):
    return json.dumps({
        "engine_state": {
            "account_daily_api_count": api_count,
            "account_daily_api_warning": False,
        },
        "active_pods": {
            "GBPUSD": {
                "net_pnl": net_pnl,
                "layer_detail": [{"direction": 1}],
            }
        },
        "working_orders": {},
        "system_alerts": [],
    })


def grind_payload_base(**overrides):
    payload = {
        "instance_id": "GRIND_GBPUSD_OPT",
        "open_layers_long": 0,
        "open_layers_short": 0,
        "fills": 1,
        "scalps": 2,
        "api_count": 11,
        "halted": False,
        "recon_ok": True,
        "invariant_ok": True,
        "peer_read_failed": False,
        "slot": "OPT",
        "net_mtm": 0.0,
        "realised_pnl_today": 0.0,
        "scalp_pnl_last": 0.0,
        "exit_penetration_pips_last": 0.0,
        "exit_penetration_pips_mean": 0.0,
        "exit_touch_revert_count": 0,
    }
    payload.update(overrides)
    return json.dumps(payload)


def js_grind_fmt_signed(val):
    """Mirror dashboard grindFmtSigned — explicit null check, not truthy."""
    if val is None:
        return "—"
    n = float(val)
    return ("+" if n >= 0 else "") + f"{n:.2f}"


def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()
    mock.set("fxmatrix:state:MM_LONG_V2", sample_v2_payload())

    baseline = client.get("/api/telemetry/aggregate").get_json()
    baseline_arms = json.dumps(baseline["arm_summaries"], sort_keys=True)

    # 5a — net_mtm 0.0 must render as +0.00, not dash
    mock.set("fxmatrix:state:GRIND_GBPUSD_OPT", grind_payload_base(net_mtm=0.0))
    card = client.get("/api/telemetry/aggregate").get_json()["grind_cards"]["GRIND_GBPUSD_OPT"]
    assert card["net_mtm"] == 0.0
    assert js_grind_fmt_signed(card["net_mtm"]) == "+0.00"
    print("5a OK: net_mtm 0.0 preserved and formats as +0.00 (not dash)")

    # 5b — missing net_mtm renders dash
    payload_no_mtm = json.loads(grind_payload_base())
    del payload_no_mtm["net_mtm"]
    mock.set("fxmatrix:state:GRIND_GBPUSD_OPT", json.dumps(payload_no_mtm))
    card = pipshed._summarize_grind_instance_state(
        "GRIND_GBPUSD_OPT", json.dumps(payload_no_mtm)
    )
    assert card["net_mtm"] is None
    assert js_grind_fmt_signed(card["net_mtm"]) == "—"
    print("5b OK: absent net_mtm is None and formats as dash")

    # 5c — partial group: one live instance missing P&L fields, third offline
    mock.set("fxmatrix:state:GRIND_GBPUSD_OPT", grind_payload_base(net_mtm=1.5, realised_pnl_today=2.0))
    payload_partial = json.loads(grind_payload_base())
    del payload_partial["net_mtm"]
    del payload_partial["realised_pnl_today"]
    mock.set("fxmatrix:state:GRIND_EURUSD_OPT", json.dumps(payload_partial))
    mock._data.pop("fxmatrix:state:GRIND_EURGBP_OPT", None)
    resp = client.get("/api/telemetry/aggregate").get_json()
    opt = resp["grind_arm_summaries"]["opt"]
    assert opt["status"] == "degraded"
    assert opt["instances_live"] == 2
    assert opt["net_mtm"] == 1.5
    assert opt["realised_pnl_today"] == 2.0
    assert not math.isnan(opt["net_mtm"])
    assert opt["api_count"] == 11  # still MAX
    print("5c OK: DEGRADED group sums live instances null-safe; api_count still max")

    # 5d — v2 arm_summaries unchanged
    mock.set("fxmatrix:state:GRIND_GBPUSD_OPT", grind_payload_base(net_mtm=-0.18))
    arms_with_grind = json.dumps(
        client.get("/api/telemetry/aggregate").get_json()["arm_summaries"],
        sort_keys=True,
    )
    assert arms_with_grind == baseline_arms
    print("5d OK: arm_summaries byte-identical with grind P&L present")

    # Microstructure fields pass through
    card = pipshed._summarize_grind_instance_state(
        "GRIND_EURGBP_ALT",
        grind_payload_base(
            instance_id="GRIND_EURGBP_ALT",
            exit_penetration_pips_mean=1.25,
            exit_touch_revert_count=7,
        ),
    )
    assert card["exit_penetration_pips_mean"] == 1.25
    assert card["exit_touch_revert_count"] == 7
    print("Microstructure OK: exit_penetration_pips_mean and exit_touch_revert_count pass through")

    return 0


if __name__ == "__main__":
    sys.exit(main())
