"""Verification: C97, an unpaired EXT position raises an amber ORPHAN_EXT on
the fleet strip.

When an exit fills and the EA never sees the deal (a link stall; fxmatrix
event log 1 Oct 17:55Z, NZDCAD OPT and ALT on cycle 3), the exit position
stays open beside its entry, the close-by never queues, and that side stops
scalping. No invariant fires. The heartbeat carries both the broker book
(`book.positions`, each with its GRIND comment) and the engine's layers
(`layers`, each with `has_exit_position`). An EXT position is PAIRED when
the engine holds that side and layer index with `has_exit_position` true
(the close-by is in flight); otherwise it is an ORPHAN. A live instance with
an orphan gets one amber strip alert per orphan:
kind/code ORPHAN_EXT, detail "EXT position <ticket> (<side> L<nn>) not
paired: reattach the chart". No layer detail in the heartbeat: unknown, no
alert. A resting EXT ORDER is not a position and never counts.

Tests first. Predicted at the tests-only commit: OX1, OX2, OX6 and OX7 FAIL;
OX3, OX4 and OX5 are guards that pass in both states.

    python scripts/verify_c97_orphan_ext.py
"""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "verify_fleet_strip_helpers_c97", os.path.join(ROOT, "scripts", "verify_fleet_strip.py"))
fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fs)

TOKEN = fs.TOKEN
INST = "GRIND_NZDCAD_OPTD"
INST2 = "GRIND_AUDCAD_OPTD"


def _pos(ticket, ptype, price, comment):
    return {"ticket": ticket, "type": ptype, "price": price,
            "open_time": "2026.10.01 20:55:22", "open_time_msc": 1790888122000,
            "comment": comment, "profit": 0.10}


def _layer(side, idx, entry, exit_target, has_exit_position):
    return {"layer_index": idx, "side": side, "entry_price": entry, "exit_target": exit_target,
            "has_exit_order": not has_exit_position, "has_exit_position": has_exit_position,
            "comment": f"GRIND|OPT|{side}|L{idx:02d}|ENT"}


def _hb(positions, layers, orders=None, **over):
    payload = dict(account_login=53077984, invariant_ok=True, max_layers=8,
                   open_layers_long=sum(1 for l in layers or [] if l["side"] == "L"),
                   open_layers_short=sum(1 for l in layers or [] if l["side"] == "S"),
                   book={"positions": positions, "orders": orders or []})
    if layers is not None:
        payload["layers"] = layers
    payload.update(over)
    return fs.HB(30, **payload)


def _orphan_short_l00(has_exit_position=False, with_layers=True, **over):
    positions = [_pos(555067590, "SELL", 0.80950, "GRIND|OPT|S|L00|ENT"),
                 _pos(555076933, "BUY", 0.80850, "GRIND|OPT|S|L00|EXT")]
    layers = [_layer("S", 0, 0.80950, 0.80850, has_exit_position)] if with_layers else None
    return _hb(positions, layers, **over)


def _fixture(fake, overrides):
    for inst in fs.GRIND_D_INSTANCES:
        if inst in overrides:
            if overrides[inst] is not None:
                fake.set(f"fxmatrix:state:{inst}", overrides[inst])
            continue
        fake.set(f"fxmatrix:state:{inst}", fs.HBB(30, account_login=53077984, invariant_ok=True))
    fake.set(fs.DAILY_TABLE_KEY, json.dumps({"generated_at": fs.now.isoformat(), "rows": []}))
    fake.set(fs.CRITICAL_KEY, json.dumps({"generated_at": fs.now.isoformat(), "rows": []}))


def _orphan_alerts(fake):
    import app as pipshed

    pipshed.r = fake
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets/c97").get_json()
    d = fs._fleet_by_letter(data, "D")
    return [a for a in d.get("alerts") or [] if a.get("kind") == "ORPHAN_EXT"]


def _assert_one(alerts, inst, ticket, label, why):
    mine = [a for a in alerts if a.get("instance_id") == inst]
    if len(mine) != 1:
        raise AssertionError(f"{why}: want one ORPHAN_EXT for {inst}, got {alerts}")
    a = mine[0]
    want = f"EXT position {ticket} ({label}) not paired: reattach the chart"
    if a.get("level") != "amber" or a.get("code") != "ORPHAN_EXT" or a.get("detail") != want:
        raise AssertionError(f"{why}: want amber ORPHAN_EXT '{want}', got {a}")


