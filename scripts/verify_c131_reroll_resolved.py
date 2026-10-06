"""Verification: C131, a ROLL_STRANDED alert greys once that side has
re-rolled since (fxmatrix backlog C131; ADR-165 s4.5).

With re-roll ON (fxmatrix ADR-165, live on B, C, D since 5 Oct) a side
fully rolled at cap is the normal state: it re-rolls at the next level. So
C94's rule (grey only when no side is fully rolled at cap) keeps a
ROLL_STRANDED amber long after the episode ended (5 Oct night: EURGBP OPTB
stranded at the compile's re-init with re-roll still off, then re-rolled 10
times). The EA clears its stranded latch on a successful re-roll and reports
it as ROLL_ACCEPTED (level INFO, detail "reroll": true, "side": "L" / "S";
grind_engine.mqh 985-1005, 1087, 1568-1572); ROLL_STRANDED is WARN with the
side in `reason` (grind_engine.mqh 1192).

Rule: the archive worker's critical build marks a ROLL_STRANDED row
"rerolled_after": true when, for EVERY side of that instance that raised
ROLL_STRANDED in the last 24 h, a re-roll on the SAME side was received
strictly after that side's last ROLL_STRANDED; otherwise false. The strip
and /critical show such a row resolved with the note
"resolved: re-rolled since". C94's rule still applies when it is false.

Tests first. Predicted at the tests-only commit: RR1, RR2, RR3, RR4, RR5
and RR8 FAIL; RR6 and RR7 are guards that pass in both states.
RR9 and RR10 were added with the fix for the two survivors of its
thirteen-mutation round (side check dropped; the 24 h window widened).

    python scripts/verify_c131_reroll_resolved.py   (RR8 needs VERIFY_DATABASE_URL)
"""
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "verify_fleet_strip_helpers_c131", os.path.join(ROOT, "scripts", "verify_fleet_strip.py"))
fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fs)

TOKEN = fs.TOKEN
INST = "GRIND_AUDCHF_OPTD"
NOTE = "resolved: re-rolled since"
T0 = datetime(2026, 10, 5, 23, 16, 40, tzinfo=timezone.utc)
URL = os.environ.get("VERIFY_DATABASE_URL")


def _t(sec):
    return T0 + timedelta(seconds=sec)


# --------------------------------------------------------------- pure rule

def check_rr1():
    import ftmo_daily as fd
    rows = [(INST, "L", "ROLL_STRANDED", _t(0)),
            (INST, "L", "ROLL_ACCEPTED", _t(5))]
    got = fd.stranded_rerolled(rows)
    if got != {INST}:
        raise AssertionError(f"one stranded side re-rolled after: expected {{{INST}}}, got {got}")
    return "a re-roll on the stranded side after it: rerolled"


def check_rr2():
    import ftmo_daily as fd
    cases = [
        ("re-roll before the stranded event", [(INST, "L", "ROLL_ACCEPTED", _t(0)),
                                               (INST, "L", "ROLL_STRANDED", _t(5))]),
        ("re-roll at the same instant", [(INST, "L", "ROLL_STRANDED", _t(0)),
                                         (INST, "L", "ROLL_ACCEPTED", _t(0))]),
        ("re-roll on the other side", [(INST, "L", "ROLL_STRANDED", _t(0)),
                                       (INST, "S", "ROLL_ACCEPTED", _t(5))]),
        ("re-roll on another instance", [(INST, "L", "ROLL_STRANDED", _t(0)),
                                         ("GRIND_CADCHF_OPTD", "L", "ROLL_ACCEPTED", _t(5))]),
        ("a second stranded after the re-roll", [(INST, "L", "ROLL_STRANDED", _t(0)),
                                                 (INST, "L", "ROLL_ACCEPTED", _t(5)),
                                                 (INST, "L", "ROLL_STRANDED", _t(9))]),
    ]
    for why, rows in cases:
        got = fd.stranded_rerolled(rows)
        if INST in got:
            raise AssertionError(f"{why}: must not count as re-rolled, got {got}")
    return "earlier, same instant, other side, other instance, stranded again: not rerolled"


