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
        self._lists = {}

    def get(self, key):
        return self._kv.get(key)

    def set(self, key, value, ex=None):
        self._kv[key] = value

    def lrange(self, key, start, end):
        items = self._lists.get(key, [])
        return items[start:] if end == -1 else items[start:end + 1]


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
    # Fleet D attached 1 Oct 2026 (wine-d, IC 53077984): a live card, not a
    # placeholder; cycle from 2026-10-01; NO CONNECTION until its heartbeats
    # arrive, LIVE when all eleven report.
    import app as pipshed

    fake = FakeRedis()
    _apply_fixture_fb(fake)
    pipshed.r = fake
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json()
    d = _fleet_by_letter(data, "D")
    if d.get("placeholder"):
        raise AssertionError("D must not be a placeholder after the 1 Oct attach")
    if d.get("url") != "https://linuxd.pipshed.com":
        raise AssertionError(f"D url expected linuxd, got {d.get('url')}")
    health = d.get("health") or {}
    # C119: D's strip is its nine _OPT instances (the twins retired)
    if health.get("instances_total") != 9 or health.get("instances_live") != 0:
        raise AssertionError(f"D counts expected 9/0, got {health}")
    if d.get("badge") != "NO CONNECTION":
        raise AssertionError(f"D badge with no heartbeats: NO CONNECTION, got {d.get('badge')}")
    if (d.get("cycle") or {}).get("start_date") != "2026-10-01":
        raise AssertionError(f"D cycle start expected 2026-10-01, got {d.get('cycle')}")
    for inst in GRIND_D_INSTANCES:
        fake.set(f"fxmatrix:state:{inst}", HB(30, account_login=53077984))
    d = _fleet_by_letter(pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "D")
    if d.get("badge") != "LIVE" or (d.get("health") or {}).get("instances_live") != 9:
        raise AssertionError(f"D with all heartbeats: LIVE 9 (strip), got {d.get('badge')}, {d.get('health')}")
    return "D live card (attached 1 Oct)"


def check_fs4():
    import app as pipshed

    fake = FakeRedis()
    _apply_fixture_fb(fake)
    pipshed.r = fake
    a = _fleet_by_letter(
        pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "A"
    )
    # 2 Oct 2026: cycle 3 cut to the seven-pair ring after FTMO's
    # hyperactivity warning (fxmatrix geometry-cycle3 A7); was 11.
    if (a.get("health") or {}).get("instances_total") != 7:
        raise AssertionError("A must total 7 strip instances (the ring)")
    return "A total 7"


def check_fs5():
    import app as pipshed

    fake = FakeRedis()
    _apply_fixture_fb(fake)
    pipshed.r = fake
    b = _fleet_by_letter(
        pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "B"
    )
    health = b.get("health") or {}
    # C119: B's strip is nine (twins retired); GBPUSD silent -> 8 live
    if health.get("instances_live") != 8:
        raise AssertionError(f"instances_live expected 8, got {health.get('instances_live')}")
    halted = health.get("halted") or []
    if halted != [{"instance_id": "GRIND_EURUSD_OPTB", "halt_reason": "I6_LONG"}]:
        raise AssertionError(f"halted mismatch: {halted}")
    if b.get("status") != "red":
        raise AssertionError(f"status expected red, got {b.get('status')}")
    money = b.get("money") or {}
    # 8 live x -1.50
    if money.get("open_mtm") != -12.00:
        raise AssertionError(f"open_mtm expected -12.00, got {money.get('open_mtm')}")
    risk = b.get("risk") or {}
    # long: AUDCAD 5 + seven others x 1 = 12; short: NZDCHF 7 + seven others x 1 = 14
    if risk.get("open_layers_long") != 12:
        raise AssertionError(f"open_layers_long expected 12, got {risk.get('open_layers_long')}")
    if risk.get("open_layers_short") != 14:
        raise AssertionError(f"open_layers_short expected 14, got {risk.get('open_layers_short')}")
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
        if inst == "GRIND_NZDCAD_OPTC":   # C119: a strip instance (the twin retired)
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
        if inst == "GRIND_NZDCAD_OPTC":   # C119: a strip instance (the twin retired)
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
    if _fleet_by_letter(data, "D").get("badge") != "NO CONNECTION":
        raise AssertionError("D badge must be NO CONNECTION (attached 1 Oct; no D heartbeats here)")
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
    # C119: 8 live strip instances x 2 positions
    if book.get("positions") != 16:
        raise AssertionError(f"positions expected 16, got {book.get('positions')}")
    if book.get("pairs") != 8:
        raise AssertionError(f"pairs expected 8, got {book.get('pairs')}")
    # 16 x (-1.0, -0.5 per instance) = 8 x -1.5 = -12.00; financing 9950 - 10050 + 12 = -88.00
    if book.get("open_mtm_book") != -12.00:
        raise AssertionError(f"open_mtm_book expected -12.00, got {book.get('open_mtm_book')}")
    if book.get("financing") != -88.00:
        raise AssertionError(f"financing expected -88.00, got {book.get('financing')}")
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


