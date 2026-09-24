"""Verification for Fleet B public status route (/api/g/<token>/status_b)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeRedis:
    def __init__(self):
        self._kv = {}

    def get(self, key):
        return self._kv.get(key)

    def set(self, key, value, ex=None):
        self._kv[key] = value


EXPECTED_GRIND_INSTANCES = [
    "GRIND_GBPUSD_OPT",
    "GRIND_GBPUSD_ALT",
    "GRIND_EURUSD_OPT",
    "GRIND_EURUSD_ALT",
    "GRIND_EURGBP_OPT",
    "GRIND_EURGBP_ALT",
    "GRIND_AUDCAD_OPT",
    "GRIND_AUDCAD_ALT",
    "GRIND_AUDCHF_OPT",
    "GRIND_AUDCHF_ALT",
    "GRIND_CADCHF_OPT",
    "GRIND_CADCHF_ALT",
    "GRIND_NZDCHF_OPT",
    "GRIND_NZDCHF_ALT",
    "GRIND_NZDCAD_OPT",
    "GRIND_NZDCAD_ALT",
    "GRIND_AUDNZD_OPT",
    "GRIND_AUDNZD_ALT",
]

TOKEN = "k7m9p2x4q"


def check_fb1():
    import app as pipshed

    insts = pipshed.GRIND_B_INSTANCES
    if len(insts) != 11:
        raise AssertionError(f"expected 11 ids, got {len(insts)}")
    for inst in insts:
        if not (inst.endswith("OPTB") or inst.endswith("ALTB")):
            raise AssertionError(f"{inst} suffix not OPTB/ALTB")
        if inst in pipshed.GRIND_INSTANCES:
            raise AssertionError(f"{inst} must not be in GRIND_INSTANCES")
    return "GRIND_B_INSTANCES list and isolation"


def check_fb2():
    import app as pipshed

    if pipshed.GRIND_INSTANCES != EXPECTED_GRIND_INSTANCES:
        raise AssertionError("GRIND_INSTANCES changed from cycle-3 baseline")
    if len(pipshed.GRIND_INSTANCES) != 18:
        raise AssertionError(f"expected 18 ids, got {len(pipshed.GRIND_INSTANCES)}")
    for inst in pipshed.GRIND_INSTANCES:
        if inst.endswith("B") and (inst.endswith("OPTB") or inst.endswith("ALTB")):
            raise AssertionError(f"{inst} looks like Fleet B")
    return "GRIND_INSTANCES unchanged (18, no Fleet B suffixes)"


def check_fb3():
    import app as pipshed

    fake = FakeRedis()
    pipshed.r = fake
    client = pipshed.app.test_client()
    resp = client.get("/api/g/wrong-token/status_b")
    if resp.status_code != 404:
        raise AssertionError(f"expected 404, got {resp.status_code}")
    data = resp.get_json()
    if data.get("error") != "not found":
        raise AssertionError("expected not found error")
    return "wrong token returns 404"


def _live_b_heartbeat():
    return json.dumps({
        "net_mtm": 1.25,
        "scalps": 2,
        "open_layers_long": 1,
        "account_login": 53066709,
        "account_balance": 10000.0,
        "account_equity": 10001.25,
        "halted": False,
    })


def check_fb4():
    import app as pipshed

    fake = FakeRedis()
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPTB", _live_b_heartbeat())
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPT", _live_b_heartbeat())
    pipshed.r = fake
    client = pipshed.app.test_client()
    resp = client.get(f"/api/g/{TOKEN}/status_b")
    if resp.status_code != 200:
        raise AssertionError(f"expected 200, got {resp.status_code}")
    data = resp.get_json()
    if data.get("fleet") != "B":
        raise AssertionError("fleet must be B")
    instances = data.get("instances") or {}
    if len(instances) != 11:
        raise AssertionError(f"expected 11 instances, got {len(instances)}")
    if "GRIND_GBPUSD_OPT" in instances:
        raise AssertionError("cycle-3 instance must not appear")
    summary = data.get("summary") or {}
    if summary.get("instances_live") != 1:
        raise AssertionError(f"instances_live expected 1, got {summary.get('instances_live')}")
    if summary.get("net_mtm") != 1.25:
        raise AssertionError(f"net_mtm expected 1.25, got {summary.get('net_mtm')}")
    if summary.get("scalps") != 2:
        raise AssertionError(f"scalps expected 2, got {summary.get('scalps')}")
    if summary.get("open_layers_long") != 1:
        raise AssertionError(f"open_layers_long expected 1, got {summary.get('open_layers_long')}")
    if summary.get("account_login") != 53066709:
        raise AssertionError(f"account_login expected 53066709, got {summary.get('account_login')}")
    return "status_b payload and summary"


def check_fb5():
    import app as pipshed

    fake = FakeRedis()
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPTB", _live_b_heartbeat())
    pipshed.r = fake
    client = pipshed.app.test_client()
    resp = client.get(f"/api/g/{TOKEN}/status")
    if resp.status_code != 200:
        raise AssertionError(f"expected 200, got {resp.status_code}")
    instances = resp.get_json().get("instances") or {}
    if "GRIND_GBPUSD_OPTB" in instances:
        raise AssertionError("Fleet B instance must not appear on /status")
    if len(instances) != 18:
        raise AssertionError(f"expected 18 cycle-3 instances, got {len(instances)}")
    return "Fleet B absent from /status"


def check_fb6():
    import app as pipshed

    empty = pipshed._summarize_grind_instance_state("GRIND_GBPUSD_OPTB", None)
    summary_empty = pipshed._fleet_summary({"GRIND_GBPUSD_OPTB": empty}, {"GRIND_GBPUSD_OPTB": None})
    if summary_empty.get("open_layers_long") != 0:
        raise AssertionError("no live: open_layers_long should be 0")
    if summary_empty.get("api_count") is not None:
        raise AssertionError("no live: api_count should be None")

    live_halted = pipshed._summarize_grind_instance_state(
        "GRIND_EURUSD_OPTB",
        json.dumps({"halted": True, "net_mtm": 5.0}),
    )
    summary_h = pipshed._fleet_summary(
        {"GRIND_EURUSD_OPTB": live_halted},
        {"GRIND_EURUSD_OPTB": json.dumps({"halted": True})},
    )
    halted = summary_h.get("halted_instances") or []
    if "GRIND_EURUSD_OPTB" not in halted:
        raise AssertionError("halted live card must appear in halted_instances")
    return "_fleet_summary halted and empty cases"


CHECKS = [
    ("FB1", check_fb1),
    ("FB2", check_fb2),
    ("FB3", check_fb3),
    ("FB4", check_fb4),
    ("FB5", check_fb5),
    ("FB6", check_fb6),
]


def main():
    passed = 0
    failed = 0
    for name, fn in CHECKS:
        try:
            msg = fn()
            print(f"{name} OK: {msg}")
            passed += 1
        except Exception as exc:
            print(f"{name} FAIL: {exc}")
            failed += 1
    print(f"SUMMARY passed={passed} failed={failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
