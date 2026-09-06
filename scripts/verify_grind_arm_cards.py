"""Local verification for grind OPT/ALT arm summary cards (mock Redis)."""
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


GRIND_OPT = [
    "GRIND_GBPUSD_OPT",
    "GRIND_EURUSD_OPT",
    "GRIND_EURGBP_OPT",
]
GRIND_ALT = [
    "GRIND_GBPUSD_ALT",
    "GRIND_EURUSD_ALT",
    "GRIND_EURGBP_ALT",
]


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


def sample_grind_payload(
    instance_id,
    *,
    halted=False,
    open_long=2,
    open_short=1,
    fills=10,
    scalps=5,
    api_count=11,
):
    return json.dumps({
        "instance_id": instance_id,
        "open_layers_long": open_long,
        "open_layers_short": open_short,
        "fills": fills,
        "scalps": scalps,
        "api_count": api_count,
        "api_counter_broken": False,
        "cap_blocked": False,
        "halted": halted,
        "halt_reason": "test halt" if halted else "",
        "recon_ok": True,
        "invariant_ok": True,
        "cap_leg_a": 1.25,
        "cap_leg_b": 0.75,
        "cap_total_leg_a": 10.0,
        "cap_total_leg_b": 8.0,
        "peer_read_failed": False,
        "magic": 123456789,
        "slot": "OPT" if instance_id.endswith("_OPT") else "ALT",
        "width_pips": 5.0,
        "add_pips": 10.0,
        "exit_pips": 5.0,
        "max_layers": 5,
        "cap_leg_a_name": "GBP",
        "cap_leg_b_name": "USD",
    })


def seed_all_grind(mock, *, halted_instance=None, skip_instances=None):
    skip = set(skip_instances or [])
    for inst in GRIND_OPT + GRIND_ALT:
        key = f"fxmatrix:state:{inst}"
        if inst in skip:
            mock._data.pop(key, None)
            continue
        mock.set(
            key,
            sample_grind_payload(inst, halted=(inst == halted_instance)),
        )


def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()

    mock.set("fxmatrix:state:MM_LONG_V2", sample_v2_payload(api_count=42, net_pnl=123.45))

    # 4a — no grind data
    resp = client.get("/api/telemetry/aggregate")
    assert resp.status_code == 200
    baseline = resp.get_json()
    assert "grind_arm_summaries" in baseline
    opt = baseline["grind_arm_summaries"]["opt"]
    alt = baseline["grind_arm_summaries"]["alt"]
    assert opt["status"] == "no_data"
    assert opt["status_label"] == "GRIND OPT: NO DATA"
    assert alt["status"] == "no_data"
    assert alt["status_label"] == "GRIND ALT: NO DATA"
    baseline_arms = json.dumps(baseline["arm_summaries"], sort_keys=True)
    print("4a OK: grind arm cards NO DATA; grind_arm_summaries key present")

    # 4b — all six grind payloads
    seed_all_grind(mock)
    resp = client.get("/api/telemetry/aggregate")
    data = resp.get_json()
    opt = data["grind_arm_summaries"]["opt"]
    alt = data["grind_arm_summaries"]["alt"]

    assert opt["status"] == "running"
    assert opt["status_label"] == "GRIND OPT: RUNNING"
    assert opt["instances_live"] == 3
    assert opt["open_layers_long"] == 6  # 2 * 3
    assert opt["open_layers_short"] == 3  # 1 * 3
    assert opt["fills"] == 30
    assert opt["scalps"] == 15
    assert opt["api_count"] == 11  # max, not sum (would be 33)
    assert opt.get("net_mtm") == 0.0  # no P&L fields in sample payload → null-safe sum of 0

    assert alt["status"] == "running"
    assert alt["status_label"] == "GRIND ALT: RUNNING"
    assert alt["instances_live"] == 3
    assert alt["api_count"] == 11
    print("4b OK: 3/3 live, summed layers/fills/scalps, api_count=max(11)")

    # 4e — v2 arm_summaries unchanged with grind data present
    arms_with_grind = json.dumps(data["arm_summaries"], sort_keys=True)
    assert arms_with_grind == baseline_arms, "arm_summaries changed when grind data added"
    print("4e OK: arm_summaries byte-identical with and without grind data")

    # 4c — one instance halted on OPT group
    seed_all_grind(mock, halted_instance="GRIND_GBPUSD_OPT")
    resp = client.get("/api/telemetry/aggregate")
    opt = resp.get_json()["grind_arm_summaries"]["opt"]
    assert opt["status"] == "running"
    assert len(opt["halted_instances"]) == 1
    assert opt["halted_instances"][0]["instance_id"] == "GRIND_GBPUSD_OPT"
    print("4c OK: halted instance surfaced on OPT group card")

    # 4d — two of three OPT live
    seed_all_grind(mock, skip_instances=["GRIND_EURGBP_OPT"])
    resp = client.get("/api/telemetry/aggregate")
    opt = resp.get_json()["grind_arm_summaries"]["opt"]
    assert opt["status"] == "degraded"
    assert opt["status_label"] == "GRIND OPT: DEGRADED"
    assert opt["instances_live"] == 2
    print("4d OK: 2/3 live reads DEGRADED")

    # Direct unit test: api max not sum
    cards = {inst: pipshed._summarize_grind_instance_state(
        inst, sample_grind_payload(inst, api_count=11 if "OPT" in inst else 13)
    ) for inst in GRIND_OPT}
    summary = pipshed._summarize_grind_arm("GRIND OPT", GRIND_OPT, cards)
    assert summary["api_count"] == 11
    print("Unit OK: _summarize_grind_arm uses max(api_count)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