# FS31-FS35 (resolved halt events): a halt clears only when the EA restarts
# (g_grind_halted is reset in OnInit), so a halt-family CRITICAL event on an
# instance that is live, not halted and invariant_ok true NOW is history.
# Such rows become level "resolved" (grey), sorted after amber. Predicted at
# the tests-only commit: FS31 and FS34 FAIL; FS32, FS33 and FS35 are guards
# that pass in both states (they pin what must NOT change).
def _crit_rows_resolved():
    return {
        "generated_at": now.isoformat(),
        "rows": [
            {"instance_id": "GRIND_GBPUSD_OPTC", "level": "CRITICAL", "code": "INVARIANT_FAIL",
             "count": 2, "first_at": "2026-09-28T16:27:38Z", "last_at": "2026-09-28T16:27:40Z"},
            {"instance_id": "GRIND_GBPUSD_OPTC", "level": "CRITICAL", "code": "QUARANTINE_HALT",
             "count": 1, "first_at": "2026-09-28T16:27:38Z", "last_at": "2026-09-28T16:27:38Z"},
            {"instance_id": "GRIND_GBPUSD_OPTC", "level": "WARN", "code": "QUARANTINE_ENTER",
             "count": 12, "first_at": "2026-09-28T09:56:58Z", "last_at": "2026-09-28T16:59:00Z"},
            {"instance_id": "GRIND_EURUSD_OPTC", "level": "CRITICAL", "code": "STARTUP_EXIT_SHORTFALL_SIDE",
             "count": 1, "first_at": "2026-09-28T16:57:11Z", "last_at": "2026-09-28T16:57:11Z"},
        ],
    }


def _fleet_c_live(fake, gbpusd_hb):
    for inst in GRIND_C_INSTANCES:
        fake.set(f"fxmatrix:state:{inst}",
                 gbpusd_hb if inst == "GRIND_GBPUSD_OPTC"
                 else HBB(30, account_login=53071896, invariant_ok=True))
    fake.set(DAILY_TABLE_KEY, json.dumps({"generated_at": now.isoformat(), "rows": _daily_rows_fb()}))


def _c_alerts(fake):
    import app as pipshed

    fake.set(CRITICAL_KEY, json.dumps(_crit_rows_resolved()))
    pipshed.r = fake
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json()
    return _fleet_by_letter(data, "C")


def check_fs31():
    fake = FakeRedis()
    _fleet_c_live(fake, HBB(30, account_login=53071896, invariant_ok=True))
    c = _c_alerts(fake)
    got = [(a.get("level"), a.get("code"), a.get("instance_id")) for a in c.get("alerts") or []
           if a.get("kind") == "EVENT"]            # the fixture's LEDGER alert is out of scope
    expected = [
        ("red", "STARTUP_EXIT_SHORTFALL_SIDE", "GRIND_EURUSD_OPTC"),
        ("amber", "QUARANTINE_ENTER", "GRIND_GBPUSD_OPTC"),
        ("resolved", "INVARIANT_FAIL", "GRIND_GBPUSD_OPTC"),
        ("resolved", "QUARANTINE_HALT", "GRIND_GBPUSD_OPTC"),
    ]
    if got != expected:
        raise AssertionError(f"expected {expected}, got {got}")
    for a in c["alerts"]:
        if a.get("level") == "resolved" and not str(a.get("detail", "")).endswith("resolved: instance running again"):
            raise AssertionError(f"resolved detail must end 'resolved: instance running again': {a}")
    return "halt events on a healthy instance are resolved, grey, after amber"