def check_rr3():
    import ftmo_daily as fd
    both = [(INST, "L", "ROLL_STRANDED", _t(0)), (INST, "S", "ROLL_STRANDED", _t(1)),
            (INST, "L", "ROLL_ACCEPTED", _t(5))]
    if INST in fd.stranded_rerolled(both):
        raise AssertionError("both sides stranded, only L re-rolled: not rerolled")
    both.append((INST, "S", "ROLL_ACCEPTED", _t(6)))
    if fd.stranded_rerolled(both) != {INST}:
        raise AssertionError("both sides stranded and both re-rolled after: rerolled")
    junk = [("GRIND_X_OPTD", "WARN", "QUARANTINE_ENTER", _t(0)), (INST, None, "ROLL_ACCEPTED", _t(1))]
    if fd.stranded_rerolled(junk) != set():
        raise AssertionError("other codes and a re-roll with no stranded event: empty")
    return "every stranded side must re-roll; other rows ignored"


# ------------------------------------------------------------ worker build

class _Cur:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []

    def execute(self, sql, params=None):
        self.conn.sqls.append(sql)
        self.rows = self.conn.reroll_rows if "ROLL_ACCEPTED" in sql else self.conn.crit_rows

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self, crit_rows, reroll_rows):
        self.crit_rows, self.reroll_rows, self.sqls = crit_rows, reroll_rows, []

    def cursor(self):
        return _Cur(self)


def check_rr4():
    import archive_worker as aw
    crit = [(INST, "WARN", "ROLL_STRANDED", _t(0)),
            ("GRIND_CADCHF_OPTD", "WARN", "ROLL_STRANDED", _t(0)),
            ("GRIND_CADCHF_OPTD", "WARN", "QUARANTINE_ENTER", _t(2))]
    rer = [(INST, "L", "ROLL_STRANDED", _t(0)), (INST, "L", "ROLL_ACCEPTED", _t(5)),
           ("GRIND_CADCHF_OPTD", "S", "ROLL_STRANDED", _t(0))]
    conn = _Conn(crit, rer)
    payload = aw.build_critical_list(conn)
    if not any("ROLL_ACCEPTED" in s and "reroll" in s for s in conn.sqls):
        raise AssertionError(f"a query must read ROLL_ACCEPTED rows with the reroll flag: {conn.sqls}")
    rows = {(r["instance_id"], r["code"]): r for r in payload["rows"]}
    if rows[(INST, "ROLL_STRANDED")].get("rerolled_after") is not True:
        raise AssertionError(f"{INST} ROLL_STRANDED must be rerolled_after true: {rows}")
    if rows[("GRIND_CADCHF_OPTD", "ROLL_STRANDED")].get("rerolled_after") is not False:
        raise AssertionError(f"CADCHF ROLL_STRANDED (no re-roll) must be false: {rows}")
    if "rerolled_after" in rows[("GRIND_CADCHF_OPTD", "QUARANTINE_ENTER")]:
        raise AssertionError("other codes carry no rerolled_after key")
    return "the critical build marks ROLL_STRANDED rows rerolled_after"


# ----------------------------------------------------------- strip, /critical

def _longs_fully_rolled(n=8):
    out = []
    for k in range(n):
        entry = round(0.58100 - 0.0004 * k, 5)
        out.append({"layer_index": k, "side": "L", "entry_price": entry,
                    "exit_target": round(entry - 0.0022, 5),
                    "has_exit_order": k in (0, n - 1), "has_exit_position": False})
    return out


def _fixture(fake, rerolled):
    hb = fs.HBB(30, account_login=53077984, invariant_ok=True, max_layers=8,
                layers=_longs_fully_rolled(), open_layers_long=8, open_layers_short=0)
    for inst in fs.GRIND_D_INSTANCES:
        fake.set(f"fxmatrix:state:{inst}",
                 hb if inst == INST else fs.HBB(30, account_login=53077984, invariant_ok=True))
    fake.set(fs.DAILY_TABLE_KEY, json.dumps({"generated_at": fs.now.isoformat(), "rows": []}))
    row = {"instance_id": INST, "level": "WARN", "code": "ROLL_STRANDED", "count": 1,
           "first_at": "2026-10-05T23:16:40Z", "last_at": "2026-10-05T23:16:40Z"}
    if rerolled is not None:
        row["rerolled_after"] = rerolled
    fake.set(fs.CRITICAL_KEY, json.dumps({"generated_at": fs.now.isoformat(), "rows": [row]}))


