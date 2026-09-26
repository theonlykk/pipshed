"""Verification for archive_counts --codes and --depth on a real, SCRATCH PostgreSQL.

Needs VERIFY_DATABASE_URL pointing at an empty scratch database (never the
production archive): applies migrations 001 and 002 if needed, deletes every
ea_events and scalp_history row, inserts fixtures, reads them back through
archive_counts.main([...]).
"""
import contextlib
import io
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
        for name in (
            "001_archive_phase1.sql",
            "002_adr159_daily.sql",
            "003_adr160_gated.sql",
            "004_c56_rolls.sql",
        ):
            with open(os.path.join(ROOT, "migrations", name), encoding="ascii") as f:
                cur.execute(f.read())
    cur.execute("DELETE FROM ea_events")
    cur.execute("DELETE FROM scalp_history")
    seq = 0
    events = [
        ("GRIND_GBPUSD_OPT", 60, "EJECT_ACCEPTED"),
        ("GRIND_GBPUSD_OPT", 50, "EJECT_ACCEPTED"),
        ("GRIND_GBPUSD_OPT", 40, "EJECT_FILLED"),
        ("GRIND_EURUSD_OPTB", 30, "EJECT_REFUSED"),
        ("GRIND_EURUSD_OPTB", 20, "QUARANTINE_ENTER"),
        ("GRIND_GBPUSD_OPT", 60 * 200, "EJECT_ACCEPTED"),  # outside 168 h
    ]
    for inst, mins, code in events:
        seq += 1
        cur.execute(
            "INSERT INTO ea_events (instance_id, magic, session_id, seq, ea_time_ms,"
            " received_at, level, code, reason, ticket, detail)"
            " VALUES (%s, 1, 's', %s, 0, %s, 'INFO', %s, '', 0, NULL)",
            (inst, seq, NOW - timedelta(minutes=mins), code),
        )
    scalps = [
        # instance, direction, stack_depth, minutes ago
        ("GRIND_GBPUSD_OPT", "LONG", 3, 100),
        ("GRIND_GBPUSD_OPT", "LONG", 8, 90),
        ("GRIND_GBPUSD_OPT", "LONG", 8, 80),
        ("GRIND_GBPUSD_OPT", "SHORT", 2, 70),
        ("GRIND_EURUSD_OPTB", "SHORT", 5, 60),
        ("GRIND_EURUSD_OPTB", "SHORT", 8, 60 * 200),  # outside 168 h
    ]
    for i, (inst, direction, depth, mins) in enumerate(scalps):
        cur.execute(
            "INSERT INTO scalp_history (instance_id, instrument, direction, entry_price,"
            " exit_price, gross_pnl, layer_depth, stack_depth, close_time_broker,"
            " source, received_at, rolled, ejected) VALUES (%s, 'X', %s, %s, %s, 0.1, 0, %s, %s,"
            " 'test', %s, NULL, NULL)",
            (inst, direction, 1.0 + i / 1000.0, 1.1 + i / 1000.0, depth,
             datetime(2026, 9, 25) + timedelta(minutes=i), NOW - timedelta(minutes=mins)),
        )
    cur.execute(
        "INSERT INTO scalp_history (instance_id, instrument, direction, entry_price,"
        " exit_price, gross_pnl, layer_depth, stack_depth, close_time_broker,"
        " source, received_at, rolled, ejected) VALUES"
        " ('GRIND_GBPUSD_OPT', 'X', 'LONG', 5.0, 5.1, 0.1, 0, 99, %s, 'test', %s, TRUE, NULL)",
        (datetime(2026, 9, 25), NOW - timedelta(minutes=30)),
    )
    cur.execute(
        "INSERT INTO scalp_history (instance_id, instrument, direction, entry_price,"
        " exit_price, gross_pnl, layer_depth, stack_depth, close_time_broker,"
        " source, received_at, rolled, ejected) VALUES"
        " ('GRIND_GBPUSD_OPT', 'X', 'SHORT', 6.0, 6.1, 0.1, 0, 99, %s, 'test', %s, NULL, TRUE)",
        (datetime(2026, 9, 25), NOW - timedelta(minutes=25)),
    )


def run(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = archive_counts.main(argv)
    return rc, buf.getvalue()


def main():
    if not URL:
        print("SKIP: VERIFY_DATABASE_URL is not set (scratch database only).")
        return 1
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        setup(cur)
    conn.close()
    os.environ["DATABASE_URL"] = URL
    checks = []

    rc, out = run(["--codes", "EJECT_ACCEPTED,EJECT_FILLED,EJECT_REFUSED", "--hours", "168"])
    checks.append(("codes rc 0", rc == 0))
    checks.append(("accepted grouped n=2 (200 h row excluded)",
                   any(l.startswith("GRIND_GBPUSD_OPT | EJECT_ACCEPTED | 2 |") for l in out.splitlines())))
    checks.append(("filled n=1", any(l.startswith("GRIND_GBPUSD_OPT | EJECT_FILLED | 1 |") for l in out.splitlines())))
    checks.append(("refused n=1", any(l.startswith("GRIND_EURUSD_OPTB | EJECT_REFUSED | 1 |") for l in out.splitlines())))
    checks.append(("other codes excluded", "QUARANTINE_ENTER" not in out))
    checks.append(("no depth section without --depth", "SCALP DEPTH" not in out))

    rc, out = run(["--depth", "--hours", "168"])
    lines = out.splitlines()
    checks.append(("depth long: 3 scalps, max 8, 2 at cap",
                   "GRIND_GBPUSD_OPT | LONG | 3 | 8 | 2" in lines))
    checks.append(("depth short: 1 scalp, max 2, 0 at cap",
                   "GRIND_GBPUSD_OPT | SHORT | 1 | 2 | 0" in lines))
    checks.append(("depth B short: 200 h row excluded",
                   "GRIND_EURUSD_OPTB | SHORT | 1 | 5 | 0" in lines))
    checks.append(("depth excludes rolled row (LONG still 3 not 4)",
                   "GRIND_GBPUSD_OPT | LONG | 3 | 8 | 2" in lines))
    checks.append(("depth excludes ejected row (SHORT still 1 not 2)",
                   "GRIND_GBPUSD_OPT | SHORT | 1 | 2 | 0" in lines))

    rc, out = run(["--depth", "--cap", "5", "--hours", "168", "--instance", "GRIND_EURUSD_OPTB"])
    lines = out.splitlines()
    checks.append(("--cap 5 and --instance", "GRIND_EURUSD_OPTB | SHORT | 1 | 5 | 1" in lines
                   and not any(l.startswith("GRIND_GBPUSD_OPT") for l in lines)))

    rc, out = run(["--codes", "EJECT_ACCEPTED", "--depth", "--hours", "1"])
    checks.append(("both sections in one call", "== EVENTS" in out and "== SCALP DEPTH" in out))
    checks.append(("1 h window: only the 50 min event", "GRIND_GBPUSD_OPT | EJECT_ACCEPTED | 1 |" in out))


    failed = 0
    for name, ok in checks:
        print(("PASS " if ok else "FAIL ") + name)
        failed += 0 if ok else 1
    print(f"{len(checks) - failed}/{len(checks)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
