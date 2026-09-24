"""Verification for GRIND_FLEET environment instance selection."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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

GRIND_B_INSTANCES = [
    "GRIND_GBPUSD_OPTB",
    "GRIND_EURUSD_OPTB",
    "GRIND_EURGBP_OPTB",
    "GRIND_AUDCAD_OPTB",
    "GRIND_AUDCHF_OPTB",
    "GRIND_CADCHF_OPTB",
    "GRIND_NZDCHF_OPTB",
    "GRIND_NZDCAD_OPTB",
    "GRIND_AUDNZD_OPTB",
    "GRIND_AUDNZD_ALTB",
    "GRIND_NZDCAD_ALTB",
]


def _child_probe(probe_id):
    sys.path.insert(0, ROOT)
    import app as pipshed

    live_json = json.dumps({"halted": False})

    if probe_id == "fs1":
        out = {
            "instances": pipshed.GRIND_INSTANCES,
            "opt_count": len(pipshed.GRIND_OPT_INSTANCES),
            "alt_count": len(pipshed.GRIND_ALT_INSTANCES),
            "first": pipshed.GRIND_INSTANCES[0],
        }
    elif probe_id == "fs2":
        out = {
            "instances": pipshed.GRIND_INSTANCES,
            "b_instances": pipshed.GRIND_B_INSTANCES,
            "default": pipshed.GRIND_DEFAULT_INSTANCE,
        }
    elif probe_id == "fs3":
        out = {
            "opt": list(pipshed.GRIND_OPT_INSTANCES),
            "alt": list(pipshed.GRIND_ALT_INSTANCES),
        }
    elif probe_id == "fs4":
        out = {
            "slots": {
                "GRIND_GBPUSD_OPT": pipshed._grind_slot("GRIND_GBPUSD_OPT"),
                "GRIND_GBPUSD_OPTB": pipshed._grind_slot("GRIND_GBPUSD_OPTB"),
                "GRIND_AUDNZD_ALT": pipshed._grind_slot("GRIND_AUDNZD_ALT"),
                "GRIND_AUDNZD_ALTB": pipshed._grind_slot("GRIND_AUDNZD_ALTB"),
            }
        }
    elif probe_id == "fs5b":
        out = {"instances": pipshed.GRIND_INSTANCES}
    elif probe_id == "fs5x":
        out = {"instances": pipshed.GRIND_INSTANCES}
    elif probe_id == "fs6":
        cards = {}
        for inst in pipshed.GRIND_B_INSTANCES:
            cards[inst] = pipshed._summarize_grind_instance_state(inst, live_json)
        rings = pipshed._build_grind_ring_summaries(cards)
        nzd = rings["nzd_ext"]
        eur = rings["eur_gbp_usd"]
        out = {
            "nzd_instances": list(nzd["instances"]),
            "nzd_opt_live": nzd["arm_summaries"]["opt"]["instances_live"],
            "nzd_alt_live": nzd["arm_summaries"]["alt"]["instances_live"],
            "eur_instances": list(eur["instances"]),
            "eur_opt_live": eur["arm_summaries"]["opt"]["instances_live"],
            "eur_alt_live": eur["arm_summaries"]["alt"]["instances_live"],
        }
    elif probe_id == "fs7label":
        client = pipshed.app.test_client()
        html = client.get("/").get_data(as_text=True)
        out = {
            "has_fleet_b": "Fleet B" in html,
            "has_fleet_label_span": '<span class="fleet-label">' in html,
        }
    elif probe_id == "fs7nolabel":
        client = pipshed.app.test_client()
        html = client.get("/").get_data(as_text=True)
        out = {"has_fleet_label_span": '<span class="fleet-label">' in html}
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


def check_fs1():
    data = run_probe("fs1")
    if data["instances"] != GRIND_A_INSTANCES:
        raise AssertionError("GRIND_INSTANCES must match cycle-3 A list")
    if data["first"] != "GRIND_GBPUSD_OPT":
        raise AssertionError("first instance regression")
    if data["opt_count"] != 9 or data["alt_count"] != 9:
        raise AssertionError(f"expected 9 OPT and 9 ALT, got {data['opt_count']}/{data['alt_count']}")
    return "default fleet A (18 ids, 9+9 arms)"


def check_fs2():
    data = run_probe("fs2", {"GRIND_FLEET": "B"})
    if data["instances"] != data["b_instances"]:
        raise AssertionError("GRIND_INSTANCES must equal GRIND_B_INSTANCES")
    if data["default"] != "GRIND_GBPUSD_OPTB":
        raise AssertionError("default instance must be GRIND_GBPUSD_OPTB")
    return "fleet B instances and default"


def check_fs3():
    data = run_probe("fs3", {"GRIND_FLEET": "B"})
    opt = data["opt"]
    alt = data["alt"]
    if len(opt) != 9:
        raise AssertionError(f"expected 9 OPTB, got {len(opt)}")
    for inst in opt:
        if not inst.endswith("_OPTB"):
            raise AssertionError(f"{inst} not OPTB")
    alt_set = set(alt)
    expected_alt = {"GRIND_AUDNZD_ALTB", "GRIND_NZDCAD_ALTB"}
    if alt_set != expected_alt:
        raise AssertionError(f"ALT arms expected {expected_alt}, got {alt_set}")
    return "fleet B OPT/ALT arm split"


def check_fs4():
    data = run_probe("fs4")
    slots = data["slots"]
    expected = {
        "GRIND_GBPUSD_OPT": "OPT",
        "GRIND_GBPUSD_OPTB": "OPT",
        "GRIND_AUDNZD_ALT": "ALT",
        "GRIND_AUDNZD_ALTB": "ALT",
    }
    for inst, want in expected.items():
        if slots[inst] != want:
            raise AssertionError(f"_grind_slot({inst}) expected {want}, got {slots[inst]}")
    return "_grind_slot normalizes OPTB/ALTB"


def check_fs5():
    data_b = run_probe("fs5b", {"GRIND_FLEET": "b"})
    if data_b["instances"] != GRIND_B_INSTANCES:
        raise AssertionError("GRIND_FLEET=b must select B list")
    data_x = run_probe("fs5x", {"GRIND_FLEET": "X"})
    if data_x["instances"] != GRIND_A_INSTANCES:
        raise AssertionError("unknown GRIND_FLEET must fall back to A list")
    return "case-insensitive B and unknown -> A"


def check_fs6():
    data = run_probe("fs6", {"GRIND_FLEET": "B"})
    nzd_want = {
        "GRIND_NZDCAD_OPTB",
        "GRIND_NZDCAD_ALTB",
        "GRIND_AUDNZD_OPTB",
        "GRIND_AUDNZD_ALTB",
    }
    eur_want = {
        "GRIND_GBPUSD_OPTB",
        "GRIND_EURUSD_OPTB",
        "GRIND_EURGBP_OPTB",
    }
    if set(data["nzd_instances"]) != nzd_want:
        raise AssertionError(f"nzd_ext instances mismatch: {data['nzd_instances']}")
    if data["nzd_opt_live"] != 2 or data["nzd_alt_live"] != 2:
        raise AssertionError("nzd_ext arm live counts must be 2+2")
    if set(data["eur_instances"]) != eur_want:
        raise AssertionError(f"eur_gbp_usd instances mismatch: {data['eur_instances']}")
    if data["eur_opt_live"] != 3 or data["eur_alt_live"] != 0:
        raise AssertionError("eur_gbp_usd arms must be 3 OPT / 0 ALT")
    return "ring membership under fleet B"


def check_fs7():
    labeled = run_probe("fs7label", {"GRIND_FLEET_LABEL": "Fleet B"})
    if not labeled["has_fleet_b"]:
        raise AssertionError("dashboard must show Fleet B label text")
    if not labeled["has_fleet_label_span"]:
        raise AssertionError("dashboard must include fleet-label span")
    plain = run_probe("fs7nolabel")
    if plain["has_fleet_label_span"]:
        raise AssertionError("unset label must not render fleet-label")
    return "dashboard fleet label"


CHECKS = [
    ("FS1", check_fs1),
    ("FS2", check_fs2),
    ("FS3", check_fs3),
    ("FS4", check_fs4),
    ("FS5", check_fs5),
    ("FS6", check_fs6),
    ("FS7", check_fs7),
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