def check_fs32():
    fake = FakeRedis()
    # halted with invariant_ok TRUE (a REBUILD_EXIT_FAILED halt is not an
    # invariant failure): only the halted state may keep the events red
    _fleet_c_live(fake, HBB(30, account_login=53071896, halted=True,
                            halt_reason="REBUILD_EXIT_FAILED", invariant_ok=True))
    c = _c_alerts(fake)
    got = [(a.get("level"), a.get("code")) for a in c.get("alerts") or []
           if a.get("instance_id") == "GRIND_GBPUSD_OPTC"]
    for want in (("red", "HALTED"), ("red", "INVARIANT_FAIL"), ("red", "QUARANTINE_HALT")):
        if want not in got:
            raise AssertionError(f"halted instance must keep {want}, got {got}")
    return "a still-halted instance keeps its red halt events"


def check_fs33():
    fake = FakeRedis()
    _fleet_c_live(fake, HBB(30, account_login=53071896, invariant_ok=True))
    c = _c_alerts(fake)
    row = [a for a in c.get("alerts") or [] if a.get("code") == "STARTUP_EXIT_SHORTFALL_SIDE"]
    if len(row) != 1 or row[0].get("level") != "red":
        raise AssertionError(f"a non-halt CRITICAL stays red on a healthy instance, got {row}")
    return "non-halt CRITICAL codes are never resolved"


def check_fs34():
    import app as pipshed

    html = pipshed.app.test_client().get("/").get_data(as_text=True)
    if ".fleet-alerts.sev-resolved" not in html:
        raise AssertionError("a grey sev-resolved banner style is required")
    if "a.level === 'amber'" not in html:
        raise AssertionError("banner severity must fall back red -> amber -> resolved")
    if "grey" not in html.lower() or "resolved" not in html.lower():
        raise AssertionError("the alert legend must explain grey = resolved")
    return "grey banner and legend for resolved events"


def check_fs35():
    fake = FakeRedis()
    # live, not halted, but in quarantine now (invariant_ok false): not resolved
    _fleet_c_live(fake, HBB(30, account_login=53071896, invariant_ok=False))
    c = _c_alerts(fake)
    got = [(a.get("level"), a.get("code")) for a in c.get("alerts") or []
           if a.get("instance_id") == "GRIND_GBPUSD_OPTC"]
    if ("red", "INVARIANT_FAIL") not in got or ("red", "QUARANTINE_HALT") not in got:
        raise AssertionError(f"invariant_ok false keeps halt events red, got {got}")
    # and a heartbeat with no invariant_ok key at all (older builds) stays red too
    fake2 = FakeRedis()
    _fleet_c_live(fake2, HBB(30, account_login=53071896))
    c2 = _c_alerts(fake2)
    got2 = [(a.get("level"), a.get("code")) for a in c2.get("alerts") or []
            if a.get("instance_id") == "GRIND_GBPUSD_OPTC"]
    if ("red", "INVARIANT_FAIL") not in got2:
        raise AssertionError(f"missing invariant_ok must not resolve, got {got2}")
    return "quarantined or unknown invariant state keeps halt events red"


# FS36-FS42 (28 Sep): each live card carries "summary", the same numbers as
# the daily summary text for that fleet's own instances (one data function):
# scalps / ejections / rolls with signed pips and USD, commission by account,
# net, per pair, deepest side, and the cycle. C72: account money comes from
# the instance that reports a balance, not the first live one.
# Predicted at the tests-only commit: FS36-FS42 all FAIL.
def _scalp_rec(inst, entry, exit_price, usd, direction="LONG", login=53066709,
               ejected=False, rolled=False, trade_date=None):
    import app as pipshed
    # the day the CARD shows (C81); falls back to the broker day before C81
    day = trade_date or getattr(pipshed, "_card_summary_day", pipshed._broker_today)()
    rec = {"instrument": inst.split("_")[1], "direction": direction,
           "entry_price": entry, "exit_price": exit_price, "gross_pnl": usd,
           "trade_date": day,
           "close_time": day + "T12:00:00+00:00",
           "ejected": ejected, "rolled": rolled}
    if login is not None:
        rec["account_login"] = login
    return rec


