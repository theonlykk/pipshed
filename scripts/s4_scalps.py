"""Read-only s4 CloseBy scalp counts vs scalp_history (ADR-159)."""
import argparse
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ftmo_daily

OUT_BY_SQL = """
SELECT instance_id, order_ticket, position_id, ea_time_ms
FROM fill_logs
WHERE entry_type = 'OUT_BY'
  AND ea_time_ms >= %s AND ea_time_ms < %s
"""

# EJECT_FILLED and ROLL_FILLED tickets exclude CloseBy pairs from s4 scalp counts.
EJECT_SQL = """
SELECT ticket
FROM ea_events
WHERE code IN ('EJECT_FILLED', 'ROLL_FILLED')
  AND ea_time_ms >= %s AND ea_time_ms < %s
"""

SCALP_HISTORY_SQL = """
SELECT instance_id, close_time_broker, broker_utc_offset_s, account_login
FROM scalp_history
WHERE ejected IS NOT TRUE
  AND rolled IS NOT TRUE
  AND received_at >= %s AND received_at < %s
"""

GATED_SQL = (
    "SELECT account_login, ftmo_day, gated_seconds FROM "
    "daily_snapshots WHERE ftmo_day >= %s AND ftmo_day <= %s"
)


def gated_by_day(conn, days):
    if not days:
        return {}
    with conn.cursor() as cur:
        cur.execute(GATED_SQL, (min(days), max(days)))
        rows = cur.fetchall()
    out = {}
    for account_login, ftmo_day, gated_seconds in rows:
        if isinstance(ftmo_day, datetime):
            ftmo_day = ftmo_day.date()
        out.setdefault(ftmo_day, {})[account_login] = gated_seconds
    return out


def format_gated_line(accounts):
    if not accounts:
        return "  gated_hours: no snapshot"
    parts = []
    for login in sorted(accounts, key=lambda x: int(x)):
        seconds = accounts[login]
        if seconds is None:
            hours = "--"
        else:
            hours = f"{seconds / 3600:.1f}"
        parts.append(f"{login}={hours}")
    return "  gated_hours: " + " ".join(parts)


def connect_readonly():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is required.", file=sys.stderr)
        sys.exit(1)
    conn = psycopg2.connect(url)
    conn.set_session(readonly=True, autocommit=True)
    return conn


def ftmo_days_window(n_days):
    now = datetime.now(timezone.utc)
    today = ftmo_daily.ftmo_day_of_utc(now)
    days = []
    for i in range(1, n_days + 1):
        days.append(today - timedelta(days=i))
    days.sort()
    return days


def window_ms_for_days(days):
    if not days:
        return None, None
    start, _ = ftmo_daily.ftmo_day_bounds_utc(days[0])
    _, end = ftmo_daily.ftmo_day_bounds_utc(days[-1])
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def scalp_history_counts(conn, days):
    by_day_instance = {}
    no_offset = {}
    for day in days:
        start, end = ftmo_daily.ftmo_day_bounds_utc(day)
        recv_start = start - timedelta(days=1)
        recv_end = end + timedelta(days=1)
        with conn.cursor() as cur:
            cur.execute(SCALP_HISTORY_SQL, (recv_start, recv_end))
            rows = cur.fetchall()
        for instance_id, close_time_broker, offset_s, _account in rows:
            if offset_s is None:
                key = (day, instance_id)
                no_offset[key] = no_offset.get(key, 0) + 1
                continue
            utc_close = ftmo_daily._scalp_utc_close(close_time_broker, offset_s)
            if utc_close is None:
                continue
            if not (start <= utc_close < end):
                continue
            key = (day, instance_id)
            by_day_instance[key] = by_day_instance.get(key, 0) + 1
    return by_day_instance, no_offset


def run_main(days_count):
    days = ftmo_days_window(days_count)
    start_ms, end_ms = window_ms_for_days(days)
    conn = connect_readonly()
    try:
        with conn.cursor() as cur:
            cur.execute(OUT_BY_SQL, (start_ms, end_ms))
            fill_rows = cur.fetchall()
            cur.execute(EJECT_SQL, (start_ms, end_ms))
            eject_tickets = {row[0] for row in cur.fetchall() if row[0] is not None}
    finally:
        conn.close()

    conn2 = connect_readonly()
    try:
        hist_counts, no_offset = scalp_history_counts(conn2, days)
    finally:
        conn2.close()

    conn3 = connect_readonly()
    try:
        gated = gated_by_day(conn3, days)
    finally:
        conn3.close()

    for day in sorted(days, reverse=True):
        print(f"FTMO day {day.isoformat()}")
        print(format_gated_line(gated.get(day, {})))
        day_counts = ftmo_daily.s4_counts(fill_rows, eject_tickets, day)
        opt_vals = sorted(
            v for (inst, d), v in day_counts.items()
            if d == day and inst.endswith("_OPT")
        )
        median = None
        if opt_vals:
            median = opt_vals[len(opt_vals) // 2]

        for instance_id in sorted({inst for (inst, d) in day_counts if d == day}):
            n = day_counts.get((instance_id, day), 0)
            line = f"  {instance_id}: s4={n}"
            if instance_id.endswith("_OPT") and median is not None and median > 0:
                line += f"  ratio={n / median:.3f}"
            hist = hist_counts.get((day, instance_id), 0)
            line += f"  scalp_history={hist}"
            if n != hist:
                line += "  MISMATCH"
            print(line)

        for (d, instance_id), cnt in sorted(no_offset.items()):
            if d == day and cnt:
                print(f"  {instance_id}: scalp_history no_offset={cnt}")
        print()


def run_probe():
    days = []
    now = datetime.now(timezone.utc)
    today = ftmo_daily.ftmo_day_of_utc(now)
    for i in range(14):
        days.append(today - timedelta(days=i))
    start_ms, end_ms = window_ms_for_days(sorted(days))
    conn = connect_readonly()
    try:
        with conn.cursor() as cur:
            cur.execute(OUT_BY_SQL, (start_ms, end_ms))
            rows = cur.fetchall()
    finally:
        conn.close()

    by_day = {}
    for instance_id, order_ticket, position_id, ea_time_ms in rows:
        day = ftmo_daily.ftmo_day_of_utc(
            datetime.fromtimestamp(ea_time_ms / 1000.0, tz=timezone.utc)
        )
        by_day.setdefault(day, []).append((order_ticket, instance_id))

    print("OUT_BY probe (last 14 FTMO days)")
    for day in sorted(by_day.keys(), reverse=True):
        tickets = by_day[day]
        per_ticket = Counter(t[0] for t in tickets)
        dist = Counter(per_ticket.values())
        print(
            f"  {day.isoformat()}: rows={len(tickets)} "
            f"tickets_1={dist.get(1, 0)} tickets_2={dist.get(2, 0)} "
            f"tickets_more={sum(v for k, v in dist.items() if k > 2)}"
        )

    conn = connect_readonly()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT role FROM fill_logs
                WHERE entry_type = 'OUT_BY'
                  AND ea_time_ms >= %s AND ea_time_ms < %s
                """,
                (start_ms, end_ms),
            )
            roles = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    print("OUT_BY distinct role values:", roles)


def main():
    parser = argparse.ArgumentParser(description="s4 CloseBy scalp counter (read-only)")
    parser.add_argument("--days", type=int, default=7, help="complete FTMO days (default 7)")
    parser.add_argument("--probe", action="store_true", help="G6 distribution probe")
    args = parser.parse_args()
    if args.probe:
        run_probe()
    else:
        run_main(args.days)


if __name__ == "__main__":
    main()
