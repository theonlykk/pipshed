"""Verification for archive_counts --export-study on a real, SCRATCH PostgreSQL.

Needs VERIFY_DATABASE_URL pointing at an empty scratch database (never the
production archive): applies migrations 001-004 if needed, deletes the rows of
the exported tables, inserts fixtures, and reads the JSON lines back through
archive_counts.main([...]). Ejection value study (fxmatrix docs/research).
"""
import contextlib
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import archive_counts  # noqa: E402

URL = os.environ.get("VERIFY_DATABASE_URL")
NOW = datetime.now(timezone.utc)


def setup(cur):
    cur.execute("SELECT to_regclass('public.ea_events')")
    if cur.fetchone()[0] is None:
        for name in ("001_archive_phase1.sql", "002_adr159_daily.sql",
                     "003_adr160_gated.sql", "004_c56_rolls.sql"):
            with open(os.path.join(ROOT, "migrations", name), encoding="ascii") as f:
                cur.execute(f.read())
    for t in ("fill_logs", "ea_events", "config_events", "scalp_history"):
        cur.execute(f"DELETE FROM {t}")
    fills = [
        # instance, deal_ticket, role, hours ago
        ("GRIND_EURGBP_OPT", 101, "ENT", 5),
        ("GRIND_EURGBP_OPT", 102, "EXT", 4),
        ("GRIND_AUDCHF_OPTB", 201, "ENT", 3),
        ("GRIND_EURGBP_OPT", 103, "ENT", 24 * 10),  # outside --days 2
    ]
    for seq, (inst, ticket, role, hrs) in enumerate(fills, 1):
        cur.execute(
            "INSERT INTO fill_logs (instance_id, magic, session_id, seq, ea_time_ms, received_at,"
            " deal_ticket, order_ticket, position_id, entry_type, deal_type, side, layer_index,"
            " role, deal_price, order_price_open, volume, profit, swap, commission)"
            " VALUES (%s, 1, 's', %s, 0, %s, %s, 1, 1, 'IN', 'BUY', 'L', 7, %s, 0.86, 0.86,"
            " 0.01, 0, 0, -0.04)",
            (inst, seq, NOW - timedelta(hours=hrs), ticket, role))
    events = [
        ("GRIND_EURGBP_OPT", "EJECT_ACCEPTED", 5),
        ("GRIND_EURGBP_OPT", "EJECT_FILLED", 4),
        ("GRIND_AUDCHF_OPTB", "ROLL_ACCEPTED", 3),
        ("GRIND_AUDCHF_OPTB", "CARRY_SNAPSHOT", 3),
        ("GRIND_AUDCHF_OPTB", "QUARANTINE_ENTER", 3),   # not exported
        ("GRIND_EURGBP_OPT", "EJECT_FILLED", 24 * 10),  # outside --days 2
    ]
    for seq, (inst, code, hrs) in enumerate(events, 1):
        cur.execute(
            "INSERT INTO ea_events (instance_id, magic, session_id, seq, ea_time_ms, received_at,"
            " level, code, reason, ticket, detail) VALUES (%s, 1, 's', %s, 0, %s, 'INFO', %s,"
            " '', 0, %s)",
            (inst, seq, NOW - timedelta(hours=hrs), code, json.dumps({"side": "L"})))
    cur.execute(
        "INSERT INTO config_events (instance_id, magic, session_id, seq, ea_time_ms, received_at,"
        " event, max_layers, add_pips, exit_pips) VALUES ('GRIND_EURGBP_OPT', 1, 's', 1, 0, %s,"
        " 'INIT', 8, 4.0, 5.0)", (NOW - timedelta(days=30),))
    cur.execute(
        "INSERT INTO scalp_history (instance_id, instrument, direction, entry_price, exit_price,"
        " gross_pnl, layer_depth, stack_depth, close_time_broker, source, received_at)"
        " VALUES ('GRIND_EURGBP_OPT', 'EURGBP', 'LONG', 0.86, 0.8605, 0.6, 1, 2, %s, 'test', %s)",
        (datetime(2026, 9, 28, 10, 0), NOW - timedelta(hours=2)))