def _push(fake, inst, rec):
    fake._lists.setdefault(f"fxmatrix:scalp_history:{inst}", []).append(json.dumps(rec))


def _strip(fake):
    import app as pipshed
    pipshed.r = fake
    return pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json()


def _fixture_summary():
    fake = FakeRedis()
    _apply_fixture_fb2(fake)
    # B: 2 EURGBP scalps (+2.0 long, +1.0 short), 1 EURGBP ejection -28.8 pips
    _push(fake, "GRIND_EURGBP_OPTB", _scalp_rec("GRIND_EURGBP_OPTB", 0.85000, 0.85020, 0.27))
    _push(fake, "GRIND_EURGBP_OPTB", _scalp_rec("GRIND_EURGBP_OPTB", 0.85110, 0.85100, 0.13, "SHORT"))
    _push(fake, "GRIND_EURGBP_OPTB", _scalp_rec("GRIND_EURGBP_OPTB", 0.86092, 0.85804, -3.85, ejected=True))
    # B: 1 GBPUSD scalp +10.0 pips
    _push(fake, "GRIND_GBPUSD_OPTB", _scalp_rec("GRIND_GBPUSD_OPTB", 1.32000, 1.32100, 1.00))
    # A (FTMO): 1 EURGBP scalp +5.0 pips; must not appear on B's card
    _push(fake, "GRIND_EURGBP_OPT", _scalp_rec("GRIND_EURGBP_OPT", 0.85000, 0.85050, 0.67, login=1514731800))
    return fake


def check_fs36():
    b = _fleet_by_letter(_strip(_fixture_summary()), "B")
    sm = b.get("summary") or {}
    sc, ej, rl = sm.get("scalps") or {}, sm.get("ejections") or {}, sm.get("rolls") or {}
    got = ((sc.get("count"), sc.get("pips"), sc.get("usd")),
           (ej.get("count"), ej.get("pips"), ej.get("usd")),
           (rl.get("count"), rl.get("pips"), rl.get("usd")))
    # scalps 3: +2.0 +1.0 +10.0 = +13.0 pips, 0.27 + 0.13 + 1.00 = 1.40
    want = ((3, 13.0, 1.40), (1, -28.8, -3.85), (0, 0.0, 0.0))
    if got != want:
        raise AssertionError(f"expected {want}, got {got}")
    # 4 closes x 0.08 = -0.32; net pips 13.0 - 28.8 = -15.8; USD 1.40 - 3.85 - 0.32 = -2.77
    if (sm.get("closes"), sm.get("commission"), sm.get("net_pips"), sm.get("net_usd")) != (4, -0.32, -15.8, -2.77):
        raise AssertionError(f"closes/commission/net: {sm}")
    return "fleet B summary lines, commission and net"


def check_fs37():
    data = _strip(_fixture_summary())
    a = (_fleet_by_letter(data, "A").get("summary") or {})
    # A: 1 FTMO scalp +5.0 pips, 0.67 USD; 1 close x 0.06
    if ((a.get("scalps") or {}).get("count"), a.get("commission"), a.get("net_usd")) != (1, -0.06, 0.61):
        raise AssertionError(f"fleet A summary {a}")
    c = (_fleet_by_letter(data, "C").get("summary") or {})
    if (c.get("scalps") or {}).get("count") != 0 or c.get("closes") != 0:
        raise AssertionError(f"fleet C must be empty, got {c}")
    return "fleets counted apart; FTMO 0.06 per close"


