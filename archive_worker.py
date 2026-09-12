"""
Archive worker: drains fxmatrix:archive:queue into Postgres.
Run as separate Railway service: python archive_worker.py
"""

import json
import logging
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

import psycopg2
import redis
from psycopg2.extras import Json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("archive_worker")

ARCHIVE_QUEUE = "fxmatrix:archive:queue"
ARCHIVE_PROCESSING = "fxmatrix:archive:processing"
ARCHIVE_DEADLETTER = "fxmatrix:archive:deadletter"
ARCHIVE_WORKER_KEY = "fxmatrix:archive:worker"
ARCHIVE_RETENTION_LAST = "fxmatrix:archive:retention_last"
ARCHIVE_CARRY_KEY = "fxmatrix:carry:table"
ARCHIVE_CARRY_LAST_BUILD = "fxmatrix:carry:last_build"

BATCH_MAX = 500
HEARTBEAT_INTERVAL_SECONDS = 10
WORKER_TTL_SECONDS = 120
RETENTION_INTERVAL = timedelta(hours=24)
CARRY_BUILD_INTERVAL = timedelta(hours=1)
BACKOFF_MAX_SECONDS = 30

CARRY_SQL = """
SELECT DISTINCT ON (detail->>'symbol')
       detail->>'symbol', detail->>'swap_long', detail->>'swap_short',
       detail->>'long_pips', detail->>'short_pips', detail->>'multiplier',
       detail->>'mult_tomorrow', detail->>'rollover3days', detail->>'swap_mode',
       detail->>'digits', detail->>'trade_mode_full', received_at
FROM ea_events
WHERE code = 'CARRY_SNAPSHOT'
ORDER BY detail->>'symbol', received_at DESC
"""

SEND_LOG_FIELDS = (
    "magic", "action", "order_type", "side", "layer_index", "role",
    "requested_price", "volume", "order_ticket", "position_ticket",
    "position_by_ticket", "comment", "ok", "retcode", "result_order",
    "result_deal", "duration_ms", "broker_time",
)

FILL_LOG_FIELDS = (
    "magic", "deal_ticket", "order_ticket", "position_id", "entry_type",
    "deal_type", "side", "layer_index", "role", "deal_price",
    "order_price_open", "slippage_pips", "volume", "profit", "swap",
    "commission", "deal_time_broker", "deal_time_broker_msc",
    "halted_at_receipt", "quarantined_at_receipt",
)

CONFIG_EVENT_FIELDS = (
    "magic", "event", "deinit_reason", "symbol", "slot", "ea_build",
    "account_login", "width_pips", "add_pips", "exit_pips", "max_layers",
    "lots", "deadband_pips", "stranded_thresh_pips", "cap_leg_a",
    "cap_leg_b", "cap_leg_a_thresh", "cap_leg_b_thresh",
)

EA_EVENT_FIELDS = ("magic", "level", "code", "reason", "ticket")

SCALP_FIELDS = (
    "instrument", "direction", "entry_price", "exit_price", "gross_pnl",
    "layer_depth", "stack_depth", "entry_deal_ticket", "exit_deal_ticket",
)


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def carry_parse_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def carry_parse_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def carry_parse_bool(value):
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


