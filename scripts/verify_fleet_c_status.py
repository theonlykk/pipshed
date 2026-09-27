"""Verification for Fleet C public status route (/api/g/<token>/status_c)."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TOKEN = "k7m9p2x4q"

GRIND_A_INSTANCES = [
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

GRIND_C_INSTANCES = [
    "GRIND_GBPUSD_OPTC",
    "GRIND_EURUSD_OPTC",
    "GRIND_EURGBP_OPTC",
    "GRIND_AUDCAD_OPTC",
    "GRIND_AUDCHF_OPTC",
    "GRIND_CADCHF_OPTC",
    "GRIND_NZDCHF_OPTC",
    "GRIND_NZDCAD_OPTC",
    "GRIND_AUDNZD_OPTC",
    "GRIND_AUDNZD_ALTC",
    "GRIND_NZDCAD_ALTC",
]


class FakeRedis:
    def __init__(self):
        self._kv = {}

    def get(self, key):
        return self._kv.get(key)

    def set(self, key, value, ex=None):
        self._kv[key] = value


def _c_heartbeat():
    return json.dumps({
        "net_mtm": 1.25,
        "scalps": 2,
        "open_layers_long": 1,
        "account_login": 99999999,
        "account_balance": 10000.0,
        "account_equity": 10001.25,
        "halted": False,
    })


def _child_probe(probe_id):
    import app as pipshed

    if probe_id == "fc2":
        out = {"instances": pipshed.GRIND_INSTANCES}
    elif probe_id == "fc3":
        out = {
            "fleet": pipshed.GRIND_FLEET,
            "instances": pipshed.GRIND_INSTANCES,
            "opt_count": len(pipshed.GRIND_OPT_INSTANCES),
            "alt_count": len(pipshed.GRIND_ALT_INSTANCES),
            "default": pipshed.GRIND_DEFAULT_INSTANCE,
        }
    elif probe_id == "fc4":
        out = {"instances": pipshed.GRIND_INSTANCES}
    elif probe_id == "fc5":
        out = {
            "slots": {
                "GRIND_GBPUSD_OPTC": pipshed._grind_slot("GRIND_GBPUSD_OPTC"),
                "GRIND_AUDNZD_ALTC": pipshed._grind_slot("GRIND_AUDNZD_ALTC"),
                "GRIND_GBPUSD_OPTB": pipshed._grind_slot("GRIND_GBPUSD_OPTB"),
                "GRIND_GBPUSD_OPT": pipshed._grind_slot("GRIND_GBPUSD_OPT"),
            }
        }
    elif probe_id == "fc9":
        out = {"instances": pipshed.GRIND_INSTANCES}
    else:
        raise ValueError(f"unknown probe {probe_id}")
    print(json.dumps(out))


def run_probe(probe_id, extra_env=None):
    env = os.environ.copy()
    env.pop("GRIND_FLEET", None)
    env.pop("GRIND_FLEET_LABEL", None)
    if extra_env:
        for key, val in extra_env.items():
            if val is None:
                env.pop(key, None)
            else:
                env[key] = val
    env["PIPSHED_PROBE"] = probe_id
    result = subprocess.run(
        [sys.executable, __file__],
        env=env,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    for line in reversed(result.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError("probe produced no JSON")


def check_fc1():
    import app as pipshed

    if list(pipshed.GRIND_C_INSTANCES) != GRIND_C_INSTANCES:
        raise AssertionError("GRIND_C_INSTANCES mismatch")
    return "GRIND_C_INSTANCES list"


def check_fc2():
    data = run_probe("fc2")
    if data["instances"] != GRIND_A_INSTANCES:
        raise AssertionError("default must be fleet A list")
    for inst in data["instances"]:
        if inst.endswith("OPTC") or inst.endswith("ALTC"):
            raise AssertionError(f"{inst} must not appear on default fleet")
    return "default fleet A without C suffixes"


def check_fc3():
    data = run_probe("fc3", {"GRIND_FLEET": "C"})
    if data["fleet"] != "C":
        raise AssertionError("GRIND_FLEET must be C")
    if data["instances"] != GRIND_C_INSTANCES:
        raise AssertionError("GRIND_INSTANCES must be fleet C list")
    if data["opt_count"] != 9 or data["alt_count"] != 2:
        raise AssertionError(f"expected 9 OPT and 2 ALT, got {data['opt_count']}/{data['alt_count']}")
    if data["default"] != "GRIND_GBPUSD_OPTC":
        raise AssertionError("default instance must be GRIND_GBPUSD_OPTC")
    return "fleet C instances, arms, default"


def check_fc4():
    data = run_probe("fc4", {"GRIND_FLEET": "c"})
    if data["instances"] != GRIND_C_INSTANCES:
        raise AssertionError("GRIND_FLEET=c must select C list")
    return "case-insensitive fleet C"


def check_fc5():
    data = run_probe("fc5")
    expected = {
        "GRIND_GBPUSD_OPTC": "OPT",
        "GRIND_AUDNZD_ALTC": "ALT",
        "GRIND_GBPUSD_OPTB": "OPT",
        "GRIND_GBPUSD_OPT": "OPT",
    }
    for inst, want in expected.items():
        if data["slots"][inst] != want:
            raise AssertionError(f"_grind_slot({inst}) expected {want}, got {data['slots'][inst]}")
    return "_grind_slot OPTC/ALTC normalization"


def check_fc6():
    import app as pipshed

    pipshed.r = FakeRedis()
    client = pipshed.app.test_client()
    resp = client.get("/api/g/wrong-token/status_c")
    if resp.status_code != 404:
        raise AssertionError(f"expected 404, got {resp.status_code}")
    if resp.get_json().get("error") != "not found":
        raise AssertionError("expected not found error")
    return "wrong token returns 404"


def check_fc7():
    import app as pipshed

    fake = FakeRedis()
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPTC", _c_heartbeat())
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPTB", _c_heartbeat())
    pipshed.r = fake
    client = pipshed.app.test_client()
    resp = client.get(f"/api/g/{TOKEN}/status_c")
    if resp.status_code != 200:
        raise AssertionError(f"expected 200, got {resp.status_code}")
    data = resp.get_json()
    if data.get("fleet") != "C":
        raise AssertionError("fleet must be C")
    instances = data.get("instances") or {}
    if len(instances) != 11:
        raise AssertionError(f"expected 11 instances, got {len(instances)}")
    for inst in instances:
        if inst.endswith("OPTB") or inst.endswith("ALTB"):
            raise AssertionError(f"{inst} must not appear on status_c")
        if inst.endswith("_OPT") or inst.endswith("_ALT"):
            raise AssertionError(f"{inst} must not be bare cycle-3 id")
    summary = data.get("summary") or {}
    if summary.get("instances_total") != 11:
        raise AssertionError("instances_total must be 11")
    if summary.get("instances_live") != 1:
        raise AssertionError(f"instances_live expected 1, got {summary.get('instances_live')}")
    if summary.get("net_mtm") != 1.25:
        raise AssertionError(f"net_mtm expected 1.25, got {summary.get('net_mtm')}")
    if summary.get("scalps") != 2:
        raise AssertionError(f"scalps expected 2, got {summary.get('scalps')}")
    if summary.get("open_layers_long") != 1:
        raise AssertionError(f"open_layers_long expected 1, got {summary.get('open_layers_long')}")
    if summary.get("account_login") != 99999999:
        raise AssertionError(f"account_login expected 99999999, got {summary.get('account_login')}")
    return "status_c payload and summary"


def check_fc8():
    import app as pipshed

    fake = FakeRedis()
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPTC", _c_heartbeat())
    pipshed.r = fake
    client = pipshed.app.test_client()
    resp = client.get(f"/api/g/{TOKEN}/status_b")
    if resp.status_code != 200:
        raise AssertionError(f"expected 200, got {resp.status_code}")
    data = resp.get_json()
    if data.get("fleet") != "B":
        raise AssertionError("fleet must be B")
    summary = data.get("summary") or {}
    if summary.get("instances_live") != 0:
        raise AssertionError(f"instances_live expected 0, got {summary.get('instances_live')}")
    return "status_b ignores Fleet C heartbeat"


def check_fc9():
    data = run_probe("fc9", {"GRIND_FLEET": "X"})
    if data["instances"] != GRIND_A_INSTANCES:
        raise AssertionError("unknown GRIND_FLEET must fall back to A list")
    return "unknown fleet -> A"


CHECKS = [
    ("FC1", check_fc1),
    ("FC2", check_fc2),
    ("FC3", check_fc3),
    ("FC4", check_fc4),
    ("FC5", check_fc5),
    ("FC6", check_fc6),
    ("FC7", check_fc7),
    ("FC8", check_fc8),
    ("FC9", check_fc9),
]


def main():
    if os.environ.get("PIPSHED_PROBE"):
        _child_probe(os.environ["PIPSHED_PROBE"])
        return
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