def check_fs38():
    fake = FakeRedis()
    _apply_fixture_fb2(fake)
    _push(fake, "GRIND_GBPUSD_OPTB", _scalp_rec("GRIND_GBPUSD_OPTB", 1.32000, 1.32100, 1.00, login=None))
    sm = _fleet_by_letter(_strip(fake), "B").get("summary") or {}
    if (sm.get("commission"), sm.get("net_usd"), sm.get("commission_unknown")) != (None, None, 1):
        raise AssertionError(f"unknown account must give commission/net None, got {sm}")
    return "unknown account: commission and net are null, never zero"


def check_fs39():
    sm = _fleet_by_letter(_strip(_fixture_summary()), "B").get("summary") or {}
    pairs = [(p.get("pair"), p.get("scalps"), p.get("ejections"), p.get("pips"), p.get("usd"))
             for p in sm.get("by_pair") or []]
    # sorted by USD descending: GBPUSD +1.00 first; EURGBP 2 scalps 1 ejection,
    # +3.0 - 28.8 = -25.8 pips, 0.40 - 3.85 = -3.45
    want = [("GBPUSD", 1, 0, 10.0, 1.0), ("EURGBP", 2, 1, -25.8, -3.45)]
    if pairs != want:
        raise AssertionError(f"expected {want}, got {pairs}")
    ds = sm.get("deepest_side")
    # fixture fb2: NZDCHF_OPTB open_layers_short 7 is the deepest single side
    if ds != {"layers": 7, "pair": "NZDCHF", "side": "S"}:
        raise AssertionError(f"deepest_side {ds}")
    return "per-pair lines and deepest side"


def check_fs40():
    fake = FakeRedis()
    for i, inst in enumerate(GRIND_B_INSTANCES):
        if i == 0:
            continue
        if i == 3:
            fake.set(f"fxmatrix:state:{inst}", HBB(30, account_balance=10166.58, account_equity=10098.19))
        else:
            # every other instance: login but no balance (only the MAE reporter sends it)
            fake.set(f"fxmatrix:state:{inst}", HBB(30, account_balance=None, account_equity=None))
    fake.set(DAILY_TABLE_KEY, json.dumps({"generated_at": now.isoformat(), "rows": _daily_rows_fb()}))
    acct = _fleet_by_letter(_strip(fake), "B").get("account") or {}
    if (acct.get("balance"), acct.get("equity")) != (10166.58, 10098.19):
        raise AssertionError(f"C72: balance/equity must come from the reporter, got {acct}")
    return "C72: account money from the instance that reports it"


def check_fs41():
    import app as pipshed

    html = pipshed.app.test_client().get("/").get_data(as_text=True)
    need = ["card.summary", "fleet-sum-line", "fleet-sum-pairs", "deepest side "]
    missing = [n for n in need if n not in html]
    if missing:
        raise AssertionError(f"card template lacks {missing}")
    if "', ledger)</div>'" in html:
        raise AssertionError("the old ledger 'Today' block must no longer be drawn")
    return "cards draw the summary block"


def check_fs42():
    import app as pipshed

    fake = _fixture_summary()
    data = _strip(fake)
    a = _fleet_by_letter(data, "A").get("summary") or {}
    old = pipshed.GRIND_INSTANCES
    try:
        pipshed.GRIND_INSTANCES = list(GRIND_B_INSTANCES)   # the text summary of Fleet B's host
        # the same day as the card (C81: they differ from 21:00Z to 22:00Z)
        text = pipshed._build_daily_summary_text(
            selected_date=getattr(pipshed, "_card_summary_day", pipshed._broker_today)())
    finally:
        pipshed.GRIND_INSTANCES = old
    b = _fleet_by_letter(data, "B").get("summary") or {}
    net_line = [ln for ln in text.splitlines() if ln.startswith("Net ")][0]
    card_pips, card_usd = b.get("net_pips"), b.get("net_usd")
    if card_pips is None or card_usd is None:
        raise AssertionError(f"card has no net: {b}")
    if f"{card_pips:+.1f} pips" not in net_line or f"{card_usd:+.2f} USD" not in net_line:
        raise AssertionError(f"text summary and card disagree: {net_line!r} vs card {card_pips}, {card_usd}")
    return "card and text summary agree for the same fleet"


