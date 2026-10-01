"""Verification for Fleet D (wine-d, IC 53077984; built 30 Sep, not attached):
GRIND_D_INSTANCES (_OPTD/_ALTD), GRIND_FLEET=D, _grind_slot, /status_d, and the
strip card (placeholder until attach, badge NOT ATTACHED, url linuxd; live
card from the 1 Oct 2026 attach, cycle_start 2026-10-01: FD10).

Tests first. Predicted at the tests-only commit: FD1, FD3, FD4, FD5, FD6, FD7,
FD10, FD12 FAIL; FD2, FD8, FD9, FD11 are guards that pass in both states (FD11: an
entry without "built" keeps the NOT BUILT badge).
"""
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

GRIND_D_INSTANCES = [
    "GRIND_GBPUSD_OPTD",
    "GRIND_EURUSD_OPTD",
    "GRIND_EURGBP_OPTD",
    "GRIND_AUDCAD_OPTD",
    "GRIND_AUDCHF_OPTD",
    "GRIND_CADCHF_OPTD",
    "GRIND_NZDCHF_OPTD",
    "GRIND_NZDCAD_OPTD",
    "GRIND_AUDNZD_OPTD",
    "GRIND_AUDNZD_ALTD",
    "GRIND_NZDCAD_ALTD",
]


class FakeRedis:
    def __init__(self):
        self._kv = {}

    def get(self, key):
        return self._kv.get(key)

    def set(self, key, value, ex=None):
        self._kv[key] = value

    def lrange(self, key, start, end):
        return []   # no scalp history: the strip's other fleets read empty


def _d_heartbeat():
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

    if probe_id == "fd2":
        out = {"instances": pipshed.GRIND_INSTANCES}
    elif probe_id == "fd3":
        out = {
            "fleet": pipshed.GRIND_FLEET,
            "instances": pipshed.GRIND_INSTANCES,
            "opt_count": len(pipshed.GRIND_OPT_INSTANCES),
            "alt_count": len(pipshed.GRIND_ALT_INSTANCES),
            "default": pipshed.GRIND_DEFAULT_INSTANCE,
        }
    elif probe_id == "fd4":
        out = {"instances": pipshed.GRIND_INSTANCES}
    elif probe_id == "fd5":
        out = {
            "slots": {
                "GRIND_GBPUSD_OPTD": pipshed._grind_slot("GRIND_GBPUSD_OPTD"),
                "GRIND_AUDNZD_ALTD": pipshed._grind_slot("GRIND_AUDNZD_ALTD"),
                "GRIND_GBPUSD_OPTC": pipshed._grind_slot("GRIND_GBPUSD_OPTC"),
                "GRIND_GBPUSD_OPTB": pipshed._grind_slot("GRIND_GBPUSD_OPTB"),
                "GRIND_GBPUSD_OPT": pipshed._grind_slot("GRIND_GBPUSD_OPT"),
            }
        }
    elif probe_id == "fd9":
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


def check_fd1():
    import app as pipshed

    if list(pipshed.GRIND_D_INSTANCES) != GRIND_D_INSTANCES:
        raise AssertionError("GRIND_D_INSTANCES mismatch")
    return "GRIND_D_INSTANCES list"


def check_fd2():
    data = run_probe("fd2")
    if data["instances"] != GRIND_A_INSTANCES:
        raise AssertionError("default must be fleet A list")
    for inst in data["instances"]:
        if inst.endswith("OPTD") or inst.endswith("ALTD"):
            raise AssertionError(f"{inst} must not appear on default fleet")
    return "default fleet A without D suffixes"


def check_fd3():
    data = run_probe("fd3", {"GRIND_FLEET": "D"})
    if data["fleet"] != "D":
        raise AssertionError("GRIND_FLEET must be D")
    if data["instances"] != GRIND_D_INSTANCES:
        raise AssertionError("GRIND_INSTANCES must be fleet D list")
    if data["opt_count"] != 9 or data["alt_count"] != 2:
        raise AssertionError(f"expected 9 OPT and 2 ALT, got {data['opt_count']}/{data['alt_count']}")
    if data["default"] != "GRIND_GBPUSD_OPTD":
        raise AssertionError("default instance must be GRIND_GBPUSD_OPTD")
    return "fleet D instances, arms, default"


def check_fd4():
    data = run_probe("fd4", {"GRIND_FLEET": "d"})
    if data["instances"] != GRIND_D_INSTANCES:
        raise AssertionError("GRIND_FLEET=d must select D list")
    return "case-insensitive fleet D"


def check_fd5():
    data = run_probe("fd5")
    expected = {
        "GRIND_GBPUSD_OPTD": "OPT",
        "GRIND_AUDNZD_ALTD": "ALT",
        "GRIND_GBPUSD_OPTC": "OPT",
        "GRIND_GBPUSD_OPTB": "OPT",
        "GRIND_GBPUSD_OPT": "OPT",
    }
    for inst, want in expected.items():
        if data["slots"][inst] != want:
            raise AssertionError(f"_grind_slot({inst}) expected {want}, got {data['slots'][inst]}")
    return "_grind_slot OPTD/ALTD normalization (C, B, A unchanged)"


