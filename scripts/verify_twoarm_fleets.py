"""Verification: two-arm fleets (C/D ALT arms, retirements, fleet E placeholder).

Hand-written expectations from prompts/cursor_twoarm_fleets.md s2-s4; never read lists from app.py.

    python scripts/verify_twoarm_fleets.py
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TOKEN = "k7m9p2x4q"

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
    "GRIND_EURUSD_ALTC",
    "GRIND_AUDCAD_ALTC",
    "GRIND_GBPCHF_OPTC",
    "GRIND_GBPCHF_ALTC",
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
    "GRIND_GBPUSD_ALTD",
    "GRIND_EURUSD_ALTD",
    "GRIND_EURGBP_ALTD",
    "GRIND_AUDCAD_ALTD",
    "GRIND_AUDCHF_ALTD",
    "GRIND_CADCHF_ALTD",
]

GRIND_E_INSTANCES = [
    "GRIND_GBPUSD_OPTE",
    "GRIND_GBPUSD_ALTE",
    "GRIND_EURUSD_OPTE",
    "GRIND_EURUSD_ALTE",
    "GRIND_EURGBP_OPTE",
    "GRIND_EURGBP_ALTE",
    "GRIND_AUDCAD_OPTE",
    "GRIND_AUDCAD_ALTE",
    "GRIND_AUDCHF_OPTE",
    "GRIND_AUDCHF_ALTE",
    "GRIND_CADCHF_OPTE",
    "GRIND_CADCHF_ALTE",
]

RETIRED = frozenset({
    "GRIND_AUDNZD_ALT",
    "GRIND_NZDCAD_ALT",
    "GRIND_AUDCAD_OPT",
    "GRIND_NZDCHF_OPT",
    "GRIND_AUDNZD_ALTB",
    "GRIND_NZDCAD_ALTB",
    "GRIND_AUDNZD_ALTC",
    "GRIND_NZDCAD_ALTC",
    "GRIND_AUDNZD_ALTD",
    "GRIND_NZDCAD_ALTD",
    "GRIND_NZDCHF_OPTD",
    "GRIND_NZDCAD_OPTD",
    "GRIND_AUDNZD_OPTD",
    "GRIND_GBPUSD_OPTC",
    "GRIND_EURGBP_OPTC",
    "GRIND_AUDCHF_OPTC",
    "GRIND_CADCHF_OPTC",
    "GRIND_NZDCHF_OPTC",
    "GRIND_NZDCAD_OPTC",
    "GRIND_AUDNZD_OPTC",
})

GRIND_B_STRIP = [
    "GRIND_GBPUSD_OPTB",
    "GRIND_EURUSD_OPTB",
    "GRIND_EURGBP_OPTB",
    "GRIND_AUDCAD_OPTB",
    "GRIND_AUDCHF_OPTB",
    "GRIND_CADCHF_OPTB",
    "GRIND_NZDCHF_OPTB",
    "GRIND_NZDCAD_OPTB",
    "GRIND_AUDNZD_OPTB",
]

GRIND_C_STRIP = [
    "GRIND_EURUSD_OPTC",
    "GRIND_AUDCAD_OPTC",
    "GRIND_EURUSD_ALTC",
    "GRIND_AUDCAD_ALTC",
    "GRIND_GBPCHF_OPTC",
    "GRIND_GBPCHF_ALTC",
]

GRIND_D_STRIP = [
    "GRIND_GBPUSD_OPTD",
    "GRIND_EURUSD_OPTD",
    "GRIND_EURGBP_OPTD",
    "GRIND_AUDCAD_OPTD",
    "GRIND_AUDCHF_OPTD",
    "GRIND_CADCHF_OPTD",
    "GRIND_GBPUSD_ALTD",
    "GRIND_EURUSD_ALTD",
    "GRIND_EURGBP_ALTD",
    "GRIND_AUDCAD_ALTD",
    "GRIND_AUDCHF_ALTD",
    "GRIND_CADCHF_ALTD",
]

BOOKS_ROWS = [
    "GBPUSD", "EURUSD", "EURGBP", "AUDCHF", "CADCHF", "NZDCAD", "AUDNZD", "AUDCAD", "NZDCHF",
    "EURUSD*", "AUDCAD*", "GBPCHF", "GBPCHF*", "GBPUSD*", "EURGBP*", "AUDCHF*", "CADCHF*",
]

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

GRIND_A_STRIP = [
    "GRIND_GBPUSD_OPT",
    "GRIND_EURUSD_OPT",
    "GRIND_EURGBP_OPT",
    "GRIND_AUDCHF_OPT",
    "GRIND_CADCHF_OPT",
    "GRIND_NZDCAD_OPT",
    "GRIND_AUDNZD_OPT",
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

FLEET_META_ABCD = {
    "A": {
        "name": "FTMO-IC 1514878887",
        "broker": "FTMO",
        "url": "https://pipshed.com",
        "lattice": True,
        "daily_loss_limit_usd": 500.0,
        "cycle_start": "2026-10-08",
        "start_balance": 10000.0,
        "placeholder": False,
    },
    "B": {
        "name": "Fleet B (IC)",
        "broker": "IC Markets",
        "url": "https://linux.pipshed.com",
        "lattice": True,
        "daily_loss_limit_usd": 500.0,
        "cycle_start": "2026-09-24",
        "start_balance": 10000.0,
        "placeholder": False,
    },
    "C": {
        "name": "Fleet C (IC)",
        "broker": "IC Markets",
        "url": "https://linuxc.pipshed.com",
        "lattice": True,
        "daily_loss_limit_usd": 500.0,
        "cycle_start": "2026-09-28",
        "start_balance": 10000.0,
        "placeholder": False,
    },
    "D": {
        "name": "Fleet D (IC)",
        "broker": "IC Markets",
        "url": "https://linuxd.pipshed.com",
        "lattice": True,
        "daily_loss_limit_usd": 500.0,
        "cycle_start": "2026-10-01",
        "start_balance": 10000.0,
        "placeholder": False,
        "built": True,
    },
}

E_FLEET_ENTRY = {
    "letter": "E",
    "name": "Fleet E (FTMO two-arm)",
    "broker": "FTMO",
    "url": "https://linuxe.pipshed.com",
    "lattice": True,
    "daily_loss_limit_usd": 500.0,
    "cycle_start": "2026-10-23",
    "start_balance": 10000.0,
    "placeholder": False,
    "built": True,
}


class FakeRedis:
    def __init__(self):
        self._kv = {}

    def get(self, key):
        return self._kv.get(key)

    def set(self, key, value, ex=None):
        self._kv[key] = value

    def mget(self, keys):
        return [self._kv.get(k) for k in keys]

    def lrange(self, key, start, end):
        return []


def _child_probe(probe_id):
    import app as pipshed

    if probe_id == "ta6":
        print(json.dumps({
            "instances": list(pipshed.GRIND_INSTANCES),
            "opt": list(pipshed.GRIND_OPT_INSTANCES),
            "alt": list(pipshed.GRIND_ALT_INSTANCES),
            "default": pipshed.GRIND_DEFAULT_INSTANCE,
        }))
    elif probe_id == "ta8":
        rings = {}
        for rid in pipshed.GRIND_RINGS:
            rings[rid] = list(pipshed._grind_instances_for_ring(rid))
        on_ring = set()
        for inst in pipshed.GRIND_INSTANCES:
            n = sum(1 for rid in pipshed.GRIND_RINGS if inst in rings[rid])
            if n != 1:
                print(json.dumps({"error": inst, "count": n}))
                return
            on_ring.add(inst)
        print(json.dumps({
            "gbpchf": rings.get("gbpchf"),
            "all_covered": len(on_ring) == len(pipshed.GRIND_INSTANCES),
        }))
    elif probe_id.startswith("ta11_"):
        fleet = probe_id.split("_", 1)[1]
        print(json.dumps({"fleet": pipshed.GRIND_FLEET, "default": pipshed.GRIND_DEFAULT_INSTANCE}))
    else:
        raise ValueError(probe_id)


def run_probe(probe_id, extra_env=None):
    env = os.environ.copy()
    env.pop("GRIND_FLEET", None)
    env.pop("GRIND_FLEET_LABEL", None)
    if extra_env:
        env.update(extra_env)
    env["PIPSHED_PROBE"] = probe_id
    res = subprocess.run([sys.executable, __file__], env=env, capture_output=True, text=True, cwd=ROOT)
    if res.returncode != 0:
        raise RuntimeError(res.stderr or res.stdout)
    for line in reversed(res.stdout.splitlines()):
        if line.strip().startswith("{"):
            return json.loads(line)
    raise RuntimeError("no JSON from probe")


def check_ta1():
    import app as pipshed

    if list(pipshed.GRIND_C_INSTANCES) != GRIND_C_INSTANCES:
        raise AssertionError("GRIND_C_INSTANCES mismatch")
    if list(pipshed.GRIND_D_INSTANCES) != GRIND_D_INSTANCES:
        raise AssertionError("GRIND_D_INSTANCES mismatch")
    if list(pipshed.GRIND_E_INSTANCES) != GRIND_E_INSTANCES:
        raise AssertionError("GRIND_E_INSTANCES mismatch")
    return "C, D, E instance lists"


def check_ta2():
    import app as pipshed

    if set(pipshed.GRIND_RETIRED_INSTANCES) != RETIRED:
        raise AssertionError(f"GRIND_RETIRED_INSTANCES mismatch: {sorted(pipshed.GRIND_RETIRED_INSTANCES)}")
    return "twenty retired ids"


def check_ta3():
    import app as pipshed

    if list(pipshed.GRIND_B_STRIP_INSTANCES) != GRIND_B_STRIP:
        raise AssertionError(f"B strip {pipshed.GRIND_B_STRIP_INSTANCES}")
    if list(pipshed.GRIND_C_STRIP_INSTANCES) != GRIND_C_STRIP:
        raise AssertionError(f"C strip {pipshed.GRIND_C_STRIP_INSTANCES}")
    if list(pipshed.GRIND_D_STRIP_INSTANCES) != GRIND_D_STRIP:
        raise AssertionError(f"D strip {pipshed.GRIND_D_STRIP_INSTANCES}")
    if list(pipshed.GRIND_E_STRIP_INSTANCES) != GRIND_E_INSTANCES:
        raise AssertionError(f"E strip {pipshed.GRIND_E_STRIP_INSTANCES}")
    return "B/C/D/E strip lists"


def check_ta4():
    import app as pipshed

    letters = [e["letter"] for e in pipshed.FLEET_STRIP]
    if letters != ["A", "B", "C", "D", "E"]:
        raise AssertionError(f"FLEET_STRIP letters {letters}")
    e = next(x for x in pipshed.FLEET_STRIP if x["letter"] == "E")
    want = dict(E_FLEET_ENTRY)
    want["instances"] = GRIND_E_INSTANCES
    got = {k: e.get(k) for k in want}
    if got != want:
        raise AssertionError(f"E entry {got} != {want}")
    return "five fleets; E built fields"


def check_ta5():
    import app as pipshed

    cases = {
        "GRIND_EURUSD_OPTE": "OPT",
        "GRIND_EURUSD_ALTE": "ALT",
        "GRIND_GBPCHF_ALTC": "ALT",
        "GRIND_EURUSD_ALTD": "ALT",
        "GRIND_EURUSD_OPT": "OPT",
    }
    for inst, want in cases.items():
        if pipshed._grind_slot(inst) != want:
            raise AssertionError(f"_grind_slot({inst}) != {want}")
    return "_grind_slot OPTE/ALTE and A unchanged"


def check_ta6():
    d = run_probe("ta6", {"GRIND_FLEET": "E"})
    opt = [i for i in GRIND_E_INSTANCES if i.endswith("_OPTE")]
    alt = [i for i in GRIND_E_INSTANCES if i.endswith("_ALTE")]
    if d["instances"] != GRIND_E_INSTANCES or d["opt"] != opt or d["alt"] != alt:
        raise AssertionError(f"E fleet arms: {d}")
    if d["default"] != "GRIND_GBPUSD_OPTE":
        raise AssertionError(f"E default {d['default']}")
    return "GRIND_FLEET=E lists and default"


def check_ta7():
    import app as pipshed

    pipshed.r = FakeRedis()
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json()
    cards = data.get("fleets") or []
    if len(cards) != 5:
        raise AssertionError(f"expected 5 cards, got {len(cards)}")
    e = next(c for c in cards if c.get("letter") == "E")
    if e.get("placeholder") or e.get("badge") == "NOT BUILT":
        raise AssertionError(f"E card {e.get('badge')} placeholder={e.get('placeholder')}")
    if e.get("url") != "https://linuxe.pipshed.com":
        raise AssertionError(f"E url {e.get('url')}")
    books = data.get("books") or {}
    if books.get("fleets") != ["A", "B", "C", "D", "E"]:
        raise AssertionError(f"books fleets {books.get('fleets')}")
    return "five cards; E built; books ABCDE"


def check_ta8():
    d = run_probe("ta8", {"GRIND_FLEET": "C"})
    if d.get("gbpchf") != ["GRIND_GBPCHF_OPTC", "GRIND_GBPCHF_ALTC"]:
        raise AssertionError(f"gbpchf ring {d.get('gbpchf')}")
    if not d.get("all_covered"):
        raise AssertionError("some C instance is not in exactly one ring")
    return "gbpchf ring and full C coverage"


def check_ta10():
    import app as pipshed

    pipshed.r = FakeRedis()
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json()
    rows = [r["pair"] for r in (data.get("books") or {}).get("rows", [])]
    if rows != BOOKS_ROWS:
        raise AssertionError(f"books rows {rows}")
    return "seventeen book rows (TA10)"


def check_ta11():
    for fleet, want in (("C", "GRIND_EURUSD_OPTC"), ("D", "GRIND_GBPUSD_OPTD"), ("E", "GRIND_GBPUSD_OPTE")):
        d = run_probe(f"ta11_{fleet}", {"GRIND_FLEET": fleet})
        if d["default"] != want:
            raise AssertionError(f"fleet {fleet} default {d['default']} != {want}")
    return "defaults C/D/E"


def check_ta9():
    import app as pipshed

    if list(pipshed.GRIND_A_INSTANCES) != GRIND_A_INSTANCES:
        raise AssertionError("GRIND_A_INSTANCES changed")
    if list(pipshed.GRIND_A_STRIP_INSTANCES) != GRIND_A_STRIP:
        raise AssertionError("GRIND_A_STRIP_INSTANCES changed")
    if list(pipshed.GRIND_B_INSTANCES) != GRIND_B_INSTANCES:
        raise AssertionError("GRIND_B_INSTANCES changed")
    for entry in pipshed.FLEET_STRIP:
        letter = entry["letter"]
        if letter not in FLEET_META_ABCD:
            continue
        meta = {k: entry.get(k) for k in FLEET_META_ABCD[letter]}
        if meta != FLEET_META_ABCD[letter]:
            raise AssertionError(f"fleet {letter} metadata {meta}")
    return "A/B lists and A-D metadata unchanged"


CHECKS = [
    ("TA1", check_ta1), ("TA2", check_ta2), ("TA3", check_ta3), ("TA4", check_ta4),
    ("TA5", check_ta5), ("TA6", check_ta6), ("TA7", check_ta7), ("TA8", check_ta8),
    ("TA10", check_ta10), ("TA11", check_ta11), ("TA9", check_ta9),
]


def main():
    if os.environ.get("PIPSHED_PROBE"):
        _child_probe(os.environ["PIPSHED_PROBE"])
        return
    passed = failed = 0
    for name, fn in CHECKS:
        try:
            print(f"{name} OK: {fn()}")
            passed += 1
        except Exception as exc:
            print(f"{name} FAIL: {exc}")
            failed += 1
    print(f"verify_twoarm_fleets {passed}/{passed + failed}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