# FS43-FS44 (2 Oct 2026, fxmatrix geometry-cycle3 A7): cycle 3 runs the
# seven-pair ring. Retired: GRIND_AUDNZD_ALT, GRIND_NZDCAD_ALT (15:14Z),
# GRIND_AUDCAD_OPT, GRIND_NZDCHF_OPT (~15:40Z). Predicted at the tests-only
# commit: FS4 and FS43 FAIL (the strip still lists eleven); FS44 is a guard
# (a kept instance's event still shows) and passes in both states.
A_RING = [
    "GRIND_GBPUSD_OPT",
    "GRIND_EURUSD_OPT",
    "GRIND_EURGBP_OPT",
    "GRIND_AUDCHF_OPT",
    "GRIND_CADCHF_OPT",
    "GRIND_NZDCAD_OPT",
    "GRIND_AUDNZD_OPT",
]
A_RETIRED = {"GRIND_AUDNZD_ALT", "GRIND_NZDCAD_ALT", "GRIND_AUDCAD_OPT", "GRIND_NZDCHF_OPT"}


def _fleet_a_ring_live(fake, crit_rows):
    for inst in A_RING:
        fake.set(f"fxmatrix:state:{inst}", HBB(30, account_login=1514731800, invariant_ok=True))
    fake.set(DAILY_TABLE_KEY, json.dumps({"generated_at": now.isoformat(), "rows": _daily_rows_fb()}))
    fake.set(CRITICAL_KEY, json.dumps({"generated_at": now.isoformat(), "rows": crit_rows}))


def check_fs43():
    import app as pipshed

    if list(pipshed.GRIND_A_STRIP_INSTANCES) != A_RING:
        raise AssertionError(f"A strip must be the ring {A_RING}, got {pipshed.GRIND_A_STRIP_INSTANCES}")
    fake = FakeRedis()
    _fleet_a_ring_live(fake, [
        {"instance_id": "GRIND_AUDCAD_OPT", "level": "CRITICAL", "code": "INVARIANT_FAIL",
         "count": 2, "first_at": "2026-10-01T17:55:00Z", "last_at": "2026-10-01T17:55:30Z"},
    ])
    pipshed.r = fake
    a = _fleet_by_letter(pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "A")
    health = a.get("health") or {}
    if a.get("badge") != "LIVE" or health.get("instances_live") != 7 or health.get("instances_total") != 7:
        raise AssertionError(f"A with the seven reporting: LIVE 7/7, got {a.get('badge')}, {health}")
    named = {al.get("instance_id") for al in a.get("alerts") or []}
    if named & A_RETIRED:
        raise AssertionError(f"retired instances must not be alerted on A: {sorted(named & A_RETIRED)}")
    return "A = the seven-pair ring, LIVE 7/7, no alerts for retired instances"


def check_fs44():
    import app as pipshed

    fake = FakeRedis()
    _fleet_a_ring_live(fake, [
        {"instance_id": "GRIND_AUDNZD_OPT", "level": "CRITICAL", "code": "STARTUP_EXIT_SHORTFALL",
         "count": 1, "first_at": "2026-10-01T15:51:00Z", "last_at": "2026-10-01T15:51:00Z"},
    ])
    pipshed.r = fake
    a = _fleet_by_letter(pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json(), "A")
    hits = [al for al in a.get("alerts") or []
            if al.get("instance_id") == "GRIND_AUDNZD_OPT" and al.get("code") == "STARTUP_EXIT_SHORTFALL"]
    if not hits:
        raise AssertionError(f"a kept ring instance's event must still show on A: {a.get('alerts')}")
    return "events of kept instances still show on A"


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
    ("FS31", check_fs31),
    ("FS32", check_fs32),
    ("FS33", check_fs33),
    ("FS34", check_fs34),
    ("FS35", check_fs35),
    ("FS36", check_fs36),
    ("FS37", check_fs37),
    ("FS38", check_fs38),
    ("FS39", check_fs39),
    ("FS40", check_fs40),
    ("FS41", check_fs41),
    ("FS42", check_fs42),
    ("FS43", check_fs43),
    ("FS44", check_fs44),
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