def check_fd6():
    import app as pipshed

    pipshed.r = FakeRedis()
    client = pipshed.app.test_client()
    resp = client.get("/api/g/wrong-token/status_d")
    if resp.status_code != 404:
        raise AssertionError(f"expected 404, got {resp.status_code}")
    if resp.get_json().get("error") != "not found":
        raise AssertionError("expected not found error")
    return "wrong token returns 404"


def check_fd7():
    import app as pipshed

    fake = FakeRedis()
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPTD", _d_heartbeat())
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPTC", _d_heartbeat())
    pipshed.r = fake
    client = pipshed.app.test_client()
    resp = client.get(f"/api/g/{TOKEN}/status_d")
    if resp.status_code != 200:
        raise AssertionError(f"expected 200, got {resp.status_code}")
    data = resp.get_json()
    if data.get("fleet") != "D":
        raise AssertionError("fleet must be D")
    instances = data.get("instances") or {}
    if len(instances) != 11:
        raise AssertionError(f"expected 11 instances, got {len(instances)}")
    for inst in instances:
        if not (inst.endswith("OPTD") or inst.endswith("ALTD")):
            raise AssertionError(f"{inst} must not appear on status_d")
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
    return "status_d payload and summary"


def check_fd8():
    import app as pipshed

    fake = FakeRedis()
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPTD", _d_heartbeat())
    pipshed.r = fake
    client = pipshed.app.test_client()
    resp = client.get(f"/api/g/{TOKEN}/status_c")
    if resp.status_code != 200:
        raise AssertionError(f"expected 200, got {resp.status_code}")
    data = resp.get_json()
    if data.get("fleet") != "C":
        raise AssertionError("fleet must be C")
    summary = data.get("summary") or {}
    if summary.get("instances_live") != 0:
        raise AssertionError(f"instances_live expected 0, got {summary.get('instances_live')}")
    return "status_c ignores a Fleet D heartbeat"


def check_fd9():
    data = run_probe("fd9", {"GRIND_FLEET": "X"})
    if data["instances"] != GRIND_A_INSTANCES:
        raise AssertionError("unknown GRIND_FLEET must fall back to A list")
    return "unknown fleet -> A"


def _strip_d(fake):
    import app as pipshed
    pipshed.r = fake
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json()
    return next(f for f in data["fleets"] if f.get("letter") == "D")


def check_fd10():
    import app as pipshed
    entry = next(e for e in pipshed.FLEET_STRIP if e["letter"] == "D")
    if entry.get("instances") != GRIND_D_INSTANCES or entry.get("url") != "https://linuxd.pipshed.com":
        raise AssertionError(f"D strip entry: {entry.get('url')}, {entry.get('instances')}")
    if entry.get("placeholder") or entry.get("cycle_start") != "2026-10-01":
        raise AssertionError(f"attached 1 Oct: placeholder off, cycle_start 2026-10-01, got "
                             f"{entry.get('placeholder')}, {entry.get('cycle_start')}")
    d = _strip_d(FakeRedis())
    if d.get("placeholder") or d.get("badge") != "NO CONNECTION":
        raise AssertionError(f"attached, no heartbeats: live card, NO CONNECTION, got "
                             f"{d.get('placeholder')}, {d.get('badge')}")
    if d.get("url") != "https://linuxd.pipshed.com":
        raise AssertionError(f"card url {d.get('url')}")
    return "strip D: attached 1 Oct, live card, links linuxd"


def check_fd11():
    import app as pipshed
    # a fleet never built keeps NOT BUILT (the badge rule, not the D entry)
    card = pipshed._fleet_strip_placeholder_card(
        {"letter": "E", "name": "Fleet E", "broker": "IC Markets", "url": None,
         "instances": [], "daily_loss_limit_usd": 500.0})
    if card.get("badge") != "NOT BUILT":
        raise AssertionError(f"unbuilt fleet: NOT BUILT, got {card.get('badge')}")
    return "an unbuilt fleet still reads NOT BUILT"


def check_fd12():
    # the dashboard's placeholder branch renders the card's own name and badge
    # (it hard-coded "Fleet D -- not built yet" / NOT BUILT) and links nowhere
    # (linuxd.pipshed.com does not resolve until the Railway service exists)
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "templates", "dashboard.html"), encoding="utf-8") as fh:
        src = fh.read()
    i = src.index("if (card.placeholder) {")
    branch = src[i:src.index("}", src.index("return", i))]
    if "not built yet" in branch or "NOT BUILT</span>" in branch:
        raise AssertionError("placeholder branch still hard-codes NOT BUILT")
    if "card.badge" not in branch or "card.name" not in branch:
        raise AssertionError("placeholder branch must render card.name and card.badge")
    if "href" in branch:
        raise AssertionError("placeholder card must not link")
    return "placeholder card renders its own name and badge, no link"


CHECKS = [
    ("FD1", check_fd1),
    ("FD2", check_fd2),
    ("FD3", check_fd3),
    ("FD4", check_fd4),
    ("FD5", check_fd5),
    ("FD6", check_fd6),
    ("FD7", check_fd7),
    ("FD8", check_fd8),
    ("FD9", check_fd9),
    ("FD10", check_fd10),
    ("FD11", check_fd11),
    ("FD12", check_fd12),
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
