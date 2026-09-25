"""Read-only summary of the Postgres archive (ADR-130/131).

Run inside the archive-worker container, which already has DATABASE_URL:
    railway ssh --service archive-worker -i "$HOME\\.ssh\\id_ed25519" python scripts/archive_counts.py
Options:
    --limit N        latest rows to show per table (default 3, 0 = counts only)
    --table NAME     only this table
    --instance ID    only rows for this instance_id
    --carry          latest CARRY_SNAPSHOT row per symbol (skips table counts)
    --rollovers      rollover crossings per closed layer from fill_logs (skips table counts)
    --slippage       slippage distribution and I6-breach fills from fill_logs (skips table counts)
    --l0churn        layer-0 ENT modify churn from send_logs (skips table counts)
    --carrypass      nightly carry check (skips table counts): CARRY_SNAPSHOT rows,
                     CARRY_PASS_SUMMARY / _INCOMPLETE rows with their counts, and
                     quarantine / invariant / critical markers grouped by reason,
                     over the last --hours (default 30); honours --instance
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

CARRYPASS_SNAPSHOT_SQL = """
SELECT received_at,
       instance_id,
       detail->>'symbol'             AS symbol,
       detail->>'day_of_week'        AS dow,
       detail->>'mult_today'         AS mult_today,
       detail->>'mult_tomorrow'      AS mult_tomorrow,
       detail->>'rollover3days'      AS x3_day,
       detail->>'eligible_long'      AS elig_long,
       detail->>'eligible_short'     AS elig_short,
       detail->>'accrued_swap_long'  AS swap_usd_long,
       detail->>'accrued_swap_short' AS swap_usd_short
FROM ea_events
WHERE code = 'CARRY_SNAPSHOT'
  AND received_at >= now() - make_interval(hours => %(hours)s)
  AND (%(instance)s::text IS NULL OR instance_id = %(instance)s::text)
ORDER BY received_at, instance_id
"""

CARRYPASS_SUMMARY_SQL = """
SELECT received_at,
       instance_id,
       code,
       reason                 AS symbol,
       detail->>'eligible'    AS eligible,
       detail->>'shifted'     AS shifted,
       detail->>'clamped'     AS clamped,
       detail->>'skipped'     AS skipped,
       detail->>'failed'      AS failed,
       detail->>'incomplete'  AS incomplete
FROM ea_events
WHERE code IN ('CARRY_PASS_SUMMARY', 'CARRY_PASS_INCOMPLETE')
  AND received_at >= now() - make_interval(hours => %(hours)s)
  AND (%(instance)s::text IS NULL OR instance_id = %(instance)s::text)
ORDER BY received_at, instance_id
"""

CARRYPASS_FAULTS_SQL = """
SELECT instance_id,
       code,
       reason,
       count(*)                          AS n,
       min(received_at)                  AS first_at,
       max(received_at)                  AS last_at,
       bool_or(reason LIKE 'I6%%')       AS i6
FROM ea_events
WHERE (code IN ('QUARANTINE_ENTER', 'QUARANTINE_HALT', 'INVARIANT_FAIL', 'RECON_FAIL')
       OR level IN ('CRITICAL', 'FATAL'))
  AND received_at >= now() - make_interval(hours => %(hours)s)
  AND (%(instance)s::text IS NULL OR instance_id = %(instance)s::text)
GROUP BY instance_id, code, reason
ORDER BY i6 DESC, code, instance_id, reason
"""

ROLLOVERS_SQL = """
WITH legs AS (
  SELECT instance_id, position_id,
         MIN(deal_time_broker) FILTER (WHERE entry_type = 'IN')  AS opened,
         MAX(deal_time_broker) FILTER (WHERE entry_type <> 'IN') AS closed,
         MAX(layer_index)      FILTER (WHERE entry_type = 'IN')  AS layer_index,
         SUM(COALESCE(swap,0))                                   AS swap_booked
  FROM fill_logs
  GROUP BY instance_id, position_id
), spans AS (
  SELECT *,
         (closed::date - opened::date) AS rollovers,
         EXTRACT(EPOCH FROM (closed - opened))/60.0 AS hold_min
  FROM legs WHERE closed IS NOT NULL
)
SELECT instance_id,
       count(*)                                        AS layers,
       count(*) FILTER (WHERE rollovers > 0)           AS crossed,
       round(100.0*count(*) FILTER (WHERE rollovers>0)/count(*),1) AS pct_crossed,
       round(avg(rollovers)::numeric,2)                AS mean_rollovers,
       round(avg(hold_min)::numeric,1)                 AS mean_hold_min,
       round(sum(swap_booked)::numeric,2)              AS swap_usd
FROM spans GROUP BY instance_id ORDER BY instance_id;
"""

SLIPPAGE_DIST_SQL = """
SELECT instance_id,
       count(*)                                                    AS fills,
       count(*) FILTER (WHERE slippage_pips > 0)                   AS favourable,
       count(*) FILTER (WHERE slippage_pips < 0)                   AS adverse,
       count(*) FILTER (WHERE abs(slippage_pips) > 0.2)            AS beyond_i6,
       count(*) FILTER (WHERE slippage_pips < -0.2)                AS adverse_beyond_i6,
       round(avg(slippage_pips)::numeric, 3)                       AS mean_pips,
       round(min(slippage_pips)::numeric, 2)                       AS worst_adverse,
       round(max(slippage_pips)::numeric, 2)                       AS best_favourable
FROM fill_logs
WHERE slippage_pips IS NOT NULL
GROUP BY instance_id
ORDER BY adverse_beyond_i6 DESC, instance_id;
"""

SLIPPAGE_BREACH_SQL = """
SELECT deal_time_broker, instance_id, entry_type, deal_type, role,
       order_price_open, deal_price, slippage_pips, halted_at_receipt