def _strip_alert(fake):
    import app as pipshed
    pipshed.r = fake
    data = pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets/c131").get_json()
    d = fs._fleet_by_letter(data, "D")
    return {a.get("code"): a for a in d.get("alerts") or [] if a.get("kind") == "EVENT"}.get("ROLL_STRANDED")


def _critical_row(fake):
    import app as pipshed
    pipshed.r = fake
    rows = pipshed.app.test_client().get(f"/api/g/{TOKEN}/critical/c131").get_json().get("rows") or []
    return {(r.get("instance_id"), r.get("code")): r for r in rows}.get((INST, "ROLL_STRANDED")) or {}


def check_rr5():
    fake = fs.FakeRedis()
    _fixture(fake, True)       # the side is still fully rolled at cap: C94 alone keeps it amber
    a = _strip_alert(fake)
    if not a or a.get("level") != "resolved" or not str(a.get("detail", "")).endswith(NOTE):
        raise AssertionError(f"strip must show ROLL_STRANDED resolved with '{NOTE}', got {a}")
    row = _critical_row(fake)
    if row.get("resolved") is not True or row.get("resolved_note") != NOTE:
        raise AssertionError(f"/critical must mark it resolved with '{NOTE}', got {row}")
    return "rerolled_after true greys it although the side is fully rolled at cap"


def check_rr6():
    """GUARD: rerolled_after false or absent with a side fully rolled at cap: amber (C94)."""
    for flag in (False, None):
        fake = fs.FakeRedis()
        _fixture(fake, flag)
        a = _strip_alert(fake)
        if not a or a.get("level") != "amber":
            raise AssertionError(f"rerolled_after={flag}: strip must stay amber, got {a}")
        if _critical_row(fake).get("resolved") is True:
            raise AssertionError(f"rerolled_after={flag}: /critical must not resolve it")
    return "without a re-roll the C94 rule stands"


def check_rr7():
    """GUARD: C94 and the C80 critical build still pass."""
    for script in ("verify_c94_stranded_resolved.py", "verify_c80_c74_c81.py",
                   "verify_critical_resolved.py"):
        res = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", script)],
                             capture_output=True, text=True)
        if res.returncode != 0:
            raise AssertionError(f"{script} failed:\n{res.stdout[-800:]}{res.stderr[-400:]}")
    return "verify_c94, verify_c80_c74_c81 and verify_critical_resolved still pass"


# ------------------------------------------------------- the query, real PG

def check_rr8():
    if not URL:
        raise AssertionError("VERIFY_DATABASE_URL is not set (scratch database only)")
    import psycopg2
    import archive_worker as aw
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.ea_events')")
        if cur.fetchone()[0] is None:
            with open(os.path.join(ROOT, "migrations", "001_archive_phase1.sql")) as f:
                cur.execute(f.read())
        cur.execute("DELETE FROM ea_events")
        rows = [  # instance, minutes ago, level, code, reason, detail
            (INST, 30, "WARN", "ROLL_STRANDED", "L", {"level": 0.58}),
            (INST, 29, "INFO", "ROLL_ACCEPTED", "", {"side": "L", "reroll": True, "from_level": 0.581}),
            ("GRIND_CADCHF_OPTD", 30, "WARN", "ROLL_STRANDED", "S", {"level": 0.57}),
            ("GRIND_CADCHF_OPTD", 29, "INFO", "ROLL_ACCEPTED", "", {"side": "S", "reroll": False}),
            ("GRIND_NZDCHF_OPTD", 30, "WARN", "ROLL_STRANDED", "L", {"level": 0.5}),
            ("GRIND_NZDCHF_OPTD", 60 * 30, "INFO", "ROLL_ACCEPTED", "", {"side": "L", "reroll": True}),
        ]
        for seq, (inst, mins, level, code, reason, detail) in enumerate(rows, 1):
            cur.execute(
                "INSERT INTO ea_events (instance_id, magic, session_id, seq, ea_time_ms,"
                " received_at, level, code, reason, ticket, detail)"
                " VALUES (%s, 1, 's', %s, 0, %s, %s, %s, %s, 0, %s)",
                (inst, seq, now - timedelta(minutes=mins), level, code, reason, json.dumps(detail)))
    payload = aw.build_critical_list(conn)
    conn.close()
    got = {r["instance_id"]: r.get("rerolled_after") for r in payload["rows"]
           if r["code"] == "ROLL_STRANDED"}
    want = {INST: True, "GRIND_CADCHF_OPTD": False, "GRIND_NZDCHF_OPTD": False}
    if got != want:
        raise AssertionError(f"real query: expected {want}, got {got}")
    return "on PostgreSQL: reroll true counts; reroll false and a re-roll older than 24 h do not"