def carry_format_snapshot_at(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.isoformat()
    return str(value)


def build_carry_table(conn):
    rows = []
    with conn.cursor() as cur:
        cur.execute(CARRY_SQL)
        for (
            symbol,
            swap_long,
            swap_short,
            long_pips,
            short_pips,
            multiplier,
            mult_tomorrow,
            rollover3days,
            swap_mode,
            digits,
            trade_mode_full,
            received_at,
        ) in cur.fetchall():
            if symbol is None or str(symbol).strip() == "":
                continue
            swap_long_pts = carry_parse_float(swap_long)
            swap_short_pts = carry_parse_float(swap_short)
            mult_snapshot = carry_parse_int(multiplier)
            mult_tomorrow_val = carry_parse_int(mult_tomorrow)
            mult_used = (
                mult_tomorrow_val
                if mult_tomorrow_val is not None
                else mult_snapshot
            )
            long_pips_val = None
            short_pips_val = None
            if swap_long_pts is not None and mult_used is not None:
                long_pips_val = round(swap_long_pts * mult_used / 10, 3)
            if swap_short_pts is not None and mult_used is not None:
                short_pips_val = round(swap_short_pts * mult_used / 10, 3)
            row = {
                "symbol": symbol,
                "swap_long_pts": swap_long_pts,
                "swap_short_pts": swap_short_pts,
                "long_pips": long_pips_val,
                "short_pips": short_pips_val,
                "mult": mult_used,
                "mult_used": mult_used,
                "mult_snapshot": mult_snapshot,
                "rollover3days": carry_parse_int(rollover3days),
                "swap_mode": carry_parse_int(swap_mode),
                "digits": carry_parse_int(digits),
                "trade_mode_full": carry_parse_bool(trade_mode_full),
                "snapshot_at": carry_format_snapshot_at(received_at),
            }
            row["long_week_pips"] = (
                round(long_pips_val * 7, 2) if long_pips_val is not None else None
            )
            row["short_week_pips"] = (
                round(short_pips_val * 7, 2) if short_pips_val is not None else None
            )
            rows.append(row)
    return {"generated_at": utc_now_iso(), "rows": rows}


def publish_carry_table(redis_client, table):
    redis_client.set(ARCHIVE_CARRY_KEY, json.dumps(table))


def batch_contains_carry_snapshot(raw_items):
    for raw in raw_items:
        try:
            item = parse_queue_item(raw)
        except ValueError:
            continue
        if item.get("type") != "ea_event":
            continue
        event = item.get("event")
        if not isinstance(event, dict):
            continue
        if event.get("code") == "CARRY_SNAPSHOT":
            return True
    return False


def run_carry_build_if_due(conn, redis_client, force=False):
    if not force:
        last_raw = redis_client.get(ARCHIVE_CARRY_LAST_BUILD)
        now = datetime.now(timezone.utc)
        if last_raw:
            try:
                last_run = datetime.fromisoformat(last_raw)
                if last_run.tzinfo is None:
                    last_run = last_run.replace(tzinfo=timezone.utc)
                if now - last_run < CARRY_BUILD_INTERVAL:
                    return None
            except ValueError:
                pass
    table = build_carry_table(conn)
    publish_carry_table(redis_client, table)
    redis_client.set(ARCHIVE_CARRY_LAST_BUILD, utc_now_iso())
    return table


def try_carry_build(conn, redis_client, force=False):
    try:
        return run_carry_build_if_due(conn, redis_client, force=force)
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        raise
    except Exception as exc:
        log.warning("carry table build failed: %s", exc)
        return None


def parse_received_at(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return datetime.fromisoformat(value)


def parse_close_time_broker(close_time):
    if close_time is None:
        raise ValueError("close_time is required for scalp")
    text = str(close_time).rstrip("Z")
    if "T" in text:
        parsed = datetime.fromisoformat(text)
    else:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    return parsed.replace(tzinfo=None)


def parse_timestamp_field(value):
    if value is None:
        return None
    text = str(value).rstrip("Z")
    if "T" in text:
        parsed = datetime.fromisoformat(text)
    else:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    return parsed.replace(tzinfo=None)


def event_field(event, name):
    if name not in event:
        return None
    return event[name]


def build_row(item):
    event_type = item.get("type")
    event = item.get("event")
    if not isinstance(event, dict):
        raise ValueError("event must be an object")

    instance_id = item.get("instance_id")
    session_id = item.get("session_id")
    received_at = parse_received_at(item["received_at"])

    if event_type == "scalp":
        row = {
            "instance_id": instance_id,
            "received_at": received_at,
            "close_time_broker": parse_close_time_broker(event.get("close_time")),
            "source": "scalp_closed",
        }
        for field in SCALP_FIELDS:
            if field in event:
                row[field] = event[field]
        return finalize_row("scalp_history", row)

    if event_type not in ("send_log", "fill_log", "config_event", "ea_event"):
        raise ValueError(f"unknown type: {event_type}")

    row = {
        "instance_id": instance_id,
        "session_id": session_id,
        "seq": event.get("seq"),
        "ea_time_ms": event.get("ea_time_ms"),
        "received_at": received_at,
    }

    if event_type == "send_log":
        for field in SEND_LOG_FIELDS:
            value = event_field(event, field)
            if field in ("broker_time",):
                row[field] = parse_timestamp_field(value)
            else:
                row[field] = value
        return finalize_row("send_logs", row)

    if event_type == "fill_log":
        for field in FILL_LOG_FIELDS:
            value = event_field(event, field)
            if field == "deal_time_broker":
                row[field] = parse_timestamp_field(value)
            else:
                row[field] = value
        return finalize_row("fill_logs", row)

    if event_type == "config_event":
        for field in CONFIG_EVENT_FIELDS:
            row[field] = event_field(event, field)
        row["inputs"] = Json(event)
        return finalize_row("config_events", row)

    for field in EA_EVENT_FIELDS:
        row[field] = event_field(event, field)
    detail = event.get("detail")
    row["detail"] = Json(detail) if detail is not None else None
    return finalize_row("ea_events", row)


INSERT_SQL = {
    "send_logs": """
        INSERT INTO send_logs (
            instance_id, session_id, seq, ea_time_ms, received_at,
            magic, action, order_type, side, layer_index, role,
            requested_price, volume, order_ticket, position_ticket,
            position_by_ticket, comment, ok, retcode, result_order,
            result_deal, duration_ms, broker_time
        ) VALUES (
            %(instance_id)s, %(session_id)s, %(seq)s, %(ea_time_ms)s, %(received_at)s,
            %(magic)s, %(action)s, %(order_type)s, %(side)s, %(layer_index)s, %(role)s,
            %(requested_price)s, %(volume)s, %(order_ticket)s, %(position_ticket)s,
            %(position_by_ticket)s, %(comment)s, %(ok)s, %(retcode)s, %(result_order)s,
            %(result_deal)s, %(duration_ms)s, %(broker_time)s
        ) ON CONFLICT DO NOTHING
    """,
    "fill_logs": """
        INSERT INTO fill_logs (
            instance_id, session_id, seq, ea_time_ms, received_at,
            magic, deal_ticket, order_ticket, position_id, entry_type,
            deal_type, side, layer_index, role, deal_price,
            order_price_open, slippage_pips, volume, profit, swap,
            commission, deal_time_broker, deal_time_broker_msc,
            halted_at_receipt, quarantined_at_receipt
        ) VALUES (
            %(instance_id)s, %(session_id)s, %(seq)s, %(ea_time_ms)s, %(received_at)s,
            %(magic)s, %(deal_ticket)s, %(order_ticket)s, %(position_id)s, %(entry_type)s,
            %(deal_type)s, %(side)s, %(layer_index)s, %(role)s, %(deal_price)s,
            %(order_price_open)s, %(slippage_pips)s, %(volume)s, %(profit)s, %(swap)s,
            %(commission)s, %(deal_time_broker)s, %(deal_time_broker_msc)s,
            %(halted_at_receipt)s, %(quarantined_at_receipt)s
        ) ON CONFLICT DO NOTHING
    """,
    "config_events": """
        INSERT INTO config_events (
            instance_id, session_id, seq, ea_time_ms, received_at,
            magic, event, deinit_reason, symbol, slot, ea_build,
            account_login, width_pips, add_pips, exit_pips, max_layers,
            lots, deadband_pips, stranded_thresh_pips, cap_leg_a,
            cap_leg_b, cap_leg_a_thresh, cap_leg_b_thresh, inputs
        ) VALUES (
            %(instance_id)s, %(session_id)s, %(seq)s, %(ea_time_ms)s, %(received_at)s,
            %(magic)s, %(event)s, %(deinit_reason)s, %(symbol)s, %(slot)s, %(ea_build)s,
            %(account_login)s, %(width_pips)s, %(add_pips)s, %(exit_pips)s, %(max_layers)s,
            %(lots)s, %(deadband_pips)s, %(stranded_thresh_pips)s, %(cap_leg_a)s,
            %(cap_leg_b)s, %(cap_leg_a_thresh)s, %(cap_leg_b_thresh)s, %(inputs)s
        ) ON CONFLICT DO NOTHING
    """,
    "ea_events": """
        INSERT INTO ea_events (
            instance_id, session_id, seq, ea_time_ms, received_at,
            magic, level, code, reason, ticket, detail
        ) VALUES (
            %(instance_id)s, %(session_id)s, %(seq)s, %(ea_time_ms)s, %(received_at)s,
            %(magic)s, %(level)s, %(code)s, %(reason)s, %(ticket)s, %(detail)s
        ) ON CONFLICT DO NOTHING
    """,
    "scalp_history": """
        INSERT INTO scalp_history (
            instance_id, instrument, direction, entry_price, exit_price,
            gross_pnl, layer_depth, stack_depth, close_time_broker,
            entry_deal_ticket, exit_deal_ticket, source, received_at
        ) VALUES (
            %(instance_id)s, %(instrument)s, %(direction)s, %(entry_price)s, %(exit_price)s,
            %(gross_pnl)s, %(layer_depth)s, %(stack_depth)s, %(close_time_broker)s,
            %(entry_deal_ticket)s, %(exit_deal_ticket)s, %(source)s, %(received_at)s
        ) ON CONFLICT DO NOTHING
    """,
}

INSERT_PLACEHOLDERS = {
    table: re.findall(r"%\(([^)]+)\)s", sql)
    for table, sql in INSERT_SQL.items()
}


def finalize_row(table, row):
    for name in INSERT_PLACEHOLDERS[table]:
        if name not in row:
            row[name] = None
    return table, row


def parse_queue_item(raw):
    if isinstance(raw, dict):
        return raw
    try:
        item = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(item, dict):
        raise ValueError("queue item must be an object")
    return item


def insert_batch(conn, raw_items):
    with conn.cursor() as cur:
        for raw in raw_items:
            item = parse_queue_item(raw)
            table, row = build_row(item)
            cur.execute(INSERT_SQL[table], row)
    conn.commit()


def insert_single(conn, raw):
    with conn.cursor() as cur:
        item = parse_queue_item(raw)
        table, row = build_row(item)
        cur.execute(INSERT_SQL[table], row)
    conn.commit()


def is_connection_error(exc):
    if isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError)):
        return True
    if isinstance(exc, (redis.ConnectionError, redis.TimeoutError)):
        return True
    return False


