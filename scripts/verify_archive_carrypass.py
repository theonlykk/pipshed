"""Verification for archive_counts --carrypass on a real, SCRATCH PostgreSQL.

Needs VERIFY_DATABASE_URL pointing at an empty scratch database (never the
production archive): the script applies migrations/001 if ea_events is
missing, deletes every ea_events row, inserts fixtures and reads them back
through archive_counts.main(["--carrypass", ...]).
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
        with open(os.path.join(ROOT, "migrations", "001_archive_phase1.sql")) as f:
            cur.execute(f.read())
    cur.execute("DELETE FROM ea_events")
    seq = 0
    rows = [
        # instance, minutes ago, level, code, reason, detail
        ("GRIND_GBPUSD_OPT", 60, "INFO", "CARRY_SNAPSHOT", "GBPUSD",
         {"symbol": "GBPUSD", "day_of_week": 5, "mult_today": 1, "mult_tomorrow": 0,
          "rollover3days": 3, "eligible_long": 4, "eligible_short": 1,
          "accrued_swap_long": -1.25, "accrued_swap_short": -0.4}),
        ("GRIND_GBPUSD_OPT", 50, "INFO", "CARRY_PASS_SUMMARY", "GBPUSD",
         {"eligible": 5, "shifted": 4, "clamped": 1, "skipped": 0, "failed": 0,
          "incomplete": False}),
        ("GRIND_EURUSD_OPTB", 45, "INFO", "CARRY_PASS_INCOMPLETE", "EURUSD",
         {"eligible": 16, "shifted": 14, "clamped": 0, "skipped": 0, "failed": 0,
          "incomplete": True}),
        ("GRIND_AUDNZD_OPT", 40, "WARN", "QUARANTINE_ENTER", "I3_SHORT_NAKED", None),
        ("GRIND_AUDNZD_OPT", 30, "WARN", "QUARANTINE_ENTER", "I3_SHORT_NAKED", None),
        ("GRIND_NZDCAD_OPT", 20, "CRITICAL", "INVARIANT_FAIL", "I6_LONG_EXIT",
         {"ticket": 123}),
        ("GRIND_NZDCAD_OPT", 20, "INFO", "QUARANTINE_RELEASE", "I3_SHORT_NAKED", None),
        # outside a 30 h window
        ("GRIND_GBPUSD_OPT", 60 * 40, "INFO", "CARRY_PASS_SUMMARY", "GBPUSD",
         {"eligible": 9, "shifted": 9, "clamped": 0, "skipped": 0, "failed": 0,
          "incomplete": False}),
    ]
    for inst, mins, level, code, reason, detail in rows:
        seq += 1
        cur.execute(
            "INSERT INTO ea_events (instance_id, magic, session_id, seq, ea_time_ms,"
            " received_at, level, code, reason, ticket, detail)"
            " VALUES (%s, 1, 's', %s, 0, %s, %s, %s, %s, 0, %s)",
            (inst, seq, NOW - timedelta(minutes=mins), level, code, reason,
             None if detail is None else json.dumps(detail)),
        )


def run(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = archive_counts.main(argv)
    return rc, buf.getvalue()


def section(out, title_start):
    parts = out.split("== ")
    for p in parts:
        if p.startswith(title_start):
            return p
    raise AssertionError("section not found: " + title_start)


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

    rc, out = run(["--carrypass"])
    snap = section(out, "CARRY_SNAPSHOT")
    summ = section(out, "CARRY_PASS_SUMMARY")
    faults = section(out, "QUARANTINE")
    checks.append(("rc 0", rc == 0))
    checks.append(("snapshot row with dow 5, mult_tomorrow 0, x3 3",
                   "GRIND_GBPUSD_OPT | GBPUSD | 5 | 1 | 0 | 3 | 4 | 1 | -1.25 | -0.4" in snap))
    checks.append(("summary row", "GRIND_GBPUSD_OPT | CARRY_PASS_SUMMARY | GBPUSD | 5 | 4 | 1 | 0 | 0 | false" in summ))
    checks.append(("incomplete row", "GRIND_EURUSD_OPTB | CARRY_PASS_INCOMPLETE | EURUSD | 16 | 14 | 0 | 0 | 0 | true" in summ))
    checks.append(("40 h old summary excluded", " | 9 | 9 | " not in summ))
    checks.append(("summary has exactly 2 data rows", len(summ.strip().splitlines()) == 4))
    fault_lines = faults.strip().splitlines()
    checks.append(("I6 sorts first and is flagged",
                   fault_lines[2].startswith("GRIND_NZDCAD_OPT | INVARIANT_FAIL | I6_LONG_EXIT | 1 |")
                   and fault_lines[2].endswith("| True")))
    checks.append(("quarantine grouped to n=2",
                   any(l.startswith("GRIND_AUDNZD_OPT | QUARANTINE_ENTER | I3_SHORT_NAKED | 2 |")
                       and l.endswith("| False") for l in fault_lines)))
    checks.append(("release (INFO) not listed", "QUARANTINE_RELEASE" not in faults))

    rc, out = run(["--carrypass", "--hours", "50"])
    checks.append(("--hours 50 includes the 40 h row", " | 9 | 9 | " in section(out, "CARRY_PASS_SUMMARY")))

    rc, out = run(["--carrypass", "--instance", "GRIND_EURUSD_OPTB"])
    checks.append(("--instance filters snapshots", "no CARRY_SNAPSHOT rows." in section(out, "CARRY_SNAPSHOT")))
    checks.append(("--instance keeps its own summary",
                   "CARRY_PASS_INCOMPLETE" in section(out, "CARRY_PASS_SUMMARY")
                   and "GRIND_GBPUSD_OPT" not in section(out, "CARRY_PASS_SUMMARY")))
    checks.append(("--instance faults empty", "none." in section(out, "QUARANTINE")))

    failed = 0
    for name, ok in checks:
        print(("PASS " if ok else "FAIL ") + name)
        failed += 0 if ok else 1
    print(f"{len(checks) - failed}/{len(checks)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