FROM fill_logs
WHERE slippage_pips IS NOT NULL
  AND abs(slippage_pips) > 0.2
ORDER BY deal_time_broker DESC
LIMIT 40;
"""

L0_CHURN_SQL = """
WITH placements AS (
    SELECT result_order AS ticket,
           instance_id,
           role,
           layer_index
    FROM send_logs
    WHERE action = 'PENDING'
      AND ok
      AND result_order IS NOT NULL
      AND result_order <> 0
),
modify_counts AS (
    SELECT s.instance_id,
           count(*)                       AS modifies,
           count(*) FILTER (WHERE NOT s.ok) AS failed,
           min(s.received_at)             AS first_seen,
           max(s.received_at)             AS last_seen
    FROM send_logs s
    JOIN placements p
      ON p.ticket = s.order_ticket
     AND p.instance_id = s.instance_id
    WHERE s.action ILIKE '%MODIFY%'
      AND p.role = 'ENT'
      AND p.layer_index = 0
    GROUP BY s.instance_id
),
total_counts AS (
    SELECT instance_id,
           count(*)                          AS all_requests,
           count(DISTINCT received_at::date) AS active_days
    FROM send_logs
    GROUP BY instance_id
)
SELECT t.instance_id,
       COALESCE(m.modifies, 0)                        AS modifies,
       COALESCE(m.failed, 0)                          AS failed,
       round(COALESCE(m.modifies, 0)::numeric
             / NULLIF(t.active_days, 0), 1)           AS per_day,
       t.active_days,
       t.all_requests,
       round((COALESCE(m.modifies, 0)::numeric
              / NULLIF(t.all_requests, 0)) * 100, 1)  AS churn_pct,
       m.first_seen,
       m.last_seen
FROM total_counts t
LEFT JOIN modify_counts m USING (instance_id)
ORDER BY modifies DESC, t.instance_id
"""

L0_CHURN_MATCH_SQL = """
SELECT count(*)                                      AS modifies_total,
       count(*) FILTER (WHERE p.ticket IS NOT NULL)   AS matched,
       count(*) FILTER (WHERE p.ticket IS NULL)       AS unmatched
FROM send_logs s
LEFT JOIN (
    SELECT result_order AS ticket FROM send_logs
    WHERE action = 'PENDING' AND ok AND result_order IS NOT NULL
) p ON p.ticket = s.order_ticket
WHERE s.action ILIKE '%MODIFY%'
"""


def _print_query_rows(cur, rows, empty_message):
    if not rows:
        print(empty_message)
        return
    cols = [desc[0] for desc in cur.description]
    print(" | ".join(cols))
    for row in rows:
        print(" | ".join("" if v is None else str(v) for v in row))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--table", choices=sorted(TABLES))
    parser.add_argument("--instance")
    parser.add_argument("--carry", action="store_true")
    parser.add_argument("--rollovers", action="store_true")
    parser.add_argument("--slippage", action="store_true")
    parser.add_argument("--l0churn", action="store_true")
    parser.add_argument("--carrypass", action="store_true")
    parser.add_argument("--hours", type=int, default=30)
    args = parser.parse_args(argv)

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set.")
        return 1

    conn = psycopg2.connect(url)
    conn.set_session(readonly=True, autocommit=True)
    try:
        with conn.cursor() as cur:
            if args.carrypass:
                params = {"hours": args.hours, "instance": args.instance}
                print(f"== CARRY_SNAPSHOT, last {args.hours} h "
                      "(also emitted at every EA init) ==")
                cur.execute(CARRYPASS_SNAPSHOT_SQL, params)
                _print_query_rows(cur, cur.fetchall(), "no CARRY_SNAPSHOT rows.")
                print()
                print(f"== CARRY_PASS_SUMMARY / CARRY_PASS_INCOMPLETE, last {args.hours} h ==")
                cur.execute(CARRYPASS_SUMMARY_SQL, params)
                _print_query_rows(cur, cur.fetchall(), "no carry pass rows.")
                print()
                print(f"== QUARANTINE / INVARIANT / CRITICAL, last {args.hours} h ==")
                cur.execute(CARRYPASS_FAULTS_SQL, params)
                _print_query_rows(cur, cur.fetchall(), "none.")
                return 0

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

            if args.rollovers:
                cur.execute(ROLLOVERS_SQL)
                rows = cur.fetchall()
                if not rows:
                    print("no closed layers in fill_logs yet.")
                else:
                    cols = [desc[0] for desc in cur.description]
                    print(" | ".join(cols))
                    for row in rows:
                        print(" | ".join("" if v is None else str(v) for v in row))
                return 0

            if args.slippage:
                cur.execute(SLIPPAGE_DIST_SQL)
                dist_rows = cur.fetchall()
                _print_query_rows(cur, dist_rows, "no fills with slippage recorded yet.")
                print()
                cur.execute(SLIPPAGE_BREACH_SQL)
                breach_rows = cur.fetchall()
                breach_cols = [desc[0] for desc in cur.description]
                print(" | ".join(breach_cols))
                for row in breach_rows:
                    print(" | ".join("" if v is None else str(v) for v in row))
                return 0

            if args.l0churn:
                cur.execute(L0_CHURN_SQL)
                rows = cur.fetchall()
                _print_query_rows(cur, rows, "no rows in send_logs yet.")
                print()
                cur.execute(L0_CHURN_MATCH_SQL)
                match_rows = cur.fetchall()
                match_cols = [desc[0] for desc in cur.description]
                print(" | ".join(match_cols))
                for row in match_rows:
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