def move_batch_to_processing(redis_client, max_items=BATCH_MAX):
    moved = 0
    for _ in range(max_items):
        item = redis_client.lmove(
            ARCHIVE_QUEUE, ARCHIVE_PROCESSING, "LEFT", "RIGHT"
        )
        if item is None:
            break
        moved += 1
    return moved


def trim_processing(redis_client, count):
    if count <= 0:
        return
    redis_client.ltrim(ARCHIVE_PROCESSING, count, -1)


def push_deadletter(redis_client, item, error):
    payload = json.dumps({
        "item": item,
        "error": str(error),
        "failed_at": utc_now_iso(),
    })
    redis_client.rpush(ARCHIVE_DEADLETTER, payload)
    log.error("deadletter: %s", error)


def process_processing_batch(redis_client, conn, raw_items):
    if not raw_items:
        return 0
    count = len(raw_items)
    try:
        insert_batch(conn, raw_items)
        trim_processing(redis_client, count)
        return count
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        log.warning("batch error, retrying one item at a time: %s", exc)
        return process_items_individually(redis_client, conn, raw_items)


def process_items_individually(redis_client, conn, raw_items):
    inserted = 0
    for raw in raw_items:
        try:
            insert_single(conn, raw)
            trim_processing(redis_client, 1)
            inserted += 1
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            conn.rollback()
            raise
        except Exception as exc:
            conn.rollback()
            try:
                item = parse_queue_item(raw)
            except ValueError:
                item = raw
            push_deadletter(
                redis_client, item, f"{type(exc).__name__}: {exc}"
            )
            trim_processing(redis_client, 1)
    return inserted