def check_ox1():
    fake = fs.FakeRedis()
    _fixture(fake, {INST: _orphan_short_l00(has_exit_position=False)})
    _assert_one(_orphan_alerts(fake), INST, 555076933, "S L00", "engine layer without the exit")
    return "EXT position, engine layer has no exit position: amber ORPHAN_EXT"


def check_ox2():
    fake = fs.FakeRedis()
    positions = [_pos(555146463, "BUY", 0.98525, "GRIND|OPT|L|L14|ENT"),
                 _pos(555135550, "BUY", 0.98477, "GRIND|OPT|S|L01|EXT")]
    layers = [_layer("L", 14, 0.98525, 0.98625, False)]       # no short L01 in the engine
    _fixture(fake, {INST: _hb(positions, layers)})
    _assert_one(_orphan_alerts(fake), INST, 555135550, "S L01", "layer missing from the engine")
    return "EXT position whose layer the engine does not hold: ORPHAN_EXT"


def check_ox3():
    """GUARD: the close-by is in flight (engine has the exit position): no alert."""
    fake = fs.FakeRedis()
    _fixture(fake, {INST: _orphan_short_l00(has_exit_position=True)})
    got = _orphan_alerts(fake)
    if got:
        raise AssertionError(f"a paired EXT must not alert, got {got}")
    return "paired EXT (close-by in flight): no alert"


def check_ox4():
    """GUARD: resting EXT ORDERS and ENT positions never count."""
    fake = fs.FakeRedis()
    positions = [_pos(555067590, "SELL", 0.80950, "GRIND|OPT|S|L00|ENT")]
    orders = [{"ticket": 600001, "type": "BUY_LIMIT", "price": 0.80850,
               "open_time": "2026.10.01 20:50:00", "open_time_msc": 1790887800000,
               "comment": "GRIND|OPT|S|L00|EXT"}]
    layers = [_layer("S", 0, 0.80950, 0.80850, False)]
    _fixture(fake, {INST: _hb(positions, layers, orders=orders)})
    got = _orphan_alerts(fake)
    if got:
        raise AssertionError(f"orders and ENT positions must not alert, got {got}")
    return "resting EXT orders and ENT positions: no alert"


def check_ox5():
    """GUARD: no layer detail (unknown) or no heartbeat: no alert."""
    fake = fs.FakeRedis()
    _fixture(fake, {INST: _orphan_short_l00(with_layers=False)})
    got = _orphan_alerts(fake)
    if got:
        raise AssertionError(f"without layer detail there is no verdict, got {got}")
    fake2 = fs.FakeRedis()
    _fixture(fake2, {INST: None})
    got2 = _orphan_alerts(fake2)
    if got2:
        raise AssertionError(f"no heartbeat, no alert, got {got2}")
    return "unknown state: no alert"


def check_ox6():
    fake = fs.FakeRedis()
    positions2 = [_pos(555110341, "SELL", 0.98579, "GRIND|OPT|S|L01|ENT"),
                  _pos(555135550, "BUY", 0.98477, "GRIND|OPT|S|L01|EXT")]
    layers2 = [_layer("S", 1, 0.98579, 0.98479, False)]
    _fixture(fake, {INST: _orphan_short_l00(has_exit_position=False),
                    INST2: _hb(positions2, layers2, halted=True, halt_reason="I3_LONG_NAKED")})
    alerts = _orphan_alerts(fake)
    if len(alerts) != 2:
        raise AssertionError(f"want two ORPHAN_EXT (one per instance), got {alerts}")
    _assert_one(alerts, INST, 555076933, "S L00", "first instance")
    _assert_one(alerts, INST2, 555135550, "S L01", "second instance, halted")
    return "one alert per orphan, per instance; a halted instance still reports its orphan"


def check_ox7():
    import app as pipshed

    html = pipshed.app.test_client().get("/").get_data(as_text=True)
    need = ["<code>ORPHAN_EXT</code>", "not paired", "reattach that chart"]
    missing = [n for n in need if n not in html]
    if missing:
        raise AssertionError(f"legend lacks {missing}")
    return "legend explains ORPHAN_EXT and the action"


CHECKS = [("OX1", check_ox1), ("OX2", check_ox2), ("OX3", check_ox3), ("OX4", check_ox4),
          ("OX5", check_ox5), ("OX6", check_ox6), ("OX7", check_ox7)]


def main():
    passed = failed = 0
    for name, fn in CHECKS:
        try:
            print(f"{name} OK: {fn()}")
            passed += 1
        except Exception as exc:
            print(f"{name} FAIL: {exc}")
            failed += 1
    print(f"SUMMARY passed={passed} failed={failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
