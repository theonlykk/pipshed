"""Verification: C137, the "Scalps per roll" table (fxmatrix backlog C137;
docs/research/scalps-per-roll.md s1, s4, s6; grid-as-variance-trade.md s4).

Per pair SIDE, over three windows, a side earns e * S - (D - e) * R pips
(D = N * a), so it makes money only while S / R exceeds the break-even

    k* = (N*a - e + c) / (e - c)       (c = cost per close, pips)

which is N*a/e - 1 before costs. The table shows S, R, S/R, k*, the k*
the side actually paid (mean roll loss + c over mean scalp gain - c),
S/R - k* (green above 0, red below, grey under 3 rolls) and the realised
pips, for three windows: today (the FTMO day, 22:00Z), the last five
weekday FTMO days (today included), and the cycle (the current regime:
IC since the gate build 7 Oct 02:25Z, A since 1514878887 started 7 Oct
22:08Z).

Definitions (previous chat's answers, 7 Oct ~23:00Z; operator "all seem
fine" ~23:04Z):
- S = scalp_history rows with rolled false and ejected false.
- R = roll CLOSES (rolled true). On cycle 3 (1514731800) an ejection was
  its roll, so ejected true counts as R there; on any other account an
  ejection is E (shown, not in S or R).
- ROLL_ACCEPTED (rolls started) is shown beside R, never used for S/R.
- c = the account's commission per close (USD) over the pair's measured
  pip value per close (sum |gross_pnl| / sum |pips| of the window's closes).
- k* uses the LIVE geometry from the heartbeat (cap, add and exit per side).

Where it is built: the web app has no Postgres connection, so the archive
worker counts S, R, E, rolls started and pips per instance, side and
window every 60 s and publishes them to Redis (`fxmatrix:sr:table`); the
strip joins them with each instance's live geometry.

Also in this patch: A is the IC strategy on FTMO 1514878887 since 7 Oct
22:08Z (its card still said "Cycle 3", no lattice, no commission rate for
the new account), and the fleets endpoint gains a Server-Timing header
(10-20 s per call measured 7 Oct ~23:10Z on pipshed.com AND linux.: CPU,
not Redis; the header names the part before any fix).

Tests first. Predicted at the tests-only commit: ST1-ST13 FAIL (the module,
the worker build, the strip key, the page, the export, A's config, the
timing header and the C136 label do not exist); ST14 is a guard that
passes in both states.

    python scripts/verify_c137_sr_table.py   (ST6, ST7 need VERIFY_DATABASE_URL)
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "verify_fleet_strip_helpers_c137", os.path.join(ROOT, "scripts", "verify_fleet_strip.py"))
fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fs)

TOKEN = fs.TOKEN
URL = os.environ.get("VERIFY_DATABASE_URL")
UTC = timezone.utc
NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)   # Thursday; FTMO day 2026-10-08
B_ACC, C_ACC, A_OLD, A_NEW = 53066709, 53071896, 1514731800, 1514878887


def T(text):
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


# ------------------------------------------------------------------ fixture
# (key, instance, account, direction, entry, exit, gross, close UTC, rolled, ejected)
# GBPUSD pip 0.0001; 0.01 lot = $0.10 a pip on B and A.
ROWS = [
    ("b1", "GRIND_GBPUSD_OPTB", B_ACC, "LONG", 1.3400, 1.3410, 1.00, "2026-10-08 01:00:00", False, False),
    ("b2", "GRIND_GBPUSD_OPTB", B_ACC, "LONG", 1.3400, 1.3410, 1.00, "2026-10-08 02:00:00", False, False),
    ("b3", "GRIND_GBPUSD_OPTB", B_ACC, "LONG", 1.3400, 1.3410, 1.00, "2026-10-08 03:00:00", False, False),
    ("b4", "GRIND_GBPUSD_OPTB", B_ACC, "LONG", 1.3400, 1.3410, 1.00, "2026-10-08 04:00:00", False, False),
    ("b5", "GRIND_GBPUSD_OPTB", B_ACC, "LONG", 1.3400, 1.3338, -6.20, "2026-10-08 05:00:00", True, False),
    ("b6", "GRIND_GBPUSD_OPTB", B_ACC, "LONG", 1.3400, 1.3338, -6.20, "2026-10-08 06:00:00", True, False),
    ("b7", "GRIND_GBPUSD_OPTB", B_ACC, "LONG", 1.3400, 1.3410, 1.00, "2026-10-07 10:00:00", False, False),
    ("b8", "GRIND_GBPUSD_OPTB", B_ACC, "LONG", 1.3400, 1.3338, -6.20, "2026-10-06 10:00:00", True, False),
    ("b9", "GRIND_GBPUSD_OPTB", B_ACC, "LONG", 1.3400, 1.3410, 1.00, "2026-10-01 21:00:00", False, False),
    ("b10", "GRIND_GBPUSD_OPTB", B_ACC, "SHORT", 1.3410, 1.3400, 1.00, "2026-10-08 07:00:00", False, False),
    ("b11", "GRIND_GBPUSD_OPTB", B_ACC, "SHORT", 1.3300, 1.3362, -6.20, "2026-10-07 23:30:00", True, False),
    ("a1", "GRIND_GBPUSD_OPT", A_OLD, "LONG", 1.3400, 1.3350, -5.00, "2026-10-06 12:00:00", False, True),
    ("a2", "GRIND_GBPUSD_OPT", A_OLD, "LONG", 1.3400, 1.3410, 1.00, "2026-10-07 12:00:00", False, False),
    ("a3", "GRIND_GBPUSD_OPT", A_NEW, "LONG", 1.3400, 1.3410, 1.00, "2026-10-07 23:00:00", False, False),
    ("a4", "GRIND_GBPUSD_OPT", A_NEW, "LONG", 1.3400, 1.3380, -2.00, "2026-10-08 01:00:00", False, True),
    ("a5", "GRIND_GBPUSD_OPT", A_NEW, "LONG", 1.3400, 1.3338, -6.20, "2026-10-08 02:00:00", True, False),
]
# rows whose broker offset is missing: dated by received_at (C: EURUSD short scalp)
ROWS_NO_OFFSET = [
    ("c1", "GRIND_EURUSD_OPTC", C_ACC, "SHORT", 1.1600, 1.1590, 1.00, "2026-10-08 03:00:00", False, False),
]
# ROLL_ACCEPTED (rolls started): instance, side, received UTC
ROLL_EVENTS = [
    ("GRIND_GBPUSD_OPTB", "L", "2026-10-08 05:30:00"),
    ("GRIND_GBPUSD_OPTB", "L", "2026-10-07 03:00:00"),
    ("GRIND_GBPUSD_OPTB", "S", "2026-10-07 23:00:00"),
    ("GRIND_GBPUSD_OPTB", "L", "2026-10-07 01:00:00"),   # before the IC regime: d5 only
]


def pure_rows():
    out = []
    for key, inst, acc, d, ep, xp, g, t, rolled, ejected in ROWS + ROWS_NO_OFFSET:
        out.append({"instance_id": inst, "account_login": acc, "direction": d,
                    "entry_price": ep, "exit_price": xp, "gross_pnl": g,
                    "close_utc": T(t), "rolled": rolled, "ejected": ejected})
    return out


def pure_rolls():
    return [(i, s, T(t)) for i, s, t in ROLL_EVENTS]


def stats(S, R, E, started, sp, rp, ep):
    return {"S": S, "R": R, "E": E, "rolls_started": started,
            "scalp_pips": sp, "roll_pips": rp, "eject_pips": ep}


# hand-derived from the fixture (see the comments in check_st4)
WANT = {
    "GRIND_GBPUSD_OPTB": {
        "L": {"today": stats(4, 2, 0, 1, 40.0, -124.0, 0.0),
              "d5": stats(5, 3, 0, 3, 50.0, -186.0, 0.0),
              "cycle": stats(5, 2, 0, 2, 50.0, -124.0, 0.0)},
        "S": {"today": stats(1, 1, 0, 1, 10.0, -62.0, 0.0),
              "d5": stats(1, 1, 0, 1, 10.0, -62.0, 0.0),
              "cycle": stats(1, 1, 0, 1, 10.0, -62.0, 0.0)},
    },
    "GRIND_GBPUSD_OPT": {
        "L": {"today": stats(1, 1, 1, 0, 10.0, -62.0, -20.0),
              "d5": stats(2, 2, 1, 0, 20.0, -112.0, -20.0),
              "cycle": stats(1, 1, 1, 0, 10.0, -62.0, -20.0)},
    },
    "GRIND_EURUSD_OPTC": {
        "S": {"today": stats(1, 0, 0, 0, 10.0, 0.0, 0.0),
              "d5": stats(1, 0, 0, 0, 10.0, 0.0, 0.0),
              "cycle": stats(1, 0, 0, 0, 10.0, 0.0, 0.0)},
    },
}


def _close(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a - b) <= tol


# --------------------------------------------------------------- pure rules

def check_st1():
    import sr_table as st
    # GBPUSD at the round-2 anchor: cap 8, add 9, exit 10, c 0.8 (scalps-per-roll s4)
    got = st.k_star(8, 9.0, 10.0, 0.8)
    want = (72 - 10 + 0.8) / (10 - 0.8)                       # 62.8 / 9.2 = 6.8261
    if not _close(got, want):
        raise AssertionError(f"GBPUSD k* with costs: expected {want:.4f}, got {got}")
    if not _close(st.k_star(8, 9.0, 10.0), 6.2):              # 72/10 - 1
        raise AssertionError(f"GBPUSD k* before costs: expected 6.2, got {st.k_star(8, 9.0, 10.0)}")
    if not _close(st.k_star(8, 4.0, 10.0, 0.6), 22.6 / 9.4):  # AUDCHF 2.40
        raise AssertionError(f"AUDCHF k*: expected {22.6 / 9.4:.4f}, got {st.k_star(8, 4.0, 10.0, 0.6)}")
    bad = [(8, 9.0, 10.0, 10.0), (8, 9.0, 0.0, 0.0), (None, 9.0, 10.0, 0.8),
           (8, None, 10.0, 0.8), (8, 9.0, None, 0.8), (0, 9.0, 10.0, 0.8)]
    for args in bad:
        if st.k_star(*args) is not None:
            raise AssertionError(f"k_star{args}: expected None (exit <= cost or a missing dial)")
    return "k* = (N*a - e + c)/(e - c): GBPUSD 6.83 (6.2 before costs), AUDCHF 2.40; None when e <= c or a dial is missing"


def check_st2():
    import sr_table as st
    cases = [
        ((False, False, B_ACC), "scalp"),
        ((True, False, B_ACC), "roll"),
        ((True, True, B_ACC), "roll"),
        ((False, True, A_OLD), "roll"),     # cycle 3: an ejection was its roll
        ((False, True, A_NEW), "eject"),
        ((False, True, B_ACC), "eject"),
        ((None, None, B_ACC), "scalp"),
        ((False, True, None), "eject"),
    ]
    for args, want in cases:
        got = st.close_kind(*args)
        if got != want:
            raise AssertionError(f"close_kind{args}: expected {want}, got {got}")
    return "rolled -> R; ejected -> R on 1514731800 only, else E; otherwise a scalp"


def check_st3():
    import sr_table as st
    cases = [
        # now, today start, today end, d5 start
        (NOW, "2026-10-07 22:00:00", "2026-10-08 22:00:00", "2026-10-01 22:00:00"),   # Thu: Thu..Fri 2
        (T("2026-10-12 10:00:00"), "2026-10-11 22:00:00", "2026-10-12 22:00:00", "2026-10-05 22:00:00"),
        (T("2026-10-10 12:00:00"), "2026-10-09 22:00:00", "2026-10-10 22:00:00", "2026-10-04 22:00:00"),
        (T("2026-10-07 22:30:00"), "2026-10-07 22:00:00", "2026-10-08 22:00:00", "2026-10-01 22:00:00"),
    ]
    for now, t0, t1, d0 in cases:
        w = st.windows_for(now)
        if w["today"] != (T(t0), T(t1)) or w["d5"] != (T(d0), T(t1)):
            raise AssertionError(f"at {now}: expected today {t0}-{t1}, d5 from {d0}; got {w}")
    starts = st.REGIME_START_BY_ACCOUNT
    want = {53066709: T("2026-10-07 02:25:00"), 53071896: T("2026-10-07 02:25:00"),
            53077984: T("2026-10-07 02:25:00"), 1514878887: T("2026-10-07 22:08:00")}
    if starts != want:
        raise AssertionError(f"regime starts: expected {want}, got {starts}")
    return ("today = the FTMO day (22:00Z in summer); d5 = the last five weekday FTMO days "
            "(Thu: from Fri 2; Mon 12: from Tue 6; Sat 10: from Mon 5); cycle starts per account")


def check_st4():
    """B GBPUSD long: today b1-b4 (S 4, +40) and b5, b6 (R 2, -124); d5 adds b7 (7 Oct)
    and b8 (6 Oct roll); b9 (1 Oct 21:00Z = FTMO day 1 Oct) is outside; the cycle
    (from 7 Oct 02:25Z) keeps b7, drops b8. Rolls started L: 8 Oct 05:30 (today),
    7 Oct 03:00 (d5, cycle), 7 Oct 01:00 (d5 only). B short: b10 scalp, b11 roll at
    7 Oct 23:30Z (today's FTMO day). A long: a1 (cycle 3 ejection = R, d5 only), a2
    (cycle 3 scalp, d5 only), a3 scalp, a4 ejection on 1514878887 = E (-20), a5 roll.
    C EURUSD short c1 has no broker offset: dated by received_at (8 Oct 03:00Z)."""
    import sr_table as st
    got = st.aggregate(pure_rows(), pure_rolls(), NOW)
    insts = got.get("instances") or {}
    errors = []
    for inst, sides in WANT.items():
        for side, wins in sides.items():
            for win, want in wins.items():
                cell = ((insts.get(inst) or {}).get("sides") or {}).get(side, {}).get(win)
                if cell != want:
                    errors.append(f"{inst} {side} {win}: expected {want}, got {cell}")
    b = insts.get("GRIND_GBPUSD_OPTB") or {}
    if b.get("pair") != "GBPUSD" or b.get("account_login") != B_ACC:
        errors.append(f"B pair/account: {b.get('pair')}, {b.get('account_login')}")
    # pip value per close: sum |usd| / sum |pips| of the window's closes: 23.6 / 236 = 0.1
    pv = (b.get("pip_value") or {}).get("today")
    if not _close(pv, 0.1):
        errors.append(f"B pip value today: expected 0.1, got {pv}")
    a = insts.get("GRIND_GBPUSD_OPT") or {}
    if a.get("account_login") != A_NEW:
        errors.append(f"A account (newest row): expected {A_NEW}, got {a.get('account_login')}")
    if "S" in (a.get("sides") or {}):
        errors.append("A has no short rows: no S side expected")
    if errors:
        raise AssertionError("; ".join(errors))
    return "S, R, E, rolls started and pips per instance, side and window match the hand count"


def check_st5():
    import sr_table as st
    # B GBPUSD long, d5: S 5, R 3; rate 0.08, pip value 0.10 -> c 0.8; cap 8, add 9, exit 10
    row = st.side_row(WANT["GRIND_GBPUSD_OPTB"]["L"]["d5"], 8, 9.0, 10.0, 0.08, 0.10)
    want = {"S": 5, "R": 3, "E": 0, "rolls_started": 3,
            "sr": 1.67, "k_star": 6.83, "k_star_gross": 6.2,
            "k_actual": 6.83,            # mean roll loss 62 + 0.8 over mean scalp 10 - 0.8
            "edge": -5.16,               # 5/3 - 62.8/9.2 = -5.1594
            "realised_pips": -136.0, "c_pips": 0.8, "grey": False}
    if row != want:
        raise AssertionError(f"B long d5: expected {want}, got {row}")
    today = st.side_row(WANT["GRIND_GBPUSD_OPTB"]["L"]["today"], 8, 9.0, 10.0, 0.08, 0.10)
    if today.get("sr") != 2.0 or today.get("edge") != -4.83 or today.get("grey") is not True:
        raise AssertionError(f"B long today (R 2 < 3): expected sr 2.0, edge -4.83, grey; got {today}")
    none_r = st.side_row(WANT["GRIND_EURUSD_OPTC"]["S"]["today"], 8, 7.0, 10.0, 0.08, 0.10)
    if none_r.get("sr") is not None or none_r.get("edge") is not None or none_r.get("grey") is not True \
            or none_r.get("k_actual") is not None:
        raise AssertionError(f"no roll: S/R, edge and k actual None, grey; got {none_r}")
    no_cost = st.side_row(WANT["GRIND_GBPUSD_OPTB"]["L"]["d5"], 8, 9.0, 10.0, None, 0.10)
    if no_cost.get("k_star") is not None or no_cost.get("edge") is not None \
            or no_cost.get("k_star_gross") != 6.2 or no_cost.get("c_pips") is not None:
        raise AssertionError(f"unknown commission: k* and edge None, k* before costs 6.2; got {no_cost}")
    return "B GBPUSD long 5 days: S/R 1.67 against k* 6.83 (edge -5.16), realised -136 pips; under 3 rolls grey"


# ------------------------------------------------------- the worker, real PG

def _pg():
    import psycopg2
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.scalp_history')")
        if cur.fetchone()[0] is None:
            for name in ("001_archive_phase1.sql", "002_adr159_daily.sql",
                         "003_adr160_gated.sql", "004_c56_rolls.sql"):
                with open(os.path.join(ROOT, "migrations", name)) as f:
                    cur.execute(f.read())
        cur.execute("DELETE FROM scalp_history")
        cur.execute("DELETE FROM ea_events")
    return conn


def _load_pg(conn):
    with conn.cursor() as cur:
        for key, inst, acc, d, ep, xp, g, t, rolled, ejected in ROWS:
            utc = T(t)
            cur.execute(
                "INSERT INTO scalp_history (instance_id, instrument, direction, entry_price,"
                " exit_price, gross_pnl, close_time_broker, source, received_at, ejected,"
                " broker_utc_offset_s, account_login, rolled)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, 'ea', %s, %s, 10800, %s, %s)",
                (inst, inst.split("_")[1], d, ep, xp, g,
                 (utc + timedelta(hours=3)).replace(tzinfo=None), utc + timedelta(seconds=2),
                 ejected, acc, rolled))
        for key, inst, acc, d, ep, xp, g, t, rolled, ejected in ROWS_NO_OFFSET:
            utc = T(t)
            cur.execute(
                "INSERT INTO scalp_history (instance_id, instrument, direction, entry_price,"
                " exit_price, gross_pnl, close_time_broker, source, received_at, ejected,"
                " broker_utc_offset_s, account_login, rolled)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, 'ea', %s, %s, NULL, %s, %s)",
                (inst, inst.split("_")[1], d, ep, xp, g,
                 datetime(2026, 1, 1), utc, ejected, acc, rolled))
        for seq, (inst, side, t) in enumerate(ROLL_EVENTS, 1):
            cur.execute(
                "INSERT INTO ea_events (instance_id, magic, session_id, seq, ea_time_ms,"
                " received_at, level, code, reason, ticket, detail)"
                " VALUES (%s, 1, 's', %s, 0, %s, 'INFO', 'ROLL_ACCEPTED', '', 0, %s)",
                (inst, seq, T(t), json.dumps({"side": side, "reroll": False})))
        # noise: other codes, a ROLL_ACCEPTED with no side
        cur.execute(
            "INSERT INTO ea_events (instance_id, magic, session_id, seq, ea_time_ms,"
            " received_at, level, code, reason, ticket, detail)"
            " VALUES ('GRIND_GBPUSD_OPTB', 1, 's', 99, 0, %s, 'INFO', 'ROLL_FILLED', '', 0, %s),"
            " ('GRIND_GBPUSD_OPTB', 1, 's', 98, 0, %s, 'INFO', 'ROLL_ACCEPTED', '', 0, %s)",
            (T("2026-10-08 06:00:00"), json.dumps({"side": "L"}),
             T("2026-10-08 06:00:00"), json.dumps({"reroll": True})))


def check_st6():
    if not URL:
        raise AssertionError("VERIFY_DATABASE_URL is not set (scratch database only)")
    import archive_worker as aw
    conn = _pg()
    _load_pg(conn)
    payload = aw.build_sr_table(conn, now=NOW)
    conn.close()
    insts = payload.get("instances") or {}
    errors = []
    for inst, sides in WANT.items():
        for side, wins in sides.items():
            for win, want in wins.items():
                cell = ((insts.get(inst) or {}).get("sides") or {}).get(side, {}).get(win)
                if cell != want:
                    errors.append(f"{inst} {side} {win}: expected {want}, got {cell}")
    if not payload.get("built_at"):
        errors.append("no built_at")
    if errors:
        raise AssertionError("; ".join(errors))
    return "on PostgreSQL: broker close minus offset dates each close; ROLL_FILLED and side-less rows ignored"


class _KV:
    def __init__(self):
        self.kv = {}

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value, ex=None):
        self.kv[key] = value


def check_st7():
    if not URL:
        raise AssertionError("VERIFY_DATABASE_URL is not set (scratch database only)")
    import archive_worker as aw
    import sr_table as st
    conn = _pg()
    _load_pg(conn)
    rc = _KV()
    first = aw.try_sr_build(conn, rc, force=False)
    second = aw.try_sr_build(conn, rc, force=False)
    forced = aw.try_sr_build(conn, rc, force=True)
    conn.close()
    if first is None or second is not None or forced is None:
        raise AssertionError(f"build, then nothing within 60 s, then a forced build: got "
                             f"{first is not None}, {second is not None}, {forced is not None}")
    raw = rc.get(st.SR_TABLE_KEY)
    data = json.loads(raw) if raw else {}
    if "instances" not in data or st.SR_TABLE_KEY != "fxmatrix:sr:table":
        raise AssertionError(f"published under {st.SR_TABLE_KEY!r}: {list(data)}")
    src = open(os.path.join(ROOT, "archive_worker.py")).read()
    loop = src[src.index("def worker_loop"):]
    if loop.count("try_sr_build(") < 2:
        raise AssertionError("worker_loop must run try_sr_build at start (forced) and in the loop")
    return "the worker publishes fxmatrix:sr:table every 60 s (forced at start)"


# ------------------------------------------------------------ the strip

def _hb(inst, account, cap, add_l, add_s, exit_l, exit_s, **extra):
    payload = {
        "_received_at": fs.now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "instance_id": inst, "net_mtm": 0.0, "open_layers_long": 1, "open_layers_short": 1,
        "halted": False, "account_login": account, "account_balance": 10000.0,
        "account_equity": 10000.0, "max_layers": cap, "width_pips": 1.0,
        "add_pips": add_l, "exit_pips": exit_l,
        "add_pips_long": add_l, "add_pips_short": add_s,
        "exit_pips_long": exit_l, "exit_pips_short": exit_s,
    }
    payload.update(extra)
    return json.dumps(payload)


def _strip_fixture(built_at=None):
    import sr_table as st
    fake = fs.FakeRedis()
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPTB", _hb("GRIND_GBPUSD_OPTB", B_ACC, 8, 9.0, 9.0, 10.0, 10.0))
    fake.set("fxmatrix:state:GRIND_GBPUSD_OPT", _hb("GRIND_GBPUSD_OPT", A_NEW, 8, 9.0, 9.0, 10.0, 10.0))
    fake.set("fxmatrix:state:GRIND_EURUSD_OPTC", _hb("GRIND_EURUSD_OPTC", C_ACC, 8, 7.0, 6.0, 10.0, 10.0))
    payload = st.aggregate(pure_rows(), pure_rolls(), NOW)
    payload["built_at"] = (built_at or fs.now).strftime("%Y-%m-%dT%H:%M:%SZ")
    fake.set(st.SR_TABLE_KEY, json.dumps(payload))
    return fake


def _find(rows, inst, side):
    for r in rows:
        if r.get("instance_id") == inst and r.get("side") == side:
            return r
    return None


def check_st8():
    import app as pipshed
    pipshed.r = _strip_fixture()
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets/1").get_json() or {}
    sr = data.get("scalps_per_roll")
    if not sr or sr.get("available") is not True or sr.get("fleets") != ["A", "B", "C", "D"]:
        raise AssertionError(f"strip scalps_per_roll: {str(sr)[:300]}")
    b = _find(sr["rows"]["B"], "GRIND_GBPUSD_OPTB", "L")
    want_geo = {"cap": 8, "add": 9.0, "exit": 10.0}
    if not b or b.get("pair") != "GBPUSD" or b.get("geometry") != want_geo:
        raise AssertionError(f"B GBPUSD L row: {b}")
    if b["d5"] != {"S": 5, "R": 3, "E": 0, "rolls_started": 3, "sr": 1.67, "k_star": 6.83,
                   "k_star_gross": 6.2, "k_actual": 6.83, "edge": -5.16,
                   "realised_pips": -136.0, "c_pips": 0.8, "grey": False}:
        raise AssertionError(f"B GBPUSD L d5: {b['d5']}")
    # C EURUSD short: add 6 on the short side (per-side key), rate 0.08, pip value 0.1:
    # k* = (48 - 10 + 0.8) / 9.2 = 4.2174
    c = _find(sr["rows"]["C"], "GRIND_EURUSD_OPTC", "S")
    if not c or c.get("geometry") != {"cap": 8, "add": 6.0, "exit": 10.0} or c["today"].get("k_star") != 4.22:
        raise AssertionError(f"C EURUSD short uses its own add (6): {c}")
    # A: 1514878887 at 0.06 a close: c = 0.6, k* = (72 - 10 + 0.6) / 9.4 = 6.6596
    a = _find(sr["rows"]["A"], "GRIND_GBPUSD_OPT", "L")
    if not a or a["today"].get("k_star") != 6.66 or a["today"].get("E") != 1:
        raise AssertionError(f"A GBPUSD long on the new account: {a}")
    # every strip instance has both sides, zero rows where nothing closed
    nzd = _find(sr["rows"]["D"], "GRIND_NZDCAD_OPTD", "S")
    if not nzd or nzd["today"].get("S") != 0 or nzd["today"].get("grey") is not True \
            or nzd.get("geometry") is not None:
        raise AssertionError(f"silent D NZDCAD short: zero, grey, no geometry; got {nzd}")
    if sr.get("windows", {}).get("today", {}).get("label") != "FTMO day 2026-10-08":
        raise AssertionError(f"window label: {sr.get('windows')}")
    pipshed.r = _strip_fixture(built_at=fs.now - timedelta(seconds=400))
    stale = (pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets/2").get_json() or {}).get("scalps_per_roll")
    if not stale or stale.get("available") is not False:
        raise AssertionError(f"a table built 400 s ago is not shown: {str(stale)[:200]}")
    return "the strip joins the worker's counts with live per-side geometry; stale (> 300 s) = unavailable"


def check_st9():
    page = open(os.path.join(ROOT, "templates", "dashboard.html")).read()
    needed = ['<div id="fleetSR"', "function renderFleetSR(", "renderFleetSR(data && data.scalps_per_roll)",
              "renderFleetSR(null)", ".sr-pos", ".sr-neg", ".sr-grey", "function srEdgeClass("]
    missing = [n for n in needed if n not in page]
    if missing:
        raise AssertionError(f"page lacks {missing}")
    node = shutil.which("node")
    if not node:
        raise AssertionError("node is not installed")
    start = page.index("function srEdgeClass(")
    end = page.index("\n  }\n", start) + 4
    js = page[start:end] + """
console.log(JSON.stringify([
  srEdgeClass({edge: 0.4, grey: false}), srEdgeClass({edge: -0.1, grey: false}),
  srEdgeClass({edge: 2.0, grey: true}), srEdgeClass({edge: null, grey: true}),
  srEdgeClass({edge: 0, grey: false})]));"""
    out = subprocess.run([node, "-e", js], capture_output=True, text=True)
    got = json.loads(out.stdout or "null")
    want = ["sr-pos", "sr-neg", "sr-grey", "sr-grey", "sr-neg"]
    if got != want:
        raise AssertionError(f"srEdgeClass: expected {want}, got {got} {out.stderr[-200:]}")
    return "the table sits under the geometry table; green above 0, red at or below, grey under 3 rolls"


def check_st10():
    import app as pipshed
    pipshed.r = _strip_fixture()
    client = pipshed.app.test_client()
    j = client.get(f"/api/g/{TOKEN}/sr/x").get_json() or {}
    if j.get("available") is not True or "B" not in (j.get("rows") or {}):
        raise AssertionError(f"JSON export: {str(j)[:200]}")
    res = client.get(f"/api/g/{TOKEN}/sr/x?format=csv&fleet=B&window=d5")
    text = res.get_data(as_text=True)
    lines = [ln for ln in text.splitlines() if ln]
    header = ("fleet,pair,instance_id,side,window,S,R,E,rolls_started,sr,k_star,k_star_gross,"
              "k_actual,edge,realised_pips,c_pips,grey,cap,add,exit")
    if not res.mimetype == "text/csv" or lines[0] != header:
        raise AssertionError(f"CSV header: {res.mimetype} {lines[:1]}")
    want = "B,GBPUSD,GRIND_GBPUSD_OPTB,L,d5,5,3,0,3,1.67,6.83,6.2,6.83,-5.16,-136.0,0.8,false,8,9.0,10.0"
    if want not in lines or any(not ln.startswith("B,") for ln in lines[1:]) \
            or any(",d5," not in ln for ln in lines[1:]) or len(lines) != 1 + 18:
        raise AssertionError(f"CSV rows for B, d5 (9 pairs x 2 sides): {lines[:4]} ... {len(lines)}")
    one = client.get(f"/api/g/{TOKEN}/sr/x?format=csv&instance=GRIND_GBPUSD_OPT").get_data(as_text=True)
    if len([ln for ln in one.splitlines() if ln]) != 1 + 2 * 3:
        raise AssertionError(f"instance filter: 2 sides x 3 windows; got {one.splitlines()[:3]}")
    if client.get("/api/g/wrong/sr/x").status_code != 404:
        raise AssertionError("a wrong token must 404")
    return "/api/g/<token>/sr exports JSON or CSV, filtered by fleet, instance and window"


def check_st11():
    import app as pipshed
    import sr_table as st
    a = next(e for e in pipshed.FLEET_STRIP if e["letter"] == "A")
    want = {"name": "FTMO-IC 1514878887", "lattice": True, "cycle_start": "2026-10-08"}
    got = {k: a.get(k) for k in want}
    if got != want:
        raise AssertionError(f"A: expected {want}, got {got}")
    rates = pipshed.COMMISSION_PER_CLOSE_BY_ACCOUNT
    if rates is not st.COMMISSION_PER_CLOSE_BY_ACCOUNT or rates.get(1514878887) != 0.06 \
            or rates.get(1514731800) != 0.06 or rates.get(53066709) != 0.08:
        raise AssertionError(f"one commission table (app re-exports sr_table's) with 1514878887 at 0.06: {rates}")
    return "A = FTMO-IC 1514878887: lattice on, cycle from 8 Oct, commission 0.06 a close"


def check_st12():
    page = open(os.path.join(ROOT, "templates", "dashboard.html")).read()
    if "summary.scalps + ' closes since init'" not in page or "'Closes since init <strong>'" not in page:
        raise AssertionError("C136: the arm cards must say 'closes since init' for the heartbeat count")
    if "summary.scalps + ' scalps'" in page or "('Scalps <strong>'" in page:
        raise AssertionError("C136: the old 'scalps' label is still there")
    return "C136: the heartbeat's layer-removal count reads 'closes since init'"


def check_st13():
    import app as pipshed
    pipshed.r = _strip_fixture()
    res = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets/3")
    hdr = res.headers.get("Server-Timing") or ""
    parts = {}
    for item in hdr.split(","):
        bits = [b.strip() for b in item.split(";")]
        if len(bits) == 2 and bits[1].startswith("dur="):
            try:
                parts[bits[0]] = float(bits[1][4:])
            except ValueError:
                pass
    want = {"states", "daily", "critical", "ejection", "cards", "summary", "tables", "sr", "total"}
    if set(parts) != want or any(v < 0 for v in parts.values()):
        raise AssertionError(f"Server-Timing names {sorted(want)}; got {hdr!r}")
    return "the fleets response carries Server-Timing by part (ms)"


def check_st14():
    scripts = ["verify_fleet_strip.py", "verify_c113_fleet_books.py", "verify_c114_quote_gap.py",
               "verify_c129_geometry.py", "verify_c123_side_add.py", "verify_c90_d_commission.py"]
    bad = []
    for s in scripts:
        res = subprocess.run([sys.executable, "-B", os.path.join(ROOT, "scripts", s)],
                             capture_output=True, text=True, cwd=ROOT)
        if res.returncode != 0:
            bad.append(s)
    if bad:
        raise AssertionError(f"failing: {bad}")
    return "the strip, books, quote gap, geometry, per-side add and D commission suites still pass"


CHECKS = [("ST1", check_st1), ("ST2", check_st2), ("ST3", check_st3), ("ST4", check_st4),
          ("ST5", check_st5), ("ST6", check_st6), ("ST7", check_st7), ("ST8", check_st8),
          ("ST9", check_st9), ("ST10", check_st10), ("ST11", check_st11), ("ST12", check_st12),
          ("ST13", check_st13), ("ST14", check_st14)]


def main():
    passed = failed = 0
    for name, fn in CHECKS:
        try:
            print(f"{name} OK: {fn()}")
            passed += 1
        except Exception as exc:
            print(f"{name} FAIL: {type(exc).__name__}: {exc}")
            failed += 1
    print(f"verify_c137_sr_table {passed}/{passed + failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
