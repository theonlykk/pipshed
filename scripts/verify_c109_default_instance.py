"""Verification: C109, the page opens on the fleet's default instance.

pipshed.com 2 Oct 2026: the top-right badge read CONNECTION LOST with every
fleet card LIVE. Cause: the page chose its opening instance as
GRIND_INSTANCES[0] in the browser, and that list is built from the rings
JSON, which Jinja's tojson emits with SORTED keys. So the first ring is
aud_cad_chf and the opening instance was GRIND_AUDCAD_OPT, retired from
cycle 3 that afternoon (fxmatrix geometry-cycle3 A7). Its Redis state key
is gone, so /api/telemetry/live answers "connection_lost" every 5 s.

Rule: the page opens on the server's GRIND_DEFAULT_INSTANCE (the first id
of the fleet's own list: GBPUSD on every fleet), passed into the template,
and falls back to the first ring instance only if that id is not on the
page. Clicking a tile still selects that tile.

Tests first. Predicted at the tests-only commit: DD1, DD2 and DD3 FAIL;
DD4 is a guard that passes in both states.

    python scripts/verify_c109_default_instance.py
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RETIRED = {"GRIND_AUDNZD_ALT", "GRIND_NZDCAD_ALT", "GRIND_AUDCAD_OPT", "GRIND_NZDCHF_OPT"}
OPEN_RE = re.compile(r"let currentInstance = (\"[A-Z0-9_]+\");")


def _template_text():
    with open(os.path.join(ROOT, "templates", "dashboard.html"), encoding="utf-8") as f:
        return f.read()


def _child_probe():
    sys.path.insert(0, ROOT)
    import app as pipshed

    page = pipshed.app.test_client().get("/").get_data(as_text=True)
    m = OPEN_RE.search(page)
    print(json.dumps({
        "fleet": pipshed.GRIND_FLEET,
        "default": pipshed.GRIND_DEFAULT_INSTANCE,
        "first": pipshed.GRIND_INSTANCES[0],
        "opens_on": json.loads(m.group(1)) if m else None,
        "strip_a": list(pipshed.GRIND_A_STRIP_INSTANCES),
    }))


def run_probe(fleet):
    env = os.environ.copy()
    env.pop("GRIND_FLEET_LABEL", None)
    env["GRIND_FLEET"] = fleet
    env["PIPSHED_C109_PROBE"] = "1"
    result = subprocess.run([sys.executable, __file__], env=env,
                            capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    for line in reversed(result.stdout.splitlines()):
        if line.strip().startswith("{"):
            return json.loads(line)
    raise RuntimeError("probe produced no JSON")


def check_dd1():
    """Fleet A's page opens on GRIND_GBPUSD_OPT, not on a retired instance."""
    d = run_probe("A")
    if d["opens_on"] != "GRIND_GBPUSD_OPT":
        raise AssertionError(f"page opens on {d['opens_on']!r}, want 'GRIND_GBPUSD_OPT'")
    return "opens on GRIND_GBPUSD_OPT"


def check_dd2():
    """Fleets B, C and D open on their own default (= first id of their list)."""
    seen = []
    for fleet in ("B", "C", "D"):
        d = run_probe(fleet)
        if d["fleet"] != fleet:
            raise AssertionError(f"GRIND_FLEET={fleet} loaded fleet {d['fleet']}")
        if d["opens_on"] != d["default"] or d["default"] != d["first"]:
            raise AssertionError(
                f"fleet {fleet}: opens on {d['opens_on']!r}, default {d['default']!r}, "
                f"first {d['first']!r}")
        seen.append(f"{fleet}={d['opens_on']}")
    return ", ".join(seen)


def check_dd3():
    """The template takes the server default, with a fallback, not GRIND_INSTANCES[0]."""
    raw = _template_text()
    if "let currentInstance = GRIND_INSTANCES[0];" in raw:
        raise AssertionError("template still opens on GRIND_INSTANCES[0] (sorted rings)")
    if "{{ default_instance|tojson }}" not in raw:
        raise AssertionError("template does not read default_instance")
    if "GRIND_INSTANCES.indexOf(currentInstance) === -1" not in raw:
        raise AssertionError("no fallback when the default is not on the page")
    return "server default + fallback"


def check_dd4():
    """Guard: no fleet's default is a retired instance; A's is in the A strip."""
    for fleet in ("A", "B", "C", "D"):
        d = run_probe(fleet)
        if d["default"] in RETIRED:
            raise AssertionError(f"fleet {fleet} default {d['default']} is retired")
        if fleet == "A" and d["default"] not in d["strip_a"]:
            raise AssertionError(f"fleet A default {d['default']} not in the A strip")
    return "defaults live"


CHECKS = [("DD1", check_dd1), ("DD2", check_dd2), ("DD3", check_dd3), ("DD4", check_dd4)]


def main():
    if os.environ.get("PIPSHED_C109_PROBE"):
        _child_probe()
        return
    failed = 0
    for name, fn in CHECKS:
        try:
            print(f"{name} PASS: {fn()}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"{name} FAIL: {fn.__doc__.strip()} -- {exc}")
    print(f"{len(CHECKS) - failed}/{len(CHECKS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
