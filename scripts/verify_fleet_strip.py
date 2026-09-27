"""Verification for fleet strip route (/api/g/<token>/fleets) and helpers."""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ftmo_daily import ftmo_day_of_utc

TOKEN = "k7m9p2x4q"

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

EJECTION_VIEW_KEY = "fxmatrix:ejection:view"
DAILY_TABLE_KEY = "fxmatrix:daily:table"
CRITICAL_KEY = "fxmatrix:critical:last24h"

now = datetime.now(timezone.utc)
today = ftmo_day_of_utc(now)
yesterday = today - timedelta(days=1)
two_days_ago = today - timedelta(days=2)


class FakeRedis:
    def __init__(self):
        self._kv = {}

    def get(self, key):
        return self._kv.get(key)

    def set(self, key, value, ex=None):
        self._kv[key] = value


def HB(seconds_ago, **overrides):
    payload = {
        "_received_at": (now - timedelta(seconds=seconds_ago)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "net_mtm": -1.50,
        "open_layers_long": 1,
        "open_layers_short": 1,
        "halted": False,
        "account_login": 53066709,
        "account_balance": 10050.0,
        "account_equity": 9950.0,
    }
    payload.update(overrides)
    return json.dumps(payload)


def _daily_rows_fb():
    return [
        {"account_login": 53066709, "ftmo_day": yesterday.isoformat(), "balance_end": 10050.0},
        {"account_login": 1514731800, "ftmo_day": yesterday.isoformat(), "balance_end": 9000.0},
        {"account_login": 53066709, "ftmo_day": two_days_ago.isoformat(), "balance_end": 10200.0},
        {"account_login": 53066709, "ftmo_day": today.isoformat(), "balance_end": 12345.0},
    ]


def HBB(seconds_ago, **overrides):
    book = {"positions": [{"profit": -1.0}, {"profit": -0.5}]}
    return HB(seconds_ago, book=book, **overrides)


def _apply_fixture_fb(fake):
    for inst in GRIND_B_INSTANCES:
        if inst == "GRIND_GBPUSD_OPTB":
            continue
        if inst == "GRIND_EURUSD_OPTB":
            fake.set(
                f"fxmatrix:state:{inst}",
                HB(30, halted=True, halt_reason="I6_LONG"),
            )
            continue
        if inst == "GRIND_AUDCAD_OPTB":
            fake.set(f"fxmatrix:state:{inst}", HB(30, open_layers_long=5))
            continue
        if inst == "GRIND_NZDCHF_OPTB":
            fake.set(f"fxmatrix:state:{inst}", HB(30, open_layers_short=7))
            continue
        fake.set(f"fxmatrix:state:{inst}", HB(30))
    fake.set(DAILY_TABLE_KEY, json.dumps({"generated_at": now.isoformat(), "rows": _daily_rows_fb()}))


def _apply_fixture_fb2(fake, equity_override=None):
    extra = {}
    if equity_override is not None:
        extra["account_equity"] = equity_override
    for inst in GRIND_B_INSTANCES:
        if inst == "GRIND_GBPUSD_OPTB":
            continue
        if inst == "GRIND_EURUSD_OPTB":
            fake.set(
                f"fxmatrix:state:{inst}",
                HBB(30, halted=True, halt_reason="I6_LONG", **extra),
            )
            continue
        if inst == "GRIND_AUDCAD_OPTB":
            fake.set(f"fxmatrix:state:{inst}", HBB(30, open_layers_long=5, **extra))
            continue
        if inst == "GRIND_NZDCHF_OPTB":
            fake.set(f"fxmatrix:state:{inst}", HBB(30, open_layers_short=7, **extra))
            continue
        fake.set(f"fxmatrix:state:{inst}", HBB(30, **extra))
    fake.set(DAILY_TABLE_KEY, json.dumps({"generated_at": now.isoformat(), "rows": _daily_rows_fb()}))


def _alert_triples(card):
    return [
        (a.get("level"), a.get("kind"), a.get("instance_id"))
        for a in (card.get("alerts") or [])
    ]


def BK(count, gross, comm, swap, net):
    return {
        "count": count,
        "gross": gross,
        "commission": comm,
        "swap": swap,
        "net": net,
    }


Z = BK(0, 0.0, 0.0, 0.0, 0.0)


def SD(side, scalps, rolls, ejections):
    nets = [scalps.get("net"), rolls.get("net"), ejections.get("net")]
    if any(n is None for n in nets):
        closed_net = None
    else:
        closed_net = round(float(scalps["net"]) + float(rolls["net"]) + float(ejections["net"]), 2)
    return {
        "side": side,
        "scalps": scalps,
        "rolls": rolls,
        "ejections": ejections,
        "closed_net": closed_net,
    }


def _today_payload_fs25():
    return {
        "days": [
            {
                "ftmo_day": yesterday.isoformat(),
                "instances": [
                    {
                        "instance_id": "IGNORE",
                        "sides": [SD("L", BK(50, 999.0, 0.0, 0.0, 999.0), Z, Z)],
                    }
                ],
            },
            {
                "ftmo_day": today.isoformat(),
                "instances": [
                    {
                        "instance_id": "GRIND_AUDNZD_OPTB",
                        "sides": [
                            SD("L", BK(2, 1.00, -0.16, 0.0, 0.84), BK(1, -5.00, -0.08, 0.0, -5.08), Z),
                            SD("S", BK(1, 0.50, -0.08, -0.02, 0.40), Z, Z),
                        ],
                    },
                    {
                        "instance_id": "GRIND_AUDNZD_ALTB",
                        "sides": [
                            SD("L", BK(3, 1.50, -0.24, 0.0, 1.26), Z, Z),
                            SD("S", Z, Z, Z),
                        ],
                    },
                    {
                        "instance_id": "GRIND_GBPUSD_OPTB",
                        "sides": [SD("L", Z, Z, Z), SD("S", BK(1, 1.00, -0.08, 0.0, 0.92), Z, Z)],
                    },
                ],
            },
        ]
    }


def _fleet_by_letter(payload, letter):
    for card in payload.get("fleets") or []:
        if card.get("letter") == letter:
            return card
    raise AssertionError(f"fleet {letter} missing")


def _child_probe(probe_id):
    import app as pipshed

    if probe_id == "fs15":
        out = {
            "fleets": [
                {"letter": e["letter"], "is_self": e["letter"] == pipshed.GRIND_FLEET}
                for e in pipshed.FLEET_STRIP
            ]
        }
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
    import app as pipshed

    pipshed.r = FakeRedis()
    client = pipshed.app.test_client()
    resp = client.get("/api/g/wrong-token/fleets")
    if resp.status_code != 404:
        raise AssertionError(f"expected 404, got {resp.status_code}")
    if resp.get_json().get("error") != "not found":
        raise AssertionError("expected not found error")
    return "wrong token 404"


def check_fs2():
    import app as pipshed

    fake = FakeRedis()
    _apply_fixture_fb(fake)
    pipshed.r = fake
    client = pipshed.app.test_client()
    resp = client.get(f"/api/g/{TOKEN}/fleets")
    if resp.status_code != 200:
        raise AssertionError(f"expected 200, got {resp.status_code}")
    data = resp.get_json()
    letters = [c.get("letter") for c in data.get("fleets") or []]
    if letters != ["A", "B", "C", "D"]:
        raise AssertionError(f"letters expected ABCD, got {letters}")
    if data.get("ftmo_day") != today.isoformat():
        raise AssertionError(f"ftmo_day expected {today.isoformat()}, got {data.get('ftmo_day')}")
    return "fleets shape and ftmo_day"


def check_fs3():
    import app as pipshed

    fake = FakeRedis()
    _apply_fixture_fb(fake)
    pipshed.r = fake
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json()
    d = _fleet_by_letter(data, "D")
    if not d.get("placeholder"):
        raise AssertionError("D must be placeholder")
    if d.get("status") != "grey":
        raise AssertionError(f"D status expected grey, got {d.get('status')}")
    if d.get("url") is not None:
        raise AssertionError("D url must be null")
    health = d.get("health") or {}
    if health.get("instances_total") != 0 or health.get("instances_live") != 0:
        raise AssertionError("D instances counts must be 0")
    if (d.get("money") or {}).get("open_mtm") is not None:
        raise AssertionError("D open_mtm must be null")
    if (d.get("risk") or {}).get("deepest") is not None:
        raise AssertionError("D deepest must be null")
    if (d.get("risk") or {}).get("day_pnl") is not None:
        raise AssertionError("D day_pnl must be null")
    return "placeholder D"


def check_fs4():
    import app as pipshed

    fake = FakeRedis()
    _apply_fixture_fb(fake)
    pipshed.r = fake
    a = _fleet_by_letter(
        pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "A"
    )
    if (a.get("health") or {}).get("instances_total") != 11:
        raise AssertionError("A must total 11 strip instances")
    return "A total 11"


def check_fs5():
    import app as pipshed

    fake = FakeRedis()
    _apply_fixture_fb(fake)
    pipshed.r = fake
    b = _fleet_by_letter(
        pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "B"
    )
    health = b.get("health") or {}
    if health.get("instances_live") != 10:
        raise AssertionError(f"instances_live expected 10, got {health.get('instances_live')}")
    halted = health.get("halted") or []
    if halted != [{"instance_id": "GRIND_EURUSD_OPTB", "halt_reason": "I6_LONG"}]:
        raise AssertionError(f"halted mismatch: {halted}")
    if b.get("status") != "red":
        raise AssertionError(f"status expected red, got {b.get('status')}")
    money = b.get("money") or {}
    if money.get("open_mtm") != -15.00:
        raise AssertionError(f"open_mtm expected -15.00, got {money.get('open_mtm')}")
    risk = b.get("risk") or {}
    if risk.get("open_layers_long") != 14:
        raise AssertionError(f"open_layers_long expected 14, got {risk.get('open_layers_long')}")
    if risk.get("open_layers_short") != 16:
        raise AssertionError(f"open_layers_short expected 16, got {risk.get('open_layers_short')}")
    age = health.get("oldest_heartbeat_age_s")
    if age is None or age < 29 or age > 32:
        raise AssertionError(f"oldest age expected 29..32, got {age}")
    return "FB card B aggregates"


def check_fs6():
    import app as pipshed

    fake = FakeRedis()
    _apply_fixture_fb(fake)
    pipshed.r = fake
    b = _fleet_by_letter(
        pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "B"
    )
    deepest = (b.get("risk") or {}).get("deepest")
    expected = {"instance_id": "GRIND_NZDCHF_OPTB", "side": "S", "layers": 7}
    if deepest != expected:
        raise AssertionError(f"deepest expected {expected}, got {deepest}")
    acct = b.get("account") or {}
    if acct.get("login") != 53066709:
        raise AssertionError(f"login expected 53066709, got {acct.get('login')}")
    if acct.get("balance") != 10050.0 or acct.get("equity") != 9950.0:
        raise AssertionError(f"account money mismatch: {acct}")
    return "FB deepest and account"


def check_fs7():
    import app as pipshed

    fake = FakeRedis()
    _apply_fixture_fb(fake)
    pipshed.r = fake
    risk = (_fleet_by_letter(
        pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "B"
    ).get("risk") or {})
    if risk.get("day_pnl") != -100.00:
        raise AssertionError(f"day_pnl expected -100.00, got {risk.get('day_pnl')}")
    if risk.get("day_start_balance") != 10050.0:
        raise AssertionError(f"day_start_balance expected 10050.0, got {risk.get('day_start_balance')}")
    if risk.get("anchor_day") != yesterday.isoformat():
        raise AssertionError(f"anchor_day expected {yesterday.isoformat()}, got {risk.get('anchor_day')}")
    if risk.get("loss_share") != 0.2:
        raise AssertionError(f"loss_share expected 0.2, got {risk.get('loss_share')}")
    if risk.get("daily_loss_limit_usd") != 500.0:
        raise AssertionError("daily_loss_limit_usd must be 500.0")
    return "FB day pnl"


def check_fs8():
    import app as pipshed

    fake = FakeRedis()
    _apply_fixture_fb(fake)
    pipshed.r = fake
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json()
    for letter in ("A", "B", "C"):
        money = (_fleet_by_letter(data, letter).get("money") or {})
        if money.get("closed_net_today") is not None:
            raise AssertionError(f"{letter} closed_net_today must be null")
        if money.get("scalps_today") is not None:
            raise AssertionError(f"{letter} scalps_today must be null")
        if money.get("closed_reason") != "view_unavailable":
            raise AssertionError(f"{letter} closed_reason expected view_unavailable")
    return "no snapshot closed fields"


def check_fs9():
    import app as pipshed

    fake = FakeRedis()
    for inst in GRIND_C_INSTANCES:
        if inst == "GRIND_NZDCAD_ALTC":
            fake.set(f"fxmatrix:state:{inst}", HB(90))
        else:
            fake.set(f"fxmatrix:state:{inst}", HB(30))
    pipshed.r = fake
    c = _fleet_by_letter(
        pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "C"
    )
    if c.get("status") != "green":
        raise AssertionError(f"C status expected green, got {c.get('status')}")
    age = (c.get("health") or {}).get("oldest_heartbeat_age_s")
    if age is None or age < 89 or age > 92:
        raise AssertionError(f"oldest age expected 89..92, got {age}")
    return "C green stale window"


def check_fs10():
    import app as pipshed

    fake = FakeRedis()
    for inst in GRIND_C_INSTANCES:
        if inst == "GRIND_NZDCAD_ALTC":
            fake.set(f"fxmatrix:state:{inst}", HB(200))
        else:
            fake.set(f"fxmatrix:state:{inst}", HB(30))
    pipshed.r = fake
    c = _fleet_by_letter(
        pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "C"
    )
    if c.get("status") != "amber":
        raise AssertionError(f"C status expected amber, got {c.get('status')}")
    return "C amber stale"


def check_fs11():
    import app as pipshed

    fake = FakeRedis()
    _apply_fixture_fb(fake)
    pipshed.r = fake
    a = _fleet_by_letter(
        pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "A"
    )
    if a.get("status") != "no_data":
        raise AssertionError(f"A status expected no_data, got {a.get('status')}")
    for key in ("open_mtm",):
        if (a.get("money") or {}).get(key) is not None:
            raise AssertionError(f"A money.{key} must be null")
    risk = a.get("risk") or {}
    for key in ("open_layers_long", "deepest", "day_pnl"):
        if risk.get(key) is not None:
            raise AssertionError(f"A risk.{key} must be null")
    if (a.get("account") or {}).get("login") is not None:
        raise AssertionError("A account.login must be null")
    return "A no_data nulls"


def _side(count, closed_net):
    return {"scalps": {"count": count}, "closed_net": closed_net}


def check_fs12():
    import app as pipshed

    payload = {
        "days": [
            {
                "ftmo_day": yesterday.isoformat(),
                "instances": [
                    {
                        "instance_id": "X",
                        "sides": [_side(50, 99.0), _side(0, 0.0)],
                    }
                ],
            },
            {
                "ftmo_day": today.isoformat(),
                "instances": [
                    {
                        "instance_id": "X",
                        "sides": [_side(3, 1.20), _side(1, -0.30)],
                    },
                    {
                        "instance_id": "Z",
                        "sides": [_side(0, 0.0), _side(2, 0.45)],
                    },
                ],
            },
        ]
    }
    got = pipshed._fleet_strip_closed_today(payload, today.isoformat())
    if got != (6, 1.35, None):
        raise AssertionError(f"expected (6, 1.35, None), got {got}")
    return "_fleet_strip_closed_today happy path"


def check_fs13():
    import app as pipshed

    payload = {
        "days": [
            {
                "ftmo_day": today.isoformat(),
                "instances": [
                    {
                        "instance_id": "Z",
                        "sides": [_side(0, 0.0), _side(2, None)],
                    }
                ],
            }
        ]
    }
    got = pipshed._fleet_strip_closed_today(payload, today.isoformat())
    if got != (2, None, "incomplete"):
        raise AssertionError(f"incomplete expected (2, None, incomplete), got {got}")
    got2 = pipshed._fleet_strip_closed_today({"days": []}, today.isoformat())
    if got2 != (None, None, "no_day"):
        raise AssertionError(f"no_day expected, got {got2}")
    return "_fleet_strip_closed_today edge cases"


def check_fs19():
    import app as pipshed

    payload = {
        "days": [
            {
                "ftmo_day": today.isoformat(),
                "instances": [
                    {
                        "instance_id": "Z",
                        "sides": [_side(2, None), _side(3, 1.0)],
                    },
                    {
                        "instance_id": "Y",
                        "sides": [_side(1, 0.5), _side(0, 0.0)],
                    },
                ],
            }
        ]
    }
    got = pipshed._fleet_strip_closed_today(payload, today.isoformat())
    if got != (6, None, "incomplete"):
        raise AssertionError(f"incomplete FIRST expected (6, None, incomplete), got {got}")
    return "incomplete side first: every count still summed"


def check_fs14():
    import app as pipshed

    rows = _daily_rows_fb()
    got = pipshed._fleet_strip_day_pnl(rows, 53066709, 10100.0, today.isoformat(), 500.0)
    if got.get("day_pnl") != 50.00:
        raise AssertionError(f"day_pnl expected 50.00, got {got.get('day_pnl')}")
    if got.get("loss_share") != 0.0:
        raise AssertionError(f"loss_share expected 0.0, got {got.get('loss_share')}")
    if got.get("anchor_day") != yesterday.isoformat():
        raise AssertionError(f"anchor_day expected {yesterday.isoformat()}")
    decoy_only = [{"account_login": 53066709, "ftmo_day": today.isoformat(), "balance_end": 12345.0}]
    if any(v is not None for v in pipshed._fleet_strip_day_pnl(decoy_only, 53066709, 10100.0, today.isoformat(), 500.0).values()):
        raise AssertionError("decoy-only rows must yield all null")
    if any(v is not None for v in pipshed._fleet_strip_day_pnl(rows, 99, 10100.0, today.isoformat(), 500.0).values()):
        raise AssertionError("unknown login must yield all null")
    if any(v is not None for v in pipshed._fleet_strip_day_pnl(rows, 53066709, None, today.isoformat(), 500.0).values()):
        raise AssertionError("equity None must yield all null")
    return "_fleet_strip_day_pnl"


def check_fs15():
    data_b = run_probe("fs15", {"GRIND_FLEET": "B"})
    for row in data_b["fleets"]:
        if row["letter"] == "B" and not row["is_self"]:
            raise AssertionError("B must be is_self when GRIND_FLEET=B")
        if row["letter"] != "B" and row["is_self"]:
            raise AssertionError("only B is_self when GRIND_FLEET=B")
    data_a = run_probe("fs15")
    for row in data_a["fleets"]:
        if row["letter"] == "A" and not row["is_self"]:
            raise AssertionError("A must be is_self by default")
        if row["letter"] != "A" and row["is_self"]:
            raise AssertionError("only A is_self by default")
    return "is_self by GRIND_FLEET"


def check_fs16():
    import app as pipshed

    fake = FakeRedis()
    for inst in GRIND_C_INSTANCES:
        fake.set(f"fxmatrix:state:{inst}", HB(30))
    snap = {
        "built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "events": [],
        "scalps": [],
        "fill_logs": [],
    }
    fake.set(EJECTION_VIEW_KEY, json.dumps(snap))
    pipshed.r = fake
    money = (_fleet_by_letter(
        pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "C"
    ).get("money") or {})
    if money.get("scalps_today") != 0:
        raise AssertionError(f"scalps_today expected 0, got {money.get('scalps_today')}")
    if money.get("closed_net_today") != 0.0:
        raise AssertionError(f"closed_net_today expected 0.0, got {money.get('closed_net_today')}")
    if money.get("closed_reason") is not None:
        raise AssertionError(f"closed_reason expected null, got {money.get('closed_reason')}")
    return "fresh snapshot zeros"


def check_fs17():
    import app as pipshed

    html = pipshed.app.test_client().get("/").get_data(as_text=True)
    if 'id="fleetStrip"' not in html:
        raise AssertionError("missing fleetStrip div")
    if "/fleets/" not in html:
        raise AssertionError("missing fleets fetch path")
    return "dashboard fleet strip markup"


def check_fs18():
    import app as pipshed

    fake = FakeRedis()
    _apply_fixture_fb(fake)
    pipshed.r = fake
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/status_b").get_json()
    summary = data.get("summary") or {}
    if summary.get("instances_live") != 10:
        raise AssertionError(f"instances_live expected 10, got {summary.get('instances_live')}")
    if summary.get("halted_instances") != ["GRIND_EURUSD_OPTB"]:
        raise AssertionError(f"halted_instances mismatch: {summary.get('halted_instances')}")
    return "status_b regression"


def check_fs20():
    import app as pipshed

    fake = FakeRedis()
    _apply_fixture_fb2(fake)
    for inst in GRIND_C_INSTANCES:
        fake.set(f"fxmatrix:state:{inst}", HB(30))
    pipshed.r = fake
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json()
    if _fleet_by_letter(data, "B").get("badge") != "PARTIAL":
        raise AssertionError("B badge must be PARTIAL")
    if _fleet_by_letter(data, "C").get("badge") != "LIVE":
        raise AssertionError("C badge must be LIVE")
    if _fleet_by_letter(data, "A").get("badge") != "NO CONNECTION":
        raise AssertionError("A badge must be NO CONNECTION")
    if _fleet_by_letter(data, "D").get("badge") != "NOT BUILT":
        raise AssertionError("D badge must be NOT BUILT")
    return "badges FB2"


def check_fs21():
    import app as pipshed

    fake = FakeRedis()
    _apply_fixture_fb2(fake)
    pipshed.r = fake
    b = _fleet_by_letter(pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "B")
    expected = [
        ("red", "HALTED", "GRIND_EURUSD_OPTB"),
        ("amber", "NOT_REPORTING", "GRIND_GBPUSD_OPTB"),
        ("amber", "LEDGER", None),
        ("amber", "EVENTS_UNAVAILABLE", None),
    ]
    if _alert_triples(b) != expected:
        raise AssertionError(f"alerts expected {expected}, got {_alert_triples(b)}")
    return "FB2 alerts baseline"


def check_fs22():
    import app as pipshed

    fake = FakeRedis()
    _apply_fixture_fb2(fake)
    crit = {
        "generated_at": now.isoformat(),
        "rows": [
            {
                "instance_id": "GRIND_NZDCAD_OPTB",
                "level": "CRITICAL",
                "code": "STARTUP_EXIT_SHORTFALL_SIDE",
                "count": 2,
                "first_at": "2026-09-27T10:00:00Z",
                "last_at": "2026-09-27T12:00:00Z",
            },
            {
                "instance_id": "GRIND_AUDCHF_OPTB",
                "level": "WARN",
                "code": "ROLL_STRANDED",
                "count": 1,
                "first_at": "2026-09-27T11:00:00Z",
                "last_at": "2026-09-27T11:30:00Z",
            },
            {
                "instance_id": "GRIND_GBPUSD_OPT",
                "level": "CRITICAL",
                "code": "X",
                "count": 1,
                "first_at": "2026-09-27T09:00:00Z",
                "last_at": "2026-09-27T09:05:00Z",
            },
        ],
    }
    fake.set(CRITICAL_KEY, json.dumps(crit))
    pipshed.r = fake
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json()
    b = _fleet_by_letter(data, "B")
    expected_b = [
        ("red", "HALTED", "GRIND_EURUSD_OPTB"),
        ("red", "EVENT", "GRIND_NZDCAD_OPTB"),
        ("amber", "EVENT", "GRIND_AUDCHF_OPTB"),
        ("amber", "NOT_REPORTING", "GRIND_GBPUSD_OPTB"),
        ("amber", "LEDGER", None),
    ]
    if _alert_triples(b) != expected_b:
        raise AssertionError(f"B alerts expected {expected_b}, got {_alert_triples(b)}")
    red_event = next(a for a in b["alerts"] if a.get("kind") == "EVENT" and a.get("level") == "red")
    if red_event.get("code") != "STARTUP_EXIT_SHORTFALL_SIDE":
        raise AssertionError("red EVENT code mismatch")
    a_alerts = _alert_triples(_fleet_by_letter(data, "A"))
    if ("red", "EVENT", "GRIND_GBPUSD_OPT") not in a_alerts:
        raise AssertionError(f"A must include GBPUSD OPT event, got {a_alerts}")
    c_events = [t for t in _alert_triples(_fleet_by_letter(data, "C")) if t[1] == "EVENT"]
    if c_events:
        raise AssertionError(f"C must have no EVENT alerts, got {c_events}")
    return "critical feed alerts"


def check_fs23():
    import app as pipshed

    for equity, want_pnl, want_share, want_level in (
        (9800.0, -250.00, 0.5, "amber"),
        (9650.0, -400.00, 0.8, "red"),
    ):
        fake = FakeRedis()
        _apply_fixture_fb2(fake, equity_override=equity)
        pipshed.r = fake
        risk = _fleet_by_letter(
            pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "B"
        ).get("risk") or {}
        if risk.get("day_pnl") != want_pnl:
            raise AssertionError(f"day_pnl expected {want_pnl}, got {risk.get('day_pnl')}")
        if risk.get("loss_share") != want_share:
            raise AssertionError(f"loss_share expected {want_share}, got {risk.get('loss_share')}")
        alerts = _fleet_by_letter(
            pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "B"
        ).get("alerts") or []
        day_loss = [a for a in alerts if a.get("kind") == "DAY_LOSS"]
        if len(day_loss) != 1 or day_loss[0].get("level") != want_level:
            raise AssertionError(f"DAY_LOSS {want_level} expected, got {day_loss}")
    return "DAY_LOSS thresholds"


def check_fs24():
    import app as pipshed

    fake = FakeRedis()
    _apply_fixture_fb2(fake)
    pipshed.r = fake
    book = _fleet_by_letter(
        pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "B"
    ).get("book") or {}
    if book.get("positions") != 20:
        raise AssertionError(f"positions expected 20, got {book.get('positions')}")
    if book.get("pairs") != 8:
        raise AssertionError(f"pairs expected 8, got {book.get('pairs')}")
    if book.get("open_mtm_book") != -15.00:
        raise AssertionError(f"open_mtm_book expected -15.00, got {book.get('open_mtm_book')}")
    if book.get("financing") != -85.00:
        raise AssertionError(f"financing expected -85.00, got {book.get('financing')}")
    return "book stats FB2"


def check_fs25():
    import app as pipshed

    got = pipshed._fleet_strip_today(_today_payload_fs25(), today.isoformat())
    if got is None:
        raise AssertionError("expected today block")
    scalps = got.get("scalps") or {}
    if scalps.get("count") != 7 or scalps.get("gross") != 4.00:
        raise AssertionError(f"scalps aggregate wrong: {scalps}")
    if scalps.get("commission") != -0.56 or scalps.get("swap") != -0.02:
        raise AssertionError(f"scalps comm/swap wrong: {scalps}")
    if scalps.get("net") != 3.42:
        raise AssertionError(f"scalps net expected 3.42, got {scalps.get('net')}")
    rolls = got.get("rolls") or {}
    if rolls.get("count") != 1 or rolls.get("net") != -5.08:
        raise AssertionError(f"rolls wrong: {rolls}")
    eject = got.get("ejections") or {}
    if eject.get("count") != 0 or eject.get("net") != 0.0:
        raise AssertionError(f"ejections wrong: {eject}")
    if got.get("total_net") != -1.66:
        raise AssertionError(f"total_net expected -1.66, got {got.get('total_net')}")
    by_pair = got.get("by_pair") or []
    if by_pair != [
        {"pair": "GBPUSD", "scalps": 1, "net": 0.92},
        {"pair": "AUDNZD", "scalps": 6, "net": -2.58},
    ]:
        raise AssertionError(f"by_pair wrong: {by_pair}")
    if got.get("incomplete") is not False:
        raise AssertionError("incomplete must be false")
    return "_fleet_strip_today happy path"


def check_fs26():
    import app as pipshed

    payload = _today_payload_fs25()
    payload["days"][1]["instances"][1]["sides"][0]["scalps"]["net"] = None
    payload["days"][1]["instances"][1]["sides"][0]["closed_net"] = None
    got = pipshed._fleet_strip_today(payload, today.isoformat())
    if got.get("scalps", {}).get("net") is not None:
        raise AssertionError("scalps.net must be null")
    if got.get("scalps", {}).get("gross") != 4.00 or got.get("scalps", {}).get("count") != 7:
        raise AssertionError("scalps gross/count must still sum")
    if got.get("total_net") is not None:
        raise AssertionError("total_net must be null")
    aud = next(p for p in got.get("by_pair") or [] if p.get("pair") == "AUDNZD")
    if aud.get("net") is not None:
        raise AssertionError("AUDNZD net must be null")
    if got.get("incomplete") is not True:
        raise AssertionError("incomplete must be true")
    if pipshed._fleet_strip_today({"days": []}, today.isoformat()) is not None:
        raise AssertionError("no today block must return None")
    return "_fleet_strip_today incomplete"


def check_fs27():
    import app as pipshed

    got = pipshed._fleet_strip_cycle("2026-09-24", 10000.0, 10050.0, 9950.0, "2026-09-28")
    if got.get("day") != 3 or got.get("realised") != 50.00 or got.get("equity_change") != -50.00:
        raise AssertionError(f"cycle 28 wrong: {got}")
    got2 = pipshed._fleet_strip_cycle("2026-09-24", 10000.0, 10050.0, 9950.0, "2026-09-27")
    if got2.get("day") != 2:
        raise AssertionError(f"cycle 27 day expected 2, got {got2.get('day')}")
    got3 = pipshed._fleet_strip_cycle("2026-09-28", 10000.0, 10000.0, 10000.0, "2026-09-27")
    if got3.get("day") is not None:
        raise AssertionError("day must be null when today before start")
    if got3.get("realised") != 0.0 or got3.get("equity_change") != 0.0:
        raise AssertionError(f"realised/equity wrong: {got3}")
    got4 = pipshed._fleet_strip_cycle("2026-09-24", 10000.0, None, 9950.0, "2026-09-27")
    if got4.get("realised") is not None:
        raise AssertionError("realised null when balance None")
    return "_fleet_strip_cycle"


def check_fs28():
    import app as pipshed

    html = pipshed.app.test_client().get("/").get_data(as_text=True)
    for marker in ("fleet-badge", "fleet-alerts", "fleet-equity"):
        if marker not in html:
            raise AssertionError(f"missing class marker {marker}")
    return "v2 template markers"


def check_fs29():
    import app as pipshed

    html = pipshed.app.test_client().get("/").get_data(as_text=True)
    for marker in ("fleet-legend", "How to read the fleet alerts", "QUARANTINE_ENTER",
                   "STARTUP_EXIT_SHORTFALL_SIDE", "EVENTS_UNAVAILABLE", "red means act"):
        if marker not in html:
            raise AssertionError(f"legend missing {marker!r}")
    return "alert legend on the page"


def check_fs30():
    import app as pipshed

    html = pipshed.app.test_client().get("/").get_data(as_text=True)
    if "alert.kind === 'EVENT' && alert.code" not in html:
        raise AssertionError("EVENT alert lines must lead with the event code")
    return "EVENT lines print the code"


CHECKS = [
    ("FS1", check_fs1),
    ("FS2", check_fs2),
    ("FS3", check_fs3),
    ("FS4", check_fs4),
    ("FS5", check_fs5),
    ("FS6", check_fs6),
    ("FS7", check_fs7),
    ("FS8", check_fs8),
    ("FS9", check_fs9),
    ("FS10", check_fs10),
    ("FS11", check_fs11),
    ("FS12", check_fs12),
    ("FS13", check_fs13),
    ("FS14", check_fs14),
    ("FS19", check_fs19),
    ("FS15", check_fs15),
    ("FS16", check_fs16),
    ("FS17", check_fs17),
    ("FS18", check_fs18),
    ("FS20", check_fs20),
    ("FS21", check_fs21),
    ("FS22", check_fs22),
    ("FS23", check_fs23),
    ("FS24", check_fs24),
    ("FS25", check_fs25),
    ("FS26", check_fs26),
    ("FS27", check_fs27),
    ("FS28", check_fs28),
    ("FS29", check_fs29),
    ("FS30", check_fs30),
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