def run_retention_if_due(conn, redis_client):
    last_raw = redis_client.get(ARCHIVE_RETENTION_LAST)
    now = datetime.now(timezone.utc)
    if last_raw:
        try:
            last_run = datetime.fromisoformat(last_raw)
            if last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=timezone.utc)
            if now - last_run < RETENTION_INTERVAL:
                return None
        except ValueError:
            pass

    deleted = {}
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM send_logs WHERE received_at < now() - interval '14 days'"
        )
        deleted["send_logs"] = cur.rowcount
        cur.execute(
            "DELETE FROM ea_events WHERE received_at < now() - interval '90 days'"
        )
        deleted["ea_events"] = cur.rowcount
    conn.commit()
    redis_client.set(ARCHIVE_RETENTION_LAST, utc_now_iso())
    log.info(
        "retention: send_logs=%s ea_events=%s",
        deleted["send_logs"],
        deleted["ea_events"],
    )
    return deleted


def update_heartbeat(redis_client, state):
    payload = {
        "at": utc_now_iso(),
        "queue_len": redis_client.llen(ARCHIVE_QUEUE),
        "processing_len": redis_client.llen(ARCHIVE_PROCESSING),
        "deadletter_len": redis_client.llen(ARCHIVE_DEADLETTER),
        "last_batch": state.get("last_batch"),
        "inserted_total": state.get("inserted_total", 0),
        "last_error": state.get("last_error"),
        "retention_last": redis_client.get(ARCHIVE_RETENTION_LAST),
    }
    redis_client.set(
        ARCHIVE_WORKER_KEY,
        json.dumps(payload),
        ex=WORKER_TTL_SECONDS,
    )