def run(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            code = archive_counts.main(argv)
        except SystemExit as exc:  # argparse on an unknown flag
            code = exc.code
    return code, buf.getvalue()


def parse(out):
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def check_ex1():
    code, out = run(["--export-study", "--days", "2"])
    if code != 0:
        raise AssertionError(f"exit code {code}")
    rows = parse(out)
    if rows[0].get("table") != "_meta" or rows[0].get("days") != 2:
        raise AssertionError(f"first line must be _meta with days=2, got {rows[0]}")
    return "meta line first, every line JSON"


def check_ex2():
    rows = parse(run(["--export-study", "--days", "2"])[1])
    tickets = sorted(r["deal_ticket"] for r in rows if r["table"] == "fill_logs")
    if tickets != [101, 102, 201]:
        raise AssertionError(f"fill_logs within 2 days expected [101, 102, 201], got {tickets}")
    return "fill_logs window"


def check_ex3():
    rows = parse(run(["--export-study", "--days", "2"])[1])
    codes = sorted(r["code"] for r in rows if r["table"] == "ea_events")
    if codes != ["CARRY_SNAPSHOT", "EJECT_ACCEPTED", "EJECT_FILLED", "ROLL_ACCEPTED"]:
        raise AssertionError(f"ea_events EJECT_/ROLL_/CARRY_ in window expected, got {codes}")
    det = [r["detail"] for r in rows if r["table"] == "ea_events"][0]
    if not isinstance(det, dict) or det.get("side") != "L":
        raise AssertionError(f"detail must be a JSON object, got {det!r}")
    return "ea_events codes and detail"


def check_ex4():
    rows = parse(run(["--export-study", "--days", "2"])[1])
    cfg = [r for r in rows if r["table"] == "config_events"]
    sh = [r for r in rows if r["table"] == "scalp_history"]
    if len(cfg) != 1 or cfg[0]["max_layers"] != 8:
        raise AssertionError(f"config_events of any age expected (1 row), got {cfg}")
    if len(sh) != 1 or sh[0]["stack_depth"] != 2:
        raise AssertionError(f"scalp_history in window expected (1 row), got {sh}")
    return "config_events (any age) and scalp_history"


def check_ex5():
    rows = parse(run(["--export-study", "--days", "2", "--instance", "GRIND_AUDCHF_OPTB"])[1])
    insts = sorted({r["instance_id"] for r in rows if r["table"] != "_meta"})
    if insts != ["GRIND_AUDCHF_OPTB"]:
        raise AssertionError(f"--instance filter expected only AUDCHF_OPTB, got {insts}")
    return "--instance filter"


def check_ex6():
    # C83 (30 Sep): --export-archive copies EVERY row of the four trade-history
    # tables (all codes, no day window) for an offline copy.
    code, out = run(["--export-archive"])
    if code != 0:
        raise AssertionError(f"exit code {code}")
    rows = parse(out)
    if rows[0].get("table") != "_meta" or rows[0].get("archive") is not True:
        raise AssertionError(f"first line must be _meta with archive=true, got {rows[0]}")
    tickets = sorted(r["deal_ticket"] for r in rows if r["table"] == "fill_logs")
    codes = sorted(r["code"] for r in rows if r["table"] == "ea_events")
    n_cfg = sum(1 for r in rows if r["table"] == "config_events")
    n_sc = sum(1 for r in rows if r["table"] == "scalp_history")
    want_codes = sorted(["EJECT_ACCEPTED", "EJECT_FILLED", "ROLL_ACCEPTED", "CARRY_SNAPSHOT",
                         "QUARANTINE_ENTER", "EJECT_FILLED"])
    if tickets != [101, 102, 103, 201] or codes != want_codes or (n_cfg, n_sc) != (1, 1):
        raise AssertionError(f"all rows expected, got fills {tickets}, codes {codes}, "
                             f"config {n_cfg}, scalps {n_sc}")
    if any(r["table"] == "send_logs" for r in rows):
        raise AssertionError("send_logs are not trade history")
    return "archive export: every row of the four tables, all codes"


CHECKS = [("EX1", check_ex1), ("EX2", check_ex2), ("EX3", check_ex3),
          ("EX4", check_ex4), ("EX5", check_ex5), ("EX6", check_ex6)]


def main():
    if not URL:
        print("SKIP: VERIFY_DATABASE_URL is not set (scratch database only).")
        return 0
    os.environ["DATABASE_URL"] = URL
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        setup(cur)
    conn.close()
    passed = failed = 0
    for name, fn in CHECKS:
        try:
            print(f"{name} OK: {fn()}")
            passed += 1
        except Exception as exc:
            print(f"{name} FAIL: {exc}")
            failed += 1
    print(f"SUMMARY passed={passed} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