# --------------------------------------------- mutation-round survivors

def check_rr9():
    """Survivor (side check dropped): events with no side never count."""
    import ftmo_daily as fd
    rows = [(INST, None, "ROLL_STRANDED", _t(0)), (INST, None, "ROLL_ACCEPTED", _t(5)),
            ("GRIND_CADCHF_OPTD", "", "ROLL_STRANDED", _t(0)),
            ("GRIND_CADCHF_OPTD", "", "ROLL_ACCEPTED", _t(5))]
    got = fd.stranded_rerolled(rows)
    if got != set():
        raise AssertionError(f"no side, no verdict: expected an empty set, got {got}")
    return "a ROLL_STRANDED or re-roll without a side is ignored"


def check_rr10():
    """Survivor (window widened): a ROLL_STRANDED older than 24 h is not counted."""
    if not URL:
        raise AssertionError("VERIFY_DATABASE_URL is not set (scratch database only)")
    import psycopg2
    import archive_worker as aw
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    now = datetime.now(timezone.utc)
    inst = "GRIND_EURGBP_OPTD"
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.ea_events')")
        if cur.fetchone()[0] is None:
            with open(os.path.join(ROOT, "migrations", "001_archive_phase1.sql")) as f:
                cur.execute(f.read())
        cur.execute("DELETE FROM ea_events")
        rows = [  # minutes ago, level, code, reason, detail
            (60 * 30, "WARN", "ROLL_STRANDED", "L", {"level": 0.85}),     # outside 24 h
            (30, "WARN", "ROLL_STRANDED", "S", {"level": 0.86}),
            (20, "INFO", "ROLL_ACCEPTED", "", {"side": "S", "reroll": True}),
        ]
        for seq, (mins, level, code, reason, detail) in enumerate(rows, 1):
            cur.execute(
                "INSERT INTO ea_events (instance_id, magic, session_id, seq, ea_time_ms,"
                " received_at, level, code, reason, ticket, detail)"
                " VALUES (%s, 1, 's', %s, 0, %s, %s, %s, %s, 0, %s)",
                (inst, seq, now - timedelta(minutes=mins), level, code, reason, json.dumps(detail)))
    payload = aw.build_critical_list(conn)
    conn.close()
    got = [r.get("rerolled_after") for r in payload["rows"]
           if r["instance_id"] == inst and r["code"] == "ROLL_STRANDED"]
    if got != [True]:
        raise AssertionError(f"only the side stranded inside 24 h must re-roll: expected [True], got {got}")
    return "a long side stranded 30 h ago does not hold the alert amber"


CHECKS = [("RR1", check_rr1), ("RR2", check_rr2), ("RR3", check_rr3), ("RR4", check_rr4),
          ("RR5", check_rr5), ("RR6", check_rr6), ("RR7", check_rr7), ("RR8", check_rr8),
          ("RR9", check_rr9), ("RR10", check_rr10)]


def main():
    passed = failed = 0
    for name, fn in CHECKS:
        try:
            print(f"{name} OK: {fn()}")
            passed += 1
        except Exception as exc:
            print(f"{name} FAIL: {type(exc).__name__}: {exc}")
            failed += 1
    print(f"verify_c131_reroll_resolved {passed}/{passed + failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