def worker_cycle(redis_client, conn, state, sleep_fn):
    processing_len = redis_client.llen(ARCHIVE_PROCESSING)
    if processing_len > 0:
        raw_items = redis_client.lrange(ARCHIVE_PROCESSING, 0, -1)
        inserted = process_processing_batch(redis_client, conn, raw_items)
        if inserted:
            state["last_batch"] = inserted
            state["inserted_total"] = state.get("inserted_total", 0) + inserted
            if batch_contains_carry_snapshot(raw_items):
                try_carry_build(conn, redis_client, force=True)
        return False

    moved = move_batch_to_processing(redis_client)
    if moved == 0:
        sleep_fn(1)
        return True

    raw_items = redis_client.lrange(ARCHIVE_PROCESSING, 0, -1)
    inserted = process_processing_batch(redis_client, conn, raw_items)
    state["last_batch"] = inserted
    state["inserted_total"] = state.get("inserted_total", 0) + inserted
    if inserted and batch_contains_carry_snapshot(raw_items):
        try_carry_build(conn, redis_client, force=True)
    return False


def reconnect_with_backoff(attempt, sleep_fn):
    delay = min(BACKOFF_MAX_SECONDS, 2 ** max(0, attempt - 1))
    log.warning("reconnect attempt %s, sleeping %ss", attempt, delay)
    sleep_fn(delay)
    return attempt + 1


def connect_with_retry(conn_factory, sleep_fn, state):
    attempt = 0
    while True:
        try:
            return conn_factory()
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
            state["last_error"] = str(exc)
            log.warning("postgres connect failed: %s", exc)
            delay = min(BACKOFF_MAX_SECONDS, 2 ** attempt)
            sleep_fn(delay)
            attempt += 1


def worker_loop(redis_client, conn_factory, sleep_fn=None):
    if sleep_fn is None:
        sleep_fn = time.sleep

    state = {
        "inserted_total": 0,
        "last_batch": None,
        "last_error": None,
    }
    conn = connect_with_retry(conn_factory, sleep_fn, state)
    try_carry_build(conn, redis_client, force=True)
    redis_backoff = 0
    last_heartbeat = 0.0

    while True:
        try:
            now_mono = time.monotonic()
            if now_mono - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                try:
                    update_heartbeat(redis_client, state)
                    last_heartbeat = now_mono
                    redis_backoff = 0
                except (redis.ConnectionError, redis.TimeoutError) as exc:
                    state["last_error"] = str(exc)
                    log.warning("heartbeat redis error: %s", exc)
                    delay = min(BACKOFF_MAX_SECONDS, 2 ** redis_backoff)
                    sleep_fn(delay)
                    redis_backoff += 1
                    continue

            try:
                retention_result = run_retention_if_due(conn, redis_client)
                if retention_result is not None:
                    state["retention_last"] = utc_now_iso()
                try_carry_build(conn, redis_client, force=False)
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
                state["last_error"] = str(exc)
                try:
                    conn.close()
                except Exception:
                    pass
                conn = connect_with_retry(conn_factory, sleep_fn, state)
                continue
            except (redis.ConnectionError, redis.TimeoutError) as exc:
                state["last_error"] = str(exc)
                log.warning("redis error during retention: %s", exc)
                delay = min(BACKOFF_MAX_SECONDS, 2 ** redis_backoff)
                sleep_fn(delay)
                redis_backoff += 1
                continue
            except psycopg2.Error as exc:
                state["last_error"] = str(exc)
                try:
                    conn.rollback()
                except Exception:
                    pass
                sleep_fn(1)
                continue

            try:
                worker_cycle(redis_client, conn, state, sleep_fn)
                redis_backoff = 0
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
                state["last_error"] = str(exc)
                try:
                    conn.rollback()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
                conn = connect_with_retry(conn_factory, sleep_fn, state)
            except (redis.ConnectionError, redis.TimeoutError) as exc:
                state["last_error"] = str(exc)
                log.warning("redis error during worker cycle: %s", exc)
                delay = min(BACKOFF_MAX_SECONDS, 2 ** redis_backoff)
                sleep_fn(delay)
                redis_backoff += 1

        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            state["last_error"] = str(exc)
            log.error(
                "worker unexpected error: %s\n%s",
                exc,
                traceback.format_exc(),
            )
            sleep_fn(5)


def main():
    redis_url = os.environ.get("REDIS_URL")
    database_url = os.environ.get("DATABASE_URL")
    if not redis_url or not database_url:
        log.error("REDIS_URL and DATABASE_URL are required.")
        sys.exit(1)

    redis_client = redis.from_url(redis_url, decode_responses=True)

    def conn_factory():
        return psycopg2.connect(database_url)

    log.info("archive worker starting")
    worker_loop(redis_client, conn_factory)


if __name__ == "__main__":
    main()
