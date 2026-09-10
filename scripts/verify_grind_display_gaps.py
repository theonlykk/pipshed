"""Verification for grind pod row and open-positions display gaps (mock Redis)."""
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


def sample_grind_payload(
    instance_id,
    *,
    open_long=0,
    open_short=2,
    net_mtm=0.0,
    width_pips=5.0,
    exit_pips=5.0,
    add_pips=10.0,
    max_layers=5,
    halted=False,
):
    return json.dumps({
        "instance_id": instance_id,
        "open_layers_long": open_long,
        "open_layers_short": open_short,
        "net_mtm": net_mtm,
        "realised_pnl_today": 0.0,
        "fills": 0,
        "scalps": 0,
        "api_count": 11,
        "halted": halted,
        "recon_ok": True,
        "invariant_ok": True,
        "cap_blocked": False,
        "peer_read_failed": False,
        "width_pips": width_pips,
        "add_pips": add_pips,
        "exit_pips": exit_pips,
        "max_layers": max_layers,
        "slot": "ALT" if instance_id.endswith("_ALT") else "OPT",
    })


def js_grind_layers_line(long_l, short_l):
    has_long = long_l is not None
    has_short = short_l is not None
    if not has_long and not has_short:
        return "—"
    return f"{long_l if has_long else '—'} long / {short_l if has_short else '—'} short"


def js_grind_fmt_signed(val):
    if val is None:
        return "—"
    n = float(val)
    return ("+" if n >= 0 else "") + f"{n:.2f}"


def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import app as pipshed

    expected_grind_count = len(pipshed.GRIND_INSTANCES)

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()

    baseline_agg = client.get("/api/telemetry/aggregate").get_json()
    assert len(baseline_agg["grind_cards"]) == expected_grind_count

    # 4a / 5a — grind flat payload: 0.0 net_mtm is not treated as absent
    mock.set(
        "fxmatrix:state:GRIND_EURGBP_ALT",
        sample_grind_payload("GRIND_EURGBP_ALT", open_short=2, net_mtm=0.0),
    )
    card = pipshed._summarize_grind_instance_state(
        "GRIND_EURGBP_ALT",
        mock.get("fxmatrix:state:GRIND_EURGBP_ALT"),
    )
    assert card["net_mtm"] == 0.0
    assert js_grind_fmt_signed(card["net_mtm"]) == "+0.00"
    assert js_grind_layers_line(0, 2) == "0 long / 2 short"
    assert pipshed._grind_symbol_from_instance_id("GRIND_EURGBP_ALT") == "EURGBP"
    print("4a OK: grind symbol from instance_id; net_mtm 0.0 -> +0.00; layers 0 long / 2 short")

    # 4c — grind shorts in open positions with dashes for entry/net when bidirectional
    mock.set(
        "fxmatrix:state:GRIND_EURGBP_OPT",
        sample_grind_payload("GRIND_EURGBP_OPT", open_long=1, open_short=0, net_mtm=-0.18),
    )
    open_resp = client.get("/api/telemetry/open_positions").get_json()
    grind_rows = [p for p in open_resp["positions"] if p["instance_id"].startswith("GRIND_")]
    assert len(grind_rows) == 2
    alt_row = next(p for p in grind_rows if p["instance_id"] == "GRIND_EURGBP_ALT")
    opt_row = next(p for p in grind_rows if p["instance_id"] == "GRIND_EURGBP_OPT")
    assert alt_row["direction"] == "SHORT"
    assert alt_row["layers"] == 2
    assert alt_row["avg_entry_price"] is None
    assert alt_row["net_pnl"] == 0.0
    assert opt_row["direction"] == "LONG"
    assert opt_row["net_pnl"] == -0.18
    print("4c OK: grind EURGBP long+short rows; entry dash; per-direction net_pnl")

    # 4c-ii — both sides open => two rows, net_pnl dash on both
    mock.set(
        "fxmatrix:state:GRIND_GBPUSD_OPT",
        sample_grind_payload("GRIND_GBPUSD_OPT", open_long=2, open_short=1, net_mtm=1.5),
    )
    open_resp = client.get("/api/telemetry/open_positions").get_json()
    gbp_rows = [p for p in open_resp["positions"] if p["instance_id"] == "GRIND_GBPUSD_OPT"]
    assert len(gbp_rows) == 2
    assert {r["direction"] for r in gbp_rows} == {"LONG", "SHORT"}
    assert all(r["net_pnl"] is None for r in gbp_rows)
    print("4c-ii OK: bidirectional grind renders two rows with net_pnl dash on both")

    # 4d — count line fields derived from GRIND_INSTANCES
    assert open_resp["tracked_grind_count"] == expected_grind_count
    assert open_resp["tracked_total_count"] == expected_grind_count
    print(
        f"4d OK: tracked counts match len(GRIND_INSTANCES) == {expected_grind_count}"
    )

    # 4e — aggregate ring structure unchanged aside from seeded grind cards
    agg = client.get("/api/telemetry/aggregate").get_json()
    assert len(agg["grind_rings"]) == len(pipshed.GRIND_RINGS)
    for ring_id, ring_meta in pipshed.GRIND_RINGS.items():
        ring = agg["grind_rings"][ring_id]
        assert ring["label"] == ring_meta["label"]
        assert len(ring["instances"]) == len(pipshed._grind_instances_for_ring(ring_id))
    print("4e OK: grind_rings structure matches GRIND_RINGS mapping")

    return 0


if __name__ == "__main__":
    sys.exit(main())
