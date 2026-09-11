"""Read-only summary of the Postgres archive (ADR-130/131).

Run inside the archive-worker container, which already has DATABASE_URL:
    railway ssh --service archive-worker -i "$HOME\\.ssh\\id_ed25519" python scripts/archive_counts.py
Options:
    --limit N        latest rows to show per table (default 3, 0 = counts only)
    --table NAME     only this table
    --instance ID    only rows for this instance_id
    --carry          latest CARRY_SNAPSHOT row per symbol (skips table counts)
Never prints the connection string. Opens a read-only session.
"""
import argparse
import os
import sys

import psycopg2

TABLES = {
    "config_events": ["received_at", "instance_id", "event", "symbol", "ea_build", "deinit_reason"],
    "send_logs": ["received_at", "instance_id", "action", "order_type", "requested_price",
                  "ok", "retcode", "duration_ms", "broker_time"],
    "fill_logs": ["received_at", "instance_id", "deal_ticket", "entry_type", "deal_type",
                  "deal_price", "order_price_open", "slippage_pips", "halted_at_receipt"],
    "ea_events": ["received_at", "instance_id", "level", "code", "reason"],
    "scalp_history": ["received_at", "instance_id", "direction", "entry_price", "exit_price",
                      "gross_pnl", "close_time_broker", "source"],
}

CARRY_SQL = """
SELECT DISTINCT ON (detail->>'symbol')
       detail->>'symbol'            AS symbol,
       detail->>'swap_long'         AS swap_long_pts,
       detail->>'swap_short'        AS swap_short_pts,
       detail->>'long_pips'         AS long_pips,
       detail->>'short_pips'        AS short_pips,
       detail->>'multiplier'        AS mult,
       detail->>'rollover3days'     AS x3_day,
       detail->>'swap_mode'         AS swap_mode,
       detail->>'trade_mode_full'   AS tradeable,
       detail->>'eligible_long'     AS elig_long,
       detail->>'eligible_short'    AS elig_short,
       received_at
FROM ea_events
WHERE code = 'CARRY_SNAPSHOT'
ORDER BY detail->>'symbol', received_at DESC
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--table", choices=sorted(TABLES))
    parser.add_argument("--instance")
    parser.add_argument("--carry", action="store_true")
    args = parser.parse_args(argv)

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set.")
        return 1

    conn = psycopg2.connect(url)
    conn.set_session(readonly=True, autocommit=True)
    try:
        with conn.cursor() as cur:
            if args.carry:
                cur.execute(CARRY_SQL)
                rows = cur.fetchall()
                if not rows:
                    print("no CARRY_SNAPSHOT rows yet.")
                else:
                    cols = [desc[0] for desc in cur.description]
                    print(" | ".join(cols))
                    for row in rows:
                        print(" | ".join("" if v is None else str(v) for v in row))
                return 0

            tables = [args.table] if args.table else list(TABLES)
            for table in tables:
                where, params = "", ()
                if args.instance:
                    where, params = " WHERE instance_id = %s", (args.instance,)
                cur.execute(f"SELECT count(*), max(received_at) FROM {table}{where}", params)
                count, latest = cur.fetchone()
                print(f"{table}: {count} rows, latest received_at {latest}")
                if args.limit > 0 and count:
                    cols = TABLES[table]
                    cur.execute(
                        f"SELECT {', '.join(cols)} FROM {table}{where} "
                        f"ORDER BY received_at DESC, id DESC LIMIT %s",
                        params + (args.limit,),
                    )
                    for row in cur.fetchall():
                        print("   " + " | ".join(f"{c}={v}" for c, v in zip(cols, row)))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
