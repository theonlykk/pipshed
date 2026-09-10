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


def ring_opt_instances(pipshed, ring_id):
    return [
        inst for inst in pipshed._grind_instances_for_ring(ring_id)
        if inst.endswith("_OPT")
    ]


def ring_alt_instances(pipshed, ring_id):
    return [
        inst for inst in pipshed._grind_instances_for_ring(ring_id)
        if inst.endswith("_ALT")
    ]


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


def seed_instances(mock, instances, *, halted_instance=None, skip_instances=None):
    skip = set(skip_instances or [])
    for inst in instances:
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

    ring_id = "eur_gbp_usd"
    ring_opt = ring_opt_instances(pipshed, ring_id)
    ring_alt = ring_alt_instances(pipshed, ring_id)
    ring_all = pipshed._grind_instances_for_ring(ring_id)
    per_instance_long = 2
    per_instance_short = 1
    per_instance_fills = 10
    per_instance_scalps = 5
    per_instance_api = 11

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()

    # 4a — no grind data
    resp = client.get("/api/telemetry/aggregate")
    assert resp.status_code == 200
    baseline = resp.get_json()
    assert "grind_rings" in baseline
    ring = baseline["grind_rings"][ring_id]
    opt = ring["arm_summaries"]["opt"]
    alt = ring["arm_summaries"]["alt"]
    assert opt["status"] == "no_data"
    assert opt["status_label"] == "Arm A: NO DATA"
    assert alt["status"] == "no_data"
    assert alt["status_label"] == "Arm B: NO DATA"
    print("4a OK: per-ring arm cards NO DATA; grind_rings key present")

    # 4b — all instances in ring 1 live
    seed_instances(mock, ring_all)
    resp = client.get("/api/telemetry/aggregate")
    data = resp.get_json()
    ring = data["grind_rings"][ring_id]
    opt = ring["arm_summaries"]["opt"]
    alt = ring["arm_summaries"]["alt"]

    expected_opt_live = len(ring_opt)
    expected_alt_live = len(ring_alt)

    assert opt["status"] == "running"
    assert opt["status_label"] == "Arm A: RUNNING"
    assert opt["instances_live"] == expected_opt_live
    assert opt["instances_total"] == expected_opt_live
    assert opt["open_layers_long"] == per_instance_long * expected_opt_live
    assert opt["open_layers_short"] == per_instance_short * expected_opt_live
    assert opt["fills"] == per_instance_fills * expected_opt_live
    assert opt["scalps"] == per_instance_scalps * expected_opt_live
    assert opt["api_count"] == per_instance_api  # max, not sum
    assert opt.get("net_mtm") == 0.0

    assert alt["status"] == "running"
    assert alt["status_label"] == "Arm B: RUNNING"
    assert alt["instances_live"] == expected_alt_live
    assert alt["api_count"] == per_instance_api
    print(
        f"4b OK: ring {ring_id} — {expected_opt_live}/{expected_opt_live} OPT live, "
        f"summed layers/fills/scalps, api_count=max({per_instance_api})"
    )

    # Ring 2 still NO DATA when only ring 1 seeded
    ring2 = data["grind_rings"]["aud_cad_chf"]
    assert ring2["arm_summaries"]["opt"]["status"] == "no_data"
    assert ring2["arm_summaries"]["alt"]["status"] == "no_data"
    print("4b-ii OK: unseeded ring renders NO DATA independently")

    # 4c — one instance halted on OPT group within ring 1
    seed_instances(mock, ring_all, halted_instance="GRIND_GBPUSD_OPT")
    resp = client.get("/api/telemetry/aggregate")
    opt = resp.get_json()["grind_rings"][ring_id]["arm_summaries"]["opt"]
    assert opt["status"] == "running"
    assert len(opt["halted_instances"]) == 1
    assert opt["halted_instances"][0]["instance_id"] == "GRIND_GBPUSD_OPT"
    print("4c OK: halted instance surfaced on ring OPT arm card")

    # 4d — one of three OPT live in ring 1
    seed_instances(mock, ring_all, skip_instances=["GRIND_EURGBP_OPT"])
    resp = client.get("/api/telemetry/aggregate")
    opt = resp.get_json()["grind_rings"][ring_id]["arm_summaries"]["opt"]
    assert opt["status"] == "degraded"
    assert opt["status_label"] == "Arm A: DEGRADED"
    assert opt["instances_live"] == expected_opt_live - 1
    print(f"4d OK: {expected_opt_live - 1}/{expected_opt_live} live reads DEGRADED")

    # Direct unit test: api max not sum (uses app-derived OPT list for ring)
    cards = {
        inst: pipshed._summarize_grind_instance_state(
            inst, sample_grind_payload(inst, api_count=11)
        )
        for inst in ring_opt
    }
    summary = pipshed._summarize_grind_arm("Arm A", ring_opt, cards)
    assert summary["api_count"] == per_instance_api
    assert summary["instances_total"] == len(ring_opt)
    print("Unit OK: _summarize_grind_arm uses max(api_count)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
