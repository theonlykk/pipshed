"""
Pipshed — FXMatrix Live Telemetry Dashboard
Flask backend: telemetry receiver + state server

Routes:
  POST /api/telemetry/push         — receives MQL5 payload, writes to Redis
  POST /api/telemetry/pod_closed   — pod-level close history
  POST /api/telemetry/scalp_closed — per-layer scalp close history
  POST /api/telemetry/action         — archive queue for EA events
  GET  /api/telemetry/live         — serves current state to dashboard
  GET  /api/telemetry/closed       — paginated pod-close history
  GET  /api/telemetry/scalps       — paginated scalp-close history
  GET  /api/telemetry/today_scalps    — cross-instance broker-today scalp exits
  GET  /api/telemetry/today_closed    — cross-instance broker-today pod closes
  GET  /api/telemetry/open_positions — cross-instance open pod snapshot
  GET  /api/g/<token>/status       — public grind status (unauthenticated)
  GET  /api/g/<token>/status_b     — public Fleet B grind status (unauthenticated)
  GET  /api/g/<token>/scalps       — public broker-today scalp exits
  GET  /api/g/<token>/archive      — public archive worker health
  GET  /api/g/<token>/carry        — public carry swap table (Redis only)
  GET  /api/g/<token>/daily        — public FTMO daily snapshot table (Redis only)
  GET  /api/g/<token>/critical     — public critical/warn last-24h groups (Redis only)
  GET  /api/g/<token>/summary      — public broker-day plain-text summary
  GET  /api/g/<token>/carry_audit  — public carry-adjusted order audit (JSON)
  GET  /api/g/<token>/ejection     — public roll/eject telemetry (Postgres + Redis)
  GET  /                         — dashboard UI
  GET  /health                   — Railway health check
"""

import json
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import redis
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request

load_dotenv()

app = Flask(__name__)

# Redis connection — Railway injects REDIS_URL automatically
r = redis.from_url(
    os.environ.get("REDIS_URL", "redis://localhost:6379"),
    decode_responses=True
)

TELEMETRY_API_KEY = os.environ.get("TELEMETRY_API_KEY", "")
REDIS_TTL_SECONDS = 300  # 5 minutes — if VPS drops, key expires
SCALP_HISTORY_LIST_MAX = 2999  # LTRIM 0..2999 => 3000 entries per instance
SCALP_HISTORY_TTL_SECONDS = 604800  # 7 days — matches pod history window

ARCHIVE_QUEUE_KEY = "fxmatrix:archive:queue"
ARCHIVE_PROCESSING_KEY = "fxmatrix:archive:processing"
ARCHIVE_DEADLETTER_KEY = "fxmatrix:archive:deadletter"
ARCHIVE_WORKER_KEY = "fxmatrix:archive:worker"
ARCHIVE_CARRY_KEY = "fxmatrix:carry:table"
ARCHIVE_DAILY_KEY = "fxmatrix:daily:table"
ARCHIVE_CRITICAL_KEY = "fxmatrix:critical:last24h"
ARCHIVE_ACTION_MAX_EVENTS = 500
ARCHIVE_EVENT_TYPES = frozenset({"send_log", "fill_log", "config_event", "ea_event"})

GRIND_A_INSTANCES = [
    "GRIND_GBPUSD_OPT",
    "GRIND_GBPUSD_ALT",
    "GRIND_EURUSD_OPT",
    "GRIND_EURUSD_ALT",
    "GRIND_EURGBP_OPT",
    "GRIND_EURGBP_ALT",
    "GRIND_AUDCAD_OPT",
    "GRIND_AUDCAD_ALT",
    "GRIND_AUDCHF_OPT",
    "GRIND_AUDCHF_ALT",
    "GRIND_CADCHF_OPT",
    "GRIND_CADCHF_ALT",
    "GRIND_NZDCHF_OPT",
    "GRIND_NZDCHF_ALT",
    "GRIND_NZDCAD_OPT",
    "GRIND_NZDCAD_ALT",
    "GRIND_AUDNZD_OPT",
    "GRIND_AUDNZD_ALT",
]

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

GRIND_A_STRIP_INSTANCES = [
    "GRIND_GBPUSD_OPT",
    "GRIND_EURUSD_OPT",
    "GRIND_EURGBP_OPT",
    "GRIND_AUDCAD_OPT",
    "GRIND_AUDCHF_OPT",
    "GRIND_CADCHF_OPT",
    "GRIND_NZDCHF_OPT",
    "GRIND_NZDCAD_OPT",
    "GRIND_AUDNZD_OPT",
    "GRIND_AUDNZD_ALT",
    "GRIND_NZDCAD_ALT",
]

FLEET_STRIP = [
    {
        "letter": "A",
        "name": "Cycle 3 (FTMO)",
        "broker": "FTMO",
        "url": "https://pipshed.com",
        "instances": GRIND_A_STRIP_INSTANCES,
        "daily_loss_limit_usd": 500.0,
        "cycle_start": "2026-09-24",
        "start_balance": 10000.0,
        "placeholder": False,
    },
    {
        "letter": "B",
        "name": "Fleet B (IC)",
        "broker": "IC Markets",
        "url": "https://linux.pipshed.com",
        "instances": GRIND_B_INSTANCES,
        "daily_loss_limit_usd": 500.0,
        "cycle_start": "2026-09-24",
        "start_balance": 10000.0,
        "placeholder": False,
    },
    {
        "letter": "C",
        "name": "Fleet C (IC)",
        "broker": "IC Markets",
        "url": "https://linuxc.pipshed.com",
        "instances": GRIND_C_INSTANCES,
        "daily_loss_limit_usd": 500.0,
        "cycle_start": "2026-09-28",
        "start_balance": 10000.0,
        "placeholder": False,
    },
    {
        "letter": "D",
        "name": "Fleet D (IC)",
        "broker": "IC Markets",
        "url": "https://linuxd.pipshed.com",
        "instances": GRIND_D_INSTANCES,
        "daily_loss_limit_usd": 500.0,
        "cycle_start": None,
        "start_balance": 10000.0,
        # wine-d (IC 53077984) built 30 Sep; a placeholder card until the EAs
        # attach. At attach: placeholder False and cycle_start the attach day.
        "placeholder": True,
        "built": True,
    },
]
FLEET_STRIP_STALE_S = 180

_grind_fleet_raw = os.environ.get("GRIND_FLEET", "A").strip().upper()
GRIND_FLEET_INSTANCES = {
    "A": GRIND_A_INSTANCES,
    "B": GRIND_B_INSTANCES,
    "C": GRIND_C_INSTANCES,
    "D": GRIND_D_INSTANCES,
}
if _grind_fleet_raw not in GRIND_FLEET_INSTANCES:
    logging.getLogger(__name__).warning(
        "Unknown GRIND_FLEET=%r; using fleet A", os.environ.get("GRIND_FLEET", "")
    )
    GRIND_FLEET = "A"
else:
    GRIND_FLEET = _grind_fleet_raw

GRIND_INSTANCES = GRIND_FLEET_INSTANCES[GRIND_FLEET]

GRIND_FLEET_LABEL = os.environ.get("GRIND_FLEET_LABEL", "")


def _grind_slot(inst):
    parts = inst.split("_")
    if len(parts) < 3:
        return ""
    slot = parts[2]
    if slot in ("OPTB", "ALTB", "OPTC", "ALTC", "OPTD", "ALTD"):
        return slot[:-1]
    return slot


GRIND_OPT_INSTANCES = [inst for inst in GRIND_INSTANCES if _grind_slot(inst) == "OPT"]
GRIND_ALT_INSTANCES = [inst for inst in GRIND_INSTANCES if _grind_slot(inst) == "ALT"]


def _fleet_summary(cards, raws, instances=None):
    insts = GRIND_B_INSTANCES if instances is None else instances
    instances_live = 0
    halted_instances = []
    open_layers_long = 0
    open_layers_short = 0
    scalps_total = 0
    net_mtm_total = 0.0
    realised_total = 0.0
    api_count_max = 0

    for inst in insts:
        card = cards.get(inst) or {}
        if card.get("connection") != "live":
            continue
        instances_live += 1
        open_layers_long += card.get("open_layers_long") or 0
        open_layers_short += card.get("open_layers_short") or 0
        scalps_total += card.get("scalps") or 0
        net_mtm_total += _grind_pnl_contribution(card.get("net_mtm"))
        realised_total += _grind_pnl_contribution(card.get("realised_pnl_today"))
        api_val = card.get("api_count")
        if isinstance(api_val, (int, float)):
            api_count_max = max(api_count_max, int(api_val))
        if card.get("halted"):
            halted_instances.append(inst)

    account_login = None
    account_balance = None
    account_equity = None
    for inst in insts:
        raw = raws.get(inst)
        if raw is None:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        if "account_login" not in data and "account_balance" not in data and "account_equity" not in data:
            continue
        if "account_login" in data:
            val = data["account_login"]
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                account_login = int(val)
        if "account_balance" in data:
            val = data["account_balance"]
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                account_balance = round(float(val), 2)
        if "account_equity" in data:
            val = data["account_equity"]
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                account_equity = round(float(val), 2)
        break

    return {
        "instances_total": len(insts),
        "instances_live": instances_live,
        "halted_instances": halted_instances,
        "open_layers_long": open_layers_long,
        "open_layers_short": open_layers_short,
        "scalps": scalps_total,
        "net_mtm": round(net_mtm_total, 2) if instances_live > 0 else 0,
        "realised_pnl_today": round(realised_total, 2) if instances_live > 0 else 0,
        "api_count": api_count_max if instances_live > 0 else None,
        "account_login": account_login,
        "account_balance": account_balance,
        "account_equity": account_equity,
    }


def _load_daily_table_rows():
    raw = r.get(ARCHIVE_DAILY_KEY)
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(payload, dict):
        return []
    rows = payload.get("rows")
    return rows if isinstance(rows, list) else []


def _fleet_strip_closed_today(view_payload, ftmo_day_iso):
    if not view_payload or not isinstance(view_payload, dict):
        return None, None, "view_unavailable"
    day_block = None
    for block in view_payload.get("days") or []:
        if isinstance(block, dict) and block.get("ftmo_day") == ftmo_day_iso:
            day_block = block
            break
    if day_block is None:
        return None, None, "no_day"
    scalps_today = 0
    closed_total = 0.0
    incomplete = False
    for inst in day_block.get("instances") or []:
        if not isinstance(inst, dict):
            continue
        for side in inst.get("sides") or []:
            if not isinstance(side, dict):
                continue
            scalps = side.get("scalps") or {}
            count = scalps.get("count")
            if isinstance(count, (int, float)) and not isinstance(count, bool):
                scalps_today += int(count)
            closed_net = side.get("closed_net")
            if closed_net is None:
                incomplete = True
                continue
            if isinstance(closed_net, (int, float)) and not isinstance(closed_net, bool):
                closed_total += float(closed_net)
    if incomplete:
        return scalps_today, None, "incomplete"
    return scalps_today, round(closed_total, 2), None


def _fleet_strip_day_pnl(rows, login, equity, ftmo_day_iso, limit):
    null = {
        "day_pnl": None,
        "day_start_balance": None,
        "anchor_day": None,
        "loss_share": None,
    }
    if login is None or equity is None or not ftmo_day_iso:
        return null
    if not isinstance(rows, list):
        return null
    try:
        login_int = int(login)
    except (TypeError, ValueError):
        return null
    if not isinstance(equity, (int, float)) or isinstance(equity, bool):
        return null
    best_day = None
    best_balance = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("ftmo_day") is None:
            continue
        day_key = str(row.get("ftmo_day"))
        if day_key >= ftmo_day_iso:
            continue
        try:
            row_login = int(row.get("account_login"))
        except (TypeError, ValueError):
            continue
        if row_login != login_int:
            continue
        balance_end = row.get("balance_end")
        if not isinstance(balance_end, (int, float)) or isinstance(balance_end, bool):
            continue
        if best_day is None or day_key > best_day:
            best_day = day_key
            best_balance = float(balance_end)
    if best_day is None or best_balance is None:
        return null
    day_pnl = round(float(equity) - best_balance, 2)
    loss_share = round(max(0.0, -day_pnl) / float(limit), 4)
    return {
        "day_pnl": day_pnl,
        "day_start_balance": round(best_balance, 2),
        "anchor_day": best_day,
        "loss_share": loss_share,
    }


def _fleet_strip_deepest(instances, cards):
    best = None
    for inst in instances:
        card = cards.get(inst) or {}
        if card.get("connection") != "live":
            continue
        for side_code, key in (("L", "open_layers_long"), ("S", "open_layers_short")):
            layers = card.get(key)
            if not isinstance(layers, (int, float)) or isinstance(layers, bool):
                continue
            layers_int = int(layers)
            if layers_int <= 0:
                continue
            if best is None or layers_int > best[0]:
                best = (layers_int, inst, side_code)
    if best is None:
        return None
    return {"instance_id": best[1], "side": best[2], "layers": best[0]}


def _fleet_strip_account(instances, cards, raw_by_inst):
    """Login, balance and equity for a fleet. Only the MAE reporter's heartbeat
    carries balance and equity (grind_mae.mqh 314-326; C72), so prefer the
    live instance that reports a balance; else the first live one with a
    login (money null)."""
    ordered = sorted(
        instances,
        key=lambda i: 0 if _fleet_strip_has_balance(raw_by_inst.get(i)) else 1,
    )
    return _fleet_strip_account_first(ordered, cards, raw_by_inst)


def _fleet_strip_has_balance(raw):
    try:
        data = json.loads(raw) if raw is not None else None
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    bal = data.get("account_balance")
    return isinstance(bal, (int, float)) and not isinstance(bal, bool)


def _fleet_strip_account_first(instances, cards, raw_by_inst):
    for inst in instances:
        if (cards.get(inst) or {}).get("connection") != "live":
            continue
        raw = raw_by_inst.get(inst)
        if raw is None:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        login = data.get("account_login")
        if not isinstance(login, (int, float)) or isinstance(login, bool):
            continue
        balance = data.get("account_balance")
        equity = data.get("account_equity")
        balance_out = (
            round(float(balance), 2)
            if isinstance(balance, (int, float)) and not isinstance(balance, bool)
            else None
        )
        equity_out = (
            round(float(equity), 2)
            if isinstance(equity, (int, float)) and not isinstance(equity, bool)
            else None
        )
        return {
            "login": int(login),
            "balance": balance_out,
            "equity": equity_out,
        }
    return {"login": None, "balance": None, "equity": None}


def _fleet_strip_oldest_age(instances, cards, raw_by_inst, now_dt):
    import ejection_view as ev

    oldest = None
    for inst in instances:
        if (cards.get(inst) or {}).get("connection") != "live":
            continue
        raw = raw_by_inst.get(inst)
        if raw is None:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        age = ev._heartbeat_timestamp_age_s(data, now_dt)
        if age is None:
            continue
        if oldest is None or age > oldest:
            oldest = age
    return oldest


def _fleet_strip_status(instances_live, instances_total, halted, oldest_age_s):
    if instances_live == 0:
        return "no_data"
    if halted or instances_live < instances_total:
        return "red"
    if oldest_age_s is None or oldest_age_s > FLEET_STRIP_STALE_S:
        return "amber"
    return "green"


def _fleet_strip_badge(instances_live, instances_total, placeholder):
    if placeholder:
        return "NOT BUILT"
    if instances_total > 0 and instances_live == instances_total:
        return "LIVE"
    if 0 < instances_live < instances_total:
        return "PARTIAL"
    return "NO CONNECTION"


def _fleet_strip_pair_symbol(instance_id):
    if not isinstance(instance_id, str):
        return ""
    parts = instance_id.split("_")
    return parts[1] if len(parts) > 1 else instance_id


def _load_critical_rows():
    raw = r.get(ARCHIVE_CRITICAL_KEY)
    if not raw:
        return None, False
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, False
    if not isinstance(payload, dict):
        return None, False
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return None, False
    return rows, True


# C7 (30 Sep): the account's book against the broker's 200 pending-order
# limit and the EA's entry guard (fxmatrix ea/grind_exitq.mqh 114-185:
# Grind_SlotEntryAllowed allows an entry while positions + orders + resting
# non-EXT orders <= 200 - (2 + GRIND_SLOT_MARGIN 4) = 194).
FLEET_SLOT_LIMIT = 200
FLEET_GUARD_LIMIT = 194
# ea/grind_api_counter.mqh 13-14, grind_config.mqh 11
FLEET_API_SOFT_WARN = 1800
FLEET_API_ENTRY_STOP = 1900


def _book_role(comment):
    """The role field of a GRIND comment (GRIND|OPT|L|L03|ENT -> ENT), else None."""
    if not isinstance(comment, str):
        return None
    parts = comment.split("|")
    if len(parts) >= 5 and parts[0] == "GRIND":
        return parts[4]
    return None


def _fleet_strip_slots(instances, cards, raw_by_inst):
    """Book (positions + orders) and the EA's guard total for the whole fleet,
    or None when any instance is not live or has no book (never partial)."""
    positions = orders = resting_non_ext = 0
    for inst in instances:
        if (cards.get(inst) or {}).get("connection") != "live":
            return None
        raw = raw_by_inst.get(inst)
        try:
            data = json.loads(raw) if raw is not None else None
        except (json.JSONDecodeError, TypeError):
            data = None
        book = data.get("book") if isinstance(data, dict) else None
        if not isinstance(book, dict):
            return None
        pos = book.get("positions")
        ords = book.get("orders")
        if not isinstance(pos, list) or not isinstance(ords, list):
            return None
        positions += len(pos)
        orders += len(ords)
        for o in ords:
            if not isinstance(o, dict) or _book_role(o.get("comment")) != "EXT":
                resting_non_ext += 1
    return {
        "orders": orders,
        "slots": positions + orders,
        "guard_total": positions + orders + resting_non_ext,
    }


def _fleet_strip_book(instances, cards, raw_by_inst, account):
    slots = _fleet_strip_slots(instances, cards, raw_by_inst)
    slot_fields = {
        "orders": slots["orders"] if slots else None,
        "slots": slots["slots"] if slots else None,
        "slot_limit": FLEET_SLOT_LIMIT,
        "guard_total": slots["guard_total"] if slots else None,
        "guard_limit": FLEET_GUARD_LIMIT,
    }
    null_book = {
        "positions": None,
        "pairs": None,
        "open_mtm_book": None,
        "financing": None,
    }
    null_book.update(slot_fields)
    position_count = 0
    symbols_with_positions = set()
    open_mtm = 0.0
    has_book = False

    for inst in instances:
        if (cards.get(inst) or {}).get("connection") != "live":
            continue
        raw = raw_by_inst.get(inst)
        if raw is None:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        book = data.get("book")
        if not isinstance(book, dict):
            continue
        positions = book.get("positions")
        if not isinstance(positions, list):
            continue
        has_book = True
        symbol = _fleet_strip_pair_symbol(inst)
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            position_count += 1
            if symbol:
                symbols_with_positions.add(symbol)
            profit = pos.get("profit")
            if isinstance(profit, (int, float)) and not isinstance(profit, bool):
                open_mtm += float(profit)

    if not has_book:
        return null_book

    equity = account.get("equity")
    balance = account.get("balance")
    open_mtm_book = round(open_mtm, 2)
    financing = None
    if (
        isinstance(equity, (int, float))
        and not isinstance(equity, bool)
        and isinstance(balance, (int, float))
        and not isinstance(balance, bool)
    ):
        financing = round(float(equity) - float(balance) - open_mtm_book, 2)

    out = {
        "positions": position_count,
        "pairs": len(symbols_with_positions),
        "open_mtm_book": open_mtm_book,
        "financing": financing,
    }
    out.update(slot_fields)
    return out


def _fleet_strip_sum_bucket_field(buckets, field, null_if_any_null=False):
    total = 0.0 if field != "count" else 0
    saw = False
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        val = bucket.get(field)
        if val is None:
            if null_if_any_null:
                return None
            continue
        if isinstance(val, bool):
            if null_if_any_null:
                return None
            continue
        if field == "count":
            total += int(val)
            saw = True
        elif isinstance(val, (int, float)):
            total += float(val)
            saw = True
    if field == "count":
        return total if saw or buckets else 0
    if not saw:
        return 0.0 if not null_if_any_null else None
    return round(total, 2)


def _fleet_strip_today(view_payload, ftmo_day_iso):
    if not view_payload or not isinstance(view_payload, dict):
        return None
    day_block = None
    for block in view_payload.get("days") or []:
        if isinstance(block, dict) and block.get("ftmo_day") == ftmo_day_iso:
            day_block = block
            break
    if day_block is None:
        return None

    scalp_buckets = []
    roll_buckets = []
    eject_buckets = []
    pair_scalps = {}
    pair_nets = {}
    pair_has_null_net = set()

    for inst in day_block.get("instances") or []:
        if not isinstance(inst, dict):
            continue
        pair = _fleet_strip_pair_symbol(inst.get("instance_id"))
        for side in inst.get("sides") or []:
            if not isinstance(side, dict):
                continue
            scalp_buckets.append(side.get("scalps") or {})
            roll_buckets.append(side.get("rolls") or {})
            eject_buckets.append(side.get("ejections") or {})
            scalps_b = side.get("scalps") or {}
            rolls_b = side.get("rolls") or {}
            eject_b = side.get("ejections") or {}
            act = 0
            for b in (scalps_b, rolls_b, eject_b):
                c = b.get("count")
                if isinstance(c, (int, float)) and not isinstance(c, bool):
                    act += int(c)
            if act <= 0:
                continue
            sc = scalps_b.get("count")
            if isinstance(sc, (int, float)) and not isinstance(sc, bool):
                pair_scalps[pair] = pair_scalps.get(pair, 0) + int(sc)
            closed_net = side.get("closed_net")
            if closed_net is None:
                pair_has_null_net.add(pair)
            elif isinstance(closed_net, (int, float)) and not isinstance(closed_net, bool):
                pair_nets[pair] = pair_nets.get(pair, 0.0) + float(closed_net)

    scalps = {
        "count": _fleet_strip_sum_bucket_field(scalp_buckets, "count"),
        "gross": _fleet_strip_sum_bucket_field(scalp_buckets, "gross"),
        "commission": _fleet_strip_sum_bucket_field(
            scalp_buckets, "commission", null_if_any_null=True
        ),
        "swap": _fleet_strip_sum_bucket_field(scalp_buckets, "swap", null_if_any_null=True),
        "net": _fleet_strip_sum_bucket_field(scalp_buckets, "net", null_if_any_null=True),
    }
    rolls = {
        "count": _fleet_strip_sum_bucket_field(roll_buckets, "count"),
        "net": _fleet_strip_sum_bucket_field(roll_buckets, "net", null_if_any_null=True),
    }
    ejections = {
        "count": _fleet_strip_sum_bucket_field(eject_buckets, "count"),
        "net": _fleet_strip_sum_bucket_field(eject_buckets, "net", null_if_any_null=True),
    }

    incomplete = (
        scalps.get("net") is None
        or rolls.get("net") is None
        or ejections.get("net") is None
    )
    if incomplete:
        total_net = None
    else:
        total_net = round(
            float(scalps["net"]) + float(rolls["net"]) + float(ejections["net"]), 2
        )

    by_pair = []
    for pair in set(list(pair_scalps.keys()) + list(pair_nets.keys())):
        if pair in pair_has_null_net:
            net_val = None
        else:
            net_val = round(pair_nets.get(pair, 0.0), 2)
        by_pair.append(
            {"pair": pair, "scalps": pair_scalps.get(pair, 0), "net": net_val}
        )

    def _pair_sort_key(row):
        net_val = row.get("net")
        if net_val is None:
            return (1, 0.0, row.get("pair") or "")
        return (0, -float(net_val), row.get("pair") or "")

    by_pair.sort(key=_pair_sort_key)

    return {
        "ftmo_day": ftmo_day_iso,
        "scalps": scalps,
        "rolls": rolls,
        "ejections": ejections,
        "total_net": total_net,
        "by_pair": by_pair,
        "incomplete": incomplete,
    }


def _fleet_strip_cycle(start_date_iso, start_balance, balance, equity, today_iso):
    null = {
        "start_date": start_date_iso,
        "day": None,
        "realised": None,
        "equity_change": None,
    }
    if not start_date_iso or not today_iso:
        return null
    from datetime import date as date_cls

    try:
        start_day = date_cls.fromisoformat(str(start_date_iso))
        today_day = date_cls.fromisoformat(str(today_iso))
    except ValueError:
        return null

    if today_day < start_day:
        realised = None
        if balance is None:
            realised_out = None
        elif isinstance(balance, (int, float)) and not isinstance(balance, bool):
            realised_out = round(float(balance) - float(start_balance or 0), 2)
        else:
            realised_out = None
        equity_change = None
        if equity is None:
            equity_change = None
        elif isinstance(equity, (int, float)) and not isinstance(equity, bool):
            equity_change = round(float(equity) - float(start_balance or 0), 2)
        return {
            "start_date": start_date_iso,
            "day": None,
            "realised": realised_out,
            "equity_change": equity_change,
        }

    weekday_count = 0
    cursor = start_day
    while cursor <= today_day:
        if cursor.weekday() < 5:
            weekday_count += 1
        cursor += timedelta(days=1)
    day_num = max(1, weekday_count)

    if balance is None or not isinstance(balance, (int, float)) or isinstance(balance, bool):
        realised = None
    else:
        realised = round(float(balance) - float(start_balance or 0), 2)

    if equity is None or not isinstance(equity, (int, float)) or isinstance(equity, bool):
        equity_change = None
    else:
        equity_change = round(float(equity) - float(start_balance or 0), 2)

    return {
        "start_date": start_date_iso,
        "day": day_num,
        "realised": realised,
        "equity_change": equity_change,
    }


def _fleet_strip_short_time(ts):
    """ISO timestamp -> 'HH:MMZ' (UTC) for banner lines; the raw text if unparsable."""
    if not isinstance(ts, str) or not ts.strip():
        return "--"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo("UTC")).strftime("%H:%MZ")


_FLEET_STRIP_ALERT_KIND_ORDER = {
    "HALTED": 0,
    "EVENT": 1,
    "DAY_LOSS": 2,
    "NOT_REPORTING": 3,
    "STALE_HEARTBEAT": 4,
    "LEDGER": 5,
    "EVENTS_UNAVAILABLE": 6,
}

_FLEET_STRIP_LEVEL_ORDER = {"red": 0, "amber": 1, "resolved": 2}

# CRITICAL codes that mean "this instance halted". A halt clears only when
# the EA restarts (g_grind_halted is reset in OnInit), so once the instance
# is live, not halted and invariant_ok true again, the event is history.
_FLEET_STRIP_HALT_CODES = frozenset({
    "INVARIANT_FAIL",
    "QUARANTINE_HALT",
    "RECON_FAIL",
    "REBUILD_EXIT_FAILED",
    "REBUILD_EXIT_UNREADABLE",
})


def _fleet_strip_recovered(instances, cards, raw_by_inst, halted):
    """Instances whose halt events are resolved: live now, not in the halted
    list, and a heartbeat with invariant_ok exactly true (a missing key
    never counts as recovered)."""
    halted_ids = {h.get("instance_id") for h in halted if isinstance(h, dict)}
    out = set()
    for inst in instances:
        if (cards.get(inst) or {}).get("connection") != "live" or inst in halted_ids:
            continue
        try:
            data = json.loads(raw_by_inst.get(inst) or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("invariant_ok") is True:
            out.add(inst)
    return out


def _fleet_strip_alert_sort_key(inst_index):
    return lambda a: (
        _FLEET_STRIP_LEVEL_ORDER.get(a.get("level"), 1),
        _FLEET_STRIP_ALERT_KIND_ORDER.get(a.get("kind"), 99),
        inst_index.get(a.get("instance_id"), 9999),
    )


def _fleet_strip_build_alerts(
    *,
    instances,
    cards,
    raw_by_inst,
    halted,
    instances_live,
    instances_total,
    critical_rows,
    critical_ok,
    closed_reason,
    loss_share,
    now_dt,
):
    import ejection_view as ev

    inst_index = {inst: idx for idx, inst in enumerate(instances)}
    alerts = []

    if instances_live == 0:
        if critical_ok and critical_rows:
            fleet_set = set(instances)
            for row in critical_rows:
                if not isinstance(row, dict):
                    continue
                inst = row.get("instance_id")
                if inst not in fleet_set:
                    continue
                level_raw = row.get("level")
                level = "red" if level_raw == "CRITICAL" else "amber"
                count = row.get("count")
                last_at = row.get("last_at") or ""
                alerts.append(
                    {
                        "level": level,
                        "kind": "EVENT",
                        "code": row.get("code"),
                        "instance_id": inst,
                        "detail": f"x{count}, last {_fleet_strip_short_time(last_at)}",
                    }
                )
        if not critical_ok:
            alerts.append(
                {
                    "level": "amber",
                    "kind": "EVENTS_UNAVAILABLE",
                    "code": "EVENTS_UNAVAILABLE",
                    "instance_id": None,
                    "detail": "critical feed unavailable",
                }
            )
        return sorted(alerts, key=_fleet_strip_alert_sort_key(inst_index))

    for h in halted:
        inst = h.get("instance_id")
        alerts.append(
            {
                "level": "red",
                "kind": "HALTED",
                "code": "HALTED",
                "instance_id": inst,
                "detail": h.get("halt_reason"),
            }
        )

    if critical_ok and critical_rows:
        fleet_set = set(instances)
        recovered = _fleet_strip_recovered(instances, cards, raw_by_inst, halted)
        for row in critical_rows:
            if not isinstance(row, dict):
                continue
            inst = row.get("instance_id")
            if inst not in fleet_set:
                continue
            level_raw = row.get("level")
            level = "red" if level_raw == "CRITICAL" else "amber"
            count = row.get("count")
            last_at = row.get("last_at") or ""
            detail = f"x{count}, last {_fleet_strip_short_time(last_at)}"
            if (level == "red" and row.get("code") in _FLEET_STRIP_HALT_CODES
                    and inst in recovered):
                level = "resolved"
                detail += ", resolved: instance running again"
            alerts.append(
                {
                    "level": level,
                    "kind": "EVENT",
                    "code": row.get("code"),
                    "instance_id": inst,
                    "detail": detail,
                }
            )
    elif not critical_ok:
        alerts.append(
            {
                "level": "amber",
                "kind": "EVENTS_UNAVAILABLE",
                "code": "EVENTS_UNAVAILABLE",
                "instance_id": None,
                "detail": "critical feed unavailable",
            }
        )

    if isinstance(loss_share, (int, float)) and not isinstance(loss_share, bool):
        if loss_share >= 0.8:
            alerts.append(
                {
                    "level": "red",
                    "kind": "DAY_LOSS",
                    "code": "DAY_LOSS",
                    "instance_id": None,
                    "detail": f"{round(float(loss_share) * 100, 1)}% of daily limit",
                }
            )
        elif loss_share >= 0.5:
            alerts.append(
                {
                    "level": "amber",
                    "kind": "DAY_LOSS",
                    "code": "DAY_LOSS",
                    "instance_id": None,
                    "detail": f"{round(float(loss_share) * 100, 1)}% of daily limit",
                }
            )

    if 0 < instances_live < instances_total:
        for inst in instances:
            if (cards.get(inst) or {}).get("connection") == "live":
                continue
            alerts.append(
                {
                    "level": "amber",
                    "kind": "NOT_REPORTING",
                    "code": "NOT_REPORTING",
                    "instance_id": inst,
                    "detail": "no heartbeat",
                }
            )

    for inst in instances:
        if (cards.get(inst) or {}).get("connection") != "live":
            continue
        raw = raw_by_inst.get(inst)
        age = None
        if raw is not None:
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                data = None
            if isinstance(data, dict):
                age = ev._heartbeat_timestamp_age_s(data, now_dt)
        if age is None or age > FLEET_STRIP_STALE_S:
            alerts.append(
                {
                    "level": "amber",
                    "kind": "STALE_HEARTBEAT",
                    "code": "STALE_HEARTBEAT",
                    "instance_id": inst,
                    "detail": f"{age if age is not None else 'unknown'} s",
                }
            )

    if closed_reason in ("view_unavailable", "incomplete"):
        alerts.append(
            {
                "level": "amber",
                "kind": "LEDGER",
                "code": closed_reason,
                "instance_id": None,
                "detail": closed_reason.replace("_", " "),
            }
        )

    return sorted(alerts, key=_fleet_strip_alert_sort_key(inst_index))


def _fleet_strip_placeholder_card(entry):
    limit = entry.get("daily_loss_limit_usd")
    return {
        "letter": entry["letter"],
        "name": entry["name"],
        "broker": entry["broker"],
        "url": entry.get("url"),
        "placeholder": True,
        "is_self": entry["letter"] == GRIND_FLEET,
        "status": "grey",
        "health": {
            "instances_total": 0,
            "instances_live": 0,
            "halted": [],
            "oldest_heartbeat_age_s": None,
        },
        "account": {"login": None, "balance": None, "equity": None},
        "money": {
            "open_mtm": None,
            "closed_net_today": None,
            "scalps_today": None,
            "closed_reason": None,
        },
        "risk": {
            "open_layers_long": None,
            "open_layers_short": None,
            "deepest": None,
            "day_pnl": None,
            "day_start_balance": None,
            "anchor_day": None,
            "loss_share": None,
            "daily_loss_limit_usd": limit,
        },
        "badge": "NOT ATTACHED" if entry.get("built") else "NOT BUILT",
        "book": {
            "positions": None,
            "pairs": None,
            "open_mtm_book": None,
            "financing": None,
        },
        "today": None,
        "cycle": None,
        "alerts": [],
    }


def _card_summary_day(now_utc=None):
    """The broker day the fleet card shows (C81). The broker day (server
    GMT+2/+3) rolls an hour BEFORE the FTMO day (Prague midnight); for that
    hour the new broker day has nothing booked. Keep the previous broker day
    until the FTMO roll: the card's day is the FTMO day's date (outside that
    hour the two dates are equal)."""
    from datetime import timezone as _tz
    from ftmo_daily import ftmo_day_of_utc
    return ftmo_day_of_utc(now_utc or datetime.now(_tz.utc)).isoformat()


def _fleet_strip_summary(entry, instances, cards):
    """The daily summary's numbers for one fleet (its own instances), for the
    card's broker day (_card_summary_day); the same function builds the text
    summary."""
    try:
        broker_today = _card_summary_day()
        _, records = _collect_today_scalp_records(broker_today, instances=instances)
        data = _summary_data(records)
        start = entry.get("cycle_start") or DEFAULT_CYCLE_START_DATE
        data["cycle"] = _summary_cycle(
            _collect_scalp_records_between(start, broker_today, instances=instances),
            start, broker_today, broker_today)
    except Exception:
        app.logger.exception("fleet strip summary failed for %s", entry.get("letter"))
        return None
    data["broker_day"] = broker_today
    deepest = None
    for inst in instances:
        card = cards.get(inst) or {}
        if card.get("connection") != "live":
            continue
        pair = inst.split("_")[1] if "_" in inst else inst
        for side, key in (("L", "open_layers_long"), ("S", "open_layers_short")):
            n = card.get(key)
            if isinstance(n, (int, float)) and not isinstance(n, bool):
                if deepest is None or int(n) > deepest["layers"]:
                    deepest = {"layers": int(n), "pair": pair, "side": side}
    data["deepest_side"] = deepest
    return data


def _fleet_strip_live_card(
    entry,
    cards,
    raw_by_inst,
    view_payload,
    ftmo_day_iso,
    daily_rows,
    closed_unavailable,
    critical_rows,
    critical_ok,
):
    instances = list(entry["instances"])
    instances_total = len(instances)
    instances_live = 0
    halted = []
    open_mtm_total = 0.0
    open_layers_long = 0
    open_layers_short = 0

    api_count = None
    for inst in instances:
        card = cards.get(inst) or {}
        if card.get("connection") != "live":
            continue
        instances_live += 1
        api_val = card.get("api_count")
        if isinstance(api_val, (int, float)) and not isinstance(api_val, bool):
            # one shared counter per terminal (ea/grind_api_counter.mqh): max, not sum
            api_count = int(api_val) if api_count is None else max(api_count, int(api_val))
        open_mtm_total += _grind_pnl_contribution(card.get("net_mtm"))
        open_layers_long += card.get("open_layers_long") or 0
        open_layers_short += card.get("open_layers_short") or 0
        if card.get("halted"):
            halted.append(
                {
                    "instance_id": inst,
                    "halt_reason": card.get("halt_reason"),
                }
            )

    now_dt = datetime.now(ZoneInfo("UTC"))
    oldest_age_s = _fleet_strip_oldest_age(instances, cards, raw_by_inst, now_dt)
    status = _fleet_strip_status(instances_live, instances_total, halted, oldest_age_s)

    if instances_live == 0:
        open_mtm = None
        layers_long = None
        layers_short = None
        deepest = None
    else:
        open_mtm = round(open_mtm_total, 2)
        layers_long = open_layers_long
        layers_short = open_layers_short
        deepest = _fleet_strip_deepest(instances, cards)

    account = _fleet_strip_account(instances, cards, raw_by_inst)

    if closed_unavailable:
        scalps_today = None
        closed_net_today = None
        closed_reason = "view_unavailable"
    else:
        scalps_today, closed_net_today, closed_reason = _fleet_strip_closed_today(
            view_payload, ftmo_day_iso
        )

    day_fields = _fleet_strip_day_pnl(
        daily_rows,
        account.get("login"),
        account.get("equity"),
        ftmo_day_iso,
        entry.get("daily_loss_limit_usd") or 500.0,
    )

    if closed_unavailable:
        today_block = None
    else:
        today_block = _fleet_strip_today(view_payload, ftmo_day_iso)

    book = _fleet_strip_book(instances, cards, raw_by_inst, account)
    cycle = _fleet_strip_cycle(
        entry.get("cycle_start"),
        entry.get("start_balance"),
        account.get("balance"),
        account.get("equity"),
        ftmo_day_iso,
    )
    if isinstance(cycle, dict):
        cycle["start_balance"] = entry.get("start_balance")
    summary = _fleet_strip_summary(entry, instances, cards)
    badge = _fleet_strip_badge(instances_live, instances_total, False)
    alerts = _fleet_strip_build_alerts(
        instances=instances,
        cards=cards,
        raw_by_inst=raw_by_inst,
        halted=halted,
        instances_live=instances_live,
        instances_total=instances_total,
        critical_rows=critical_rows,
        critical_ok=critical_ok,
        closed_reason=closed_reason,
        loss_share=day_fields.get("loss_share"),
        now_dt=now_dt,
    )

    return {
        "letter": entry["letter"],
        "name": entry["name"],
        "broker": entry["broker"],
        "url": entry.get("url"),
        "placeholder": False,
        "is_self": entry["letter"] == GRIND_FLEET,
        "status": status,
        "health": {
            "instances_total": instances_total,
            "instances_live": instances_live,
            "halted": halted,
            "oldest_heartbeat_age_s": oldest_age_s,
        },
        "account": account,
        "money": {
            "open_mtm": open_mtm,
            "closed_net_today": closed_net_today,
            "scalps_today": scalps_today,
            "closed_reason": closed_reason,
        },
        "risk": {
            "open_layers_long": layers_long,
            "open_layers_short": layers_short,
            "deepest": deepest,
            "day_pnl": day_fields["day_pnl"],
            "day_start_balance": day_fields["day_start_balance"],
            "anchor_day": day_fields["anchor_day"],
            "loss_share": day_fields["loss_share"],
            "daily_loss_limit_usd": entry.get("daily_loss_limit_usd"),
        },
        "badge": badge,
        "book": book,
        "api": {
            "count": api_count,
            "limit": GRIND_API_DAILY_LIMIT,
            "soft_warn": FLEET_API_SOFT_WARN,
            "entry_stop": FLEET_API_ENTRY_STOP,
        },
        "today": today_block,
        "cycle": cycle,
        "summary": summary,
        "alerts": alerts,
    }


def _build_fleet_strip_payload():
    import ejection_view as ev
    from ftmo_daily import ftmo_day_of_utc

    now_dt = datetime.now(ZoneInfo("UTC"))
    ftmo_day_iso = ftmo_day_of_utc(now_dt).isoformat()
    daily_rows = _load_daily_table_rows()
    critical_rows, critical_ok = _load_critical_rows()

    views_by_letter = ev.ejection_views_for_fleets(r, FLEET_STRIP, hours=24)
    closed_unavailable = views_by_letter is None

    cards_by_fleet = {}
    raw_by_fleet = {}
    for entry in FLEET_STRIP:
        if entry.get("placeholder"):
            continue
        letter = entry["letter"]
        cards = {}
        raw_map = {}
        for inst in entry["instances"]:
            raw_grind = r.get(f"fxmatrix:state:{inst}")
            raw_map[inst] = raw_grind
            cards[inst] = _summarize_grind_instance_state(inst, raw_grind)
        cards_by_fleet[letter] = cards
        raw_by_fleet[letter] = raw_map

    fleets_out = []
    for entry in FLEET_STRIP:
        if entry.get("placeholder"):
            fleets_out.append(_fleet_strip_placeholder_card(entry))
            continue
        letter = entry["letter"]
        view_payload = None if closed_unavailable else views_by_letter.get(letter)
        fleets_out.append(
            _fleet_strip_live_card(
                entry,
                cards_by_fleet[letter],
                raw_by_fleet[letter],
                view_payload,
                ftmo_day_iso,
                daily_rows,
                closed_unavailable,
                critical_rows,
                critical_ok,
            )
        )

    return {
        "generated_at": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ftmo_day": ftmo_day_iso,
        "fleets": fleets_out,
    }


# Ring membership — one edit here adds a ring everywhere downstream.
GRIND_RINGS = {
    "eur_gbp_usd": {
        "label": "EUR / GBP / USD",
        "symbols": ["GBPUSD", "EURUSD", "EURGBP"],
    },
    "aud_cad_chf": {
        "label": "AUD / CAD / CHF",
        "symbols": ["AUDCAD", "AUDCHF", "CADCHF"],
    },
    # Single-pair pilot. NZDCHF scored 2nd of ten on the 2026-09-13
    # calibration sweep. Ring membership is UNDECIDED (see
    # HANDOFF_2026-09-13 s3): the data favours an AUD/NZD/CAD/CHF
    # 4-cycle, which would make this an edge rather than a pilot.
    "nzdchf_pilot": {
        "label": "NZDCHF (pilot)",
        "symbols": ["NZDCHF"],
    },
    # NZD extension, live 2026-09-16. Completes the AUD/NZD/CAD/CHF
    # 4-cycle predicted in HANDOFF_2026-09-13 s3 (AUDNZD -> NZDCAD ->
    # CADCHF -> AUDCHF), but AUDCAD remains a chord across that cycle,
    # so the fleet is NOT uniform: AUD and CAD now carry 6 instances
    # each while CHF, EUR, GBP, NZD and USD carry 4. Ring membership is
    # provisional pending the topology decision in fxmatrix ADR-150 s5.
    "nzd_ext": {
        "label": "NZD extension",
        "symbols": ["NZDCAD", "AUDNZD"],
    },
}

GRIND_DEFAULT_INSTANCE = GRIND_INSTANCES[0]

PUBLIC_GRIND_STATUS_TOKEN = "k7m9p2x4q"

GRIND_HEARTBEAT_INTERVAL_SECONDS = int(
    os.environ.get("GRIND_HEARTBEAT_INTERVAL_SECONDS", "10")
)
GRIND_ACCOUNT_METRICS_MAX_AGE_SECONDS = GRIND_HEARTBEAT_INTERVAL_SECONDS * 2

GRIND_API_DAILY_LIMIT = 2000

# WARNING: fxgrind does not emit lot size in its telemetry payload.
# This is an ASSUMED constant. If any instance's InpLots is changed from
# 0.01, this figure UNDERREPORTS account exposure and must be updated.
GRIND_ASSUMED_LOT_SIZE = 0.01

GRIND_KNOWN_SYMBOLS = frozenset(inst.split("_")[1] for inst in GRIND_INSTANCES)

# FTMO / MT5 server time — matches EA trade_date (TimeCurrent() on broker)
BROKER_TIMEZONE = os.environ.get("BROKER_TIMEZONE", "Europe/Athens")
DEFAULT_CYCLE_START_DATE = "2026-09-10"
CYCLE_START_DATE = os.environ.get("CYCLE_START_DATE", DEFAULT_CYCLE_START_DATE)


def _broker_today():
    """Return YYYY-MM-DD for the current broker session calendar date."""
    return datetime.now(ZoneInfo(BROKER_TIMEZONE)).strftime("%Y-%m-%d")


def _utc_now_iso():
    """UTC ISO-8601 with microseconds and +00:00 offset."""
    return datetime.now(ZoneInfo("UTC")).isoformat(timespec="microseconds")


def _is_int_not_bool(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_archive_action_body(body):
    if body is None:
        return "Invalid JSON"
    if not isinstance(body, dict):
        return "body must be an object"
    instance_id = body.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id:
        return "instance_id required"
    session_id = body.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return "session_id required"
    events = body.get("events")
    if events is None:
        return "events required"
    if not isinstance(events, list):
        return "events must be a list"
    if len(events) == 0:
        return "events must not be empty"
    if len(events) > ARCHIVE_ACTION_MAX_EVENTS:
        return "events exceeds maximum"
    for event in events:
        if not isinstance(event, dict):
            return "event must be an object"
        event_type = event.get("type")
        if event_type not in ARCHIVE_EVENT_TYPES:
            return "unknown event type"
        seq = event.get("seq")
        if not _is_int_not_bool(seq) or seq < 0:
            return "seq must be a non-negative integer"
        ea_time_ms = event.get("ea_time_ms")
        if not _is_int_not_bool(ea_time_ms):
            return "ea_time_ms must be an integer"
    return None


def _grind_instances_for_ring(ring_id):
    """Return GRIND_INSTANCES whose symbol belongs to the given ring."""
    symbols = frozenset(GRIND_RINGS[ring_id]["symbols"])
    return [inst for inst in GRIND_INSTANCES if inst.split("_")[1] in symbols]


def _round_mae_float(value):
    """Round a telemetry MAE float for display, or None if absent."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return None


def _empty_intraday_mae():
    """Absent-data MAE payload — UI renders these as '--', never a 500."""
    return {
        "source_instance": None,
        "mae_equity_low": None,
        "mae_equity_low_dist_to_floor": None,
        "mae_open_mtm_trough": None,
        "mae_open_mtm_peak": None,
        "mae_pair_mtm_trough_gbpusd": None,
        "mae_pair_mtm_trough_eurusd": None,
        "mae_pair_mtm_trough_eurgbp": None,
        "mae_day_key": None,
    }


def _mae_from_engine_state(es, instance_id):
    """Pull account-level MAE from a flat field dict. Do not sum across instances."""
    mae = _empty_intraday_mae()
    if not isinstance(es, dict):
        return mae
    day_key = es.get("mae_day_key")
    mae.update({
        "source_instance": instance_id,
        "mae_equity_low": _round_mae_float(es.get("mae_equity_low")),
        "mae_equity_low_dist_to_floor": _round_mae_float(
            es.get("mae_equity_low_dist_to_floor")
        ),
        "mae_open_mtm_trough": _round_mae_float(es.get("mae_open_mtm_trough")),
        "mae_open_mtm_peak": _round_mae_float(es.get("mae_open_mtm_peak")),
        "mae_pair_mtm_trough_gbpusd": _round_mae_float(
            es.get("mae_pair_mtm_trough_gbpusd")
        ),
        "mae_pair_mtm_trough_eurusd": _round_mae_float(
            es.get("mae_pair_mtm_trough_eurusd")
        ),
        "mae_pair_mtm_trough_eurgbp": _round_mae_float(
            es.get("mae_pair_mtm_trough_eurgbp")
        ),
        "mae_day_key": day_key.strip() if isinstance(day_key, str) and day_key.strip() else None,
    })
    return mae


def _mae_from_grind_payload(data, instance_id):
    """Pull intraday MAE from grind heartbeat — nested intraday_mae or legacy flat."""
    if not isinstance(data, dict):
        return _empty_intraday_mae()

    nested = data.get("intraday_mae")
    if isinstance(nested, dict):
        src = nested.get("source_instance")
        mae_inst = src.strip() if isinstance(src, str) and src.strip() else instance_id
        return _mae_from_engine_state(nested, mae_inst)

    es = data.get("engine_state", data)
    return _mae_from_engine_state(es if isinstance(es, dict) else {}, instance_id)


def _parse_grind_payload_timestamp(data):
    """Parse ISO timestamp from a grind heartbeat, or None if absent/invalid."""
    ts = data.get("timestamp")
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _grind_money_field(data, key):
    """Extract a money field from flat grind payload — null stays None."""
    val = data.get(key)
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return round(float(val), 2)
    return None


def _read_global_account_metrics():
    """Account-level balance/equity/MAE from the freshest lease-holding heartbeat.

    Scans all grind instances for a non-null account_balance. Skips payloads
    whose timestamp is older than two heartbeat intervals; among fresh records,
    picks the newest timestamp so a stale first-match does not win.
    """
    now = datetime.now(ZoneInfo("UTC"))
    max_age = timedelta(seconds=GRIND_ACCOUNT_METRICS_MAX_AGE_SECONDS)
    best = None
    best_ts = None

    for inst in GRIND_INSTANCES:
        raw = r.get(f"fxmatrix:state:{inst}")
        if raw is None:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

        balance = _grind_money_field(data, "account_balance")
        if balance is None:
            continue

        payload_ts = _parse_grind_payload_timestamp(data)
        if payload_ts is not None and (now - payload_ts) > max_age:
            continue

        rank_ts = payload_ts or datetime.min.replace(tzinfo=ZoneInfo("UTC"))
        if best is not None and best_ts is not None and rank_ts <= best_ts:
            continue

        ts_out = data.get("timestamp")
        timestamp_out = ts_out.strip() if isinstance(ts_out, str) and ts_out.strip() else None

        best = {
            "balance": balance,
            "equity": _grind_money_field(data, "account_equity"),
            "source_instance": inst,
            "timestamp": timestamp_out,
            "intraday_mae": _mae_from_grind_payload(data, inst),
        }
        best_ts = rank_ts

    return best


def _read_intraday_mae():
    """Account-level intraday MAE from the global account metrics scan."""
    global_metrics = _read_global_account_metrics()
    if global_metrics and global_metrics.get("intraday_mae"):
        return global_metrics["intraday_mae"]
    return _empty_intraday_mae()


def _grind_bool(value):
    """Coerce fxgrind heartbeat booleans (JSON true/false or legacy strings)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == "true"
    return False


def _grind_price_or_none(value):
    """Parse a heartbeat price field — absent stays None, never zero."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 5)
    return None


def _grind_pending_side_fields(data, side):
    """Resting-entry tracker prices and broker count for one side."""
    l0_key = f"l0_pending_{side}"
    add_key = f"add_pending_{side}"
    resting_key = f"resting_entries_{side}"

    l0 = _grind_price_or_none(data.get(l0_key)) if l0_key in data else None
    add = _grind_price_or_none(data.get(add_key)) if add_key in data else None

    resting = None
    if resting_key in data:
        raw = data.get(resting_key)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            resting = int(raw)

    drift = None
    if resting is not None:
        expected = (1 if l0 is not None else 0) + (1 if add is not None else 0)
        if resting != expected:
            drift = {
                "side": side,
                "expected": expected,
                "actual": resting,
            }

    return {
        f"l0_pending_{side}": l0,
        f"add_pending_{side}": add,
        f"resting_entries_{side}": resting,
        f"resting_drift_{side}": drift,
    }


def _grind_layers_from_payload(data):
    """Parse per-layer detail from heartbeat — missing/absent stays None."""
    layers_raw = data.get("layers")
    if not isinstance(layers_raw, list):
        return None

    layers = []
    for layer in layers_raw:
        if not isinstance(layer, dict):
            continue
        idx = layer.get("layer_index")
        side = layer.get("side")
        entry = _grind_price_or_none(layer.get("entry_price"))
        exit_target = _grind_price_or_none(layer.get("exit_target"))
        has_exit_order = layer.get("has_exit_order")
        has_exit_position = layer.get("has_exit_position")
        if isinstance(has_exit_order, str):
            has_exit_order = has_exit_order.lower() == "true"
        if isinstance(has_exit_position, str):
            has_exit_position = has_exit_position.lower() == "true"
        if not isinstance(has_exit_order, bool):
            has_exit_order = None
        if not isinstance(has_exit_position, bool):
            has_exit_position = None
        layers.append({
            "layer_index": int(idx) if isinstance(idx, (int, float)) and not isinstance(idx, bool) else None,
            "side": side if isinstance(side, str) and side else None,
            "entry_price": entry,
            "exit_target": exit_target,
            "has_exit_order": has_exit_order,
            "has_exit_position": has_exit_position,
        })
    return layers if layers else None


def _grind_book_from_payload(data):
    """Pass through broker book from heartbeat — whole object, unfiltered."""
    book_raw = data.get("book")
    if not isinstance(book_raw, dict):
        return None
    return book_raw


def _summarize_grind_instance_state(instance_id, raw_payload):
    """Build per-instance card fields from a flat fxgrind heartbeat (or None)."""
    empty = {
        "instance_id": instance_id,
        "connection": "no_data",
        "slot": None,
        "open_layers_long": None,
        "open_layers_short": None,
        "fills": None,
        "scalps": None,
        "api_count": None,
        "api_counter_broken": None,
        "cap_blocked": None,
        "halted": None,
        "halt_reason": None,
        "recon_ok": None,
        "invariant_ok": None,
        "cap_leg_a": None,
        "cap_leg_b": None,
        "cap_total_leg_a": None,
        "cap_total_leg_b": None,
        "peer_read_failed": None,
        "magic": None,
        "width_pips": None,
        "add_pips": None,
        "exit_pips": None,
        "max_layers": None,
        "cap_leg_a_name": None,
        "cap_leg_b_name": None,
        "net_mtm": None,
        "realised_pnl_today": None,
        "scalp_pnl_last": None,
        "exit_penetration_pips_last": None,
        "exit_penetration_pips_mean": None,
        "exit_touch_revert_count": None,
        "layers": None,
        "book": None,
        "l0_pending_long": None,
        "l0_pending_short": None,
        "add_pending_long": None,
        "add_pending_short": None,
        "resting_entries_long": None,
        "resting_entries_short": None,
        "resting_drift_long": None,
        "resting_drift_short": None,
        "account_balance": None,
        "account_equity": None,
    }
    if raw_payload is None:
        return empty

    data = json.loads(raw_payload)

    def _int_or_none(key):
        val = data.get(key)
        if isinstance(val, bool):
            return None
        if isinstance(val, (int, float)):
            return int(val)
        return None

    def _float_or_none(key):
        val = data.get(key)
        if isinstance(val, bool):
            return None
        if isinstance(val, (int, float)):
            return round(float(val), 4)
        return None

    def _money_or_none(key):
        val = data.get(key)
        if isinstance(val, bool):
            return None
        if isinstance(val, (int, float)):
            return round(float(val), 2)
        return None

    magic_val = data.get("magic")
    magic_out = None
    if isinstance(magic_val, (int, float)):
        magic_out = int(magic_val)
    elif isinstance(magic_val, str) and magic_val.strip():
        try:
            magic_out = int(magic_val)
        except ValueError:
            magic_out = magic_val

    slot_val = data.get("slot")
    slot_out = slot_val.strip() if isinstance(slot_val, str) and slot_val.strip() else None

    halt_reason = data.get("halt_reason")
    halt_reason_out = halt_reason if isinstance(halt_reason, str) and halt_reason else None

    cap_a_name = data.get("cap_leg_a_name")
    cap_b_name = data.get("cap_leg_b_name")

    long_side = _grind_pending_side_fields(data, "long")
    short_side = _grind_pending_side_fields(data, "short")

    return {
        "instance_id": instance_id,
        "connection": "live",
        "slot": slot_out,
        "open_layers_long": _int_or_none("open_layers_long"),
        "open_layers_short": _int_or_none("open_layers_short"),
        "fills": _int_or_none("fills"),
        "scalps": _int_or_none("scalps"),
        "api_count": _int_or_none("api_count"),
        "api_counter_broken": _grind_bool(data.get("api_counter_broken")),
        "cap_blocked": _grind_bool(data.get("cap_blocked")),
        "halted": _grind_bool(data.get("halted")),
        "halt_reason": halt_reason_out,
        "recon_ok": _grind_bool(data.get("recon_ok")),
        "invariant_ok": _grind_bool(data.get("invariant_ok")),
        "cap_leg_a": _float_or_none("cap_leg_a"),
        "cap_leg_b": _float_or_none("cap_leg_b"),
        "cap_total_leg_a": _float_or_none("cap_total_leg_a"),
        "cap_total_leg_b": _float_or_none("cap_total_leg_b"),
        "peer_read_failed": _grind_bool(data.get("peer_read_failed")),
        "magic": magic_out,
        "width_pips": _float_or_none("width_pips"),
        "add_pips": _float_or_none("add_pips"),
        "exit_pips": _float_or_none("exit_pips"),
        "max_layers": _int_or_none("max_layers"),
        "cap_leg_a_name": cap_a_name if isinstance(cap_a_name, str) and cap_a_name else None,
        "cap_leg_b_name": cap_b_name if isinstance(cap_b_name, str) and cap_b_name else None,
        "net_mtm": _money_or_none("net_mtm"),
        "realised_pnl_today": _money_or_none("realised_pnl_today"),
        "scalp_pnl_last": _money_or_none("scalp_pnl_last"),
        "exit_penetration_pips_last": _float_or_none("exit_penetration_pips_last"),
        "exit_penetration_pips_mean": _float_or_none("exit_penetration_pips_mean"),
        "exit_touch_revert_count": _int_or_none("exit_touch_revert_count"),
        "layers": _grind_layers_from_payload(data),
        "book": _grind_book_from_payload(data),
        "account_balance": _money_or_none("account_balance"),
        "account_equity": _money_or_none("account_equity"),
        **long_side,
        **short_side,
    }


def _grind_pnl_contribution(value):
    """Null-safe P&L addend — missing fields become 0.0, never NaN."""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _summarize_grind_arm(group_label, instances, grind_cards):
    """Aggregate operator-facing totals for one grind variant (Arm A / Arm B)."""
    open_long = 0
    open_short = 0
    fills_total = 0
    scalps_total = 0
    # MAX not SUM: GRIND_DAILY_API_COUNT (ea/grind_api_counter.mqh) is one shared
    # GlobalVariable incremented by all grind instances; each heartbeat reports
    # the same family-wide count against the 2,000 FTMO limit.
    api_count_max = 0
    net_mtm_total = 0.0
    realised_today_total = 0.0
    instances_live = 0
    halted_instances = []

    for inst in instances:
        card = grind_cards.get(inst) or {}
        if card.get("connection") != "live":
            continue

        instances_live += 1
        open_long += card.get("open_layers_long") or 0
        open_short += card.get("open_layers_short") or 0
        fills_total += card.get("fills") or 0
        scalps_total += card.get("scalps") or 0

        net_mtm_total += _grind_pnl_contribution(card.get("net_mtm"))
        realised_today_total += _grind_pnl_contribution(card.get("realised_pnl_today"))

        api_val = card.get("api_count")
        if isinstance(api_val, (int, float)):
            api_count_max = max(api_count_max, int(api_val))

        if card.get("halted"):
            halted_instances.append({
                "instance_id": inst,
                "halt_reason": card.get("halt_reason") or "",
            })

    if instances_live == 0:
        status = "no_data"
        status_label = f"{group_label}: NO DATA"
    elif instances_live == len(instances):
        status = "running"
        status_label = f"{group_label}: RUNNING"
    else:
        status = "degraded"
        status_label = f"{group_label}: DEGRADED"

    return {
        "group": group_label,
        "status": status,
        "status_label": status_label,
        "status_detail": f"{instances_live}/{len(instances)} instances live",
        "open_layers_long": open_long,
        "open_layers_short": open_short,
        "fills": fills_total,
        "scalps": scalps_total,
        "net_mtm": round(net_mtm_total, 2) if instances_live > 0 else None,
        "realised_pnl_today": round(realised_today_total, 2) if instances_live > 0 else None,
        "api_count": api_count_max if instances_live > 0 else None,
        "api_count_limit": GRIND_API_DAILY_LIMIT,
        "instances_live": instances_live,
        "instances_total": len(instances),
        "halted_instances": halted_instances,
    }


_PUBLIC_GRIND_INSTANCE_KEYS = (
    "instance_id",
    "slot",
    "connection",
    "open_layers_long",
    "open_layers_short",
    "scalps",
    "net_mtm",
    "realised_pnl_today",
    "scalp_pnl_last",
    "halted",
    "halt_reason",
    "recon_ok",
    "invariant_ok",
    "cap_blocked",
    "peer_read_failed",
    "api_count",
    "width_pips",
    "add_pips",
    "exit_pips",
    "max_layers",
    "cap_leg_a_name",
    "cap_leg_b_name",
    "exit_penetration_pips_mean",
    "exit_touch_revert_count",
    "layers",
    "l0_pending_long",
    "l0_pending_short",
    "add_pending_long",
    "add_pending_short",
    "resting_entries_long",
    "resting_entries_short",
    "magic",
    "book",
)


def _public_grind_instance_fields(card):
    """Whitelist grind instance fields safe for the unauthenticated status route."""
    return {key: card.get(key) for key in _PUBLIC_GRIND_INSTANCE_KEYS}


_PUBLIC_GRIND_ARM_KEYS = (
    "group",
    "status",
    "status_label",
    "status_detail",
    "open_layers_long",
    "open_layers_short",
    "fills",
    "scalps",
    "net_mtm",
    "realised_pnl_today",
    "api_count",
    "instances_live",
    "instances_total",
)


def _public_grind_arm_fields(arm):
    """Whitelist grind arm aggregate fields safe for the unauthenticated status route."""
    out = {key: arm.get(key) for key in _PUBLIC_GRIND_ARM_KEYS}
    halted = arm.get("halted_instances") or []
    out["halted_instances"] = [
        {
            "instance_id": item.get("instance_id"),
            "halt_reason": item.get("halt_reason"),
        }
        for item in halted
        if isinstance(item, dict)
    ]
    return out


def _build_grind_ring_summaries(grind_cards):
    """Per-ring Arm A / Arm B summaries — never pooled across rings."""
    rings = {}
    for ring_id, ring_meta in GRIND_RINGS.items():
        ring_instances = _grind_instances_for_ring(ring_id)
        opt_instances = [inst for inst in ring_instances if _grind_slot(inst) == "OPT"]
        alt_instances = [inst for inst in ring_instances if _grind_slot(inst) == "ALT"]
        rings[ring_id] = {
            "label": ring_meta["label"],
            "symbols": list(ring_meta["symbols"]),
            "instances": ring_instances,
            "arm_summaries": {
                "opt": _summarize_grind_arm("Arm A", opt_instances, grind_cards),
                "alt": _summarize_grind_arm("Arm B", alt_instances, grind_cards),
            },
        }
    return rings


_PUBLIC_SCALP_KEYS = (
    "close_time",
    "instrument",
    "direction",
    "entry_price",
    "exit_price",
    "layer_depth",
    "stack_depth",
    "gross_pnl",
    "instance_id",
    "rolled",
    "ejected",
)


def _scalp_excluded_from_counts(record):
    return record.get("ejected") is True or record.get("rolled") is True


def _public_scalp_fields(record):
    """Whitelist scalp exit fields safe for the unauthenticated scalps route."""
    return {key: record.get(key) for key in _PUBLIC_SCALP_KEYS}


def _collect_today_scalp_records(selected_date=None, instances=None):
    """Cross-instance scalp exits for one broker calendar date (this host's
    instances unless a list is given)."""
    broker_today = _broker_today()
    date = selected_date or broker_today
    all_records = []

    for inst in (GRIND_INSTANCES if instances is None else instances):
        raw_list = r.lrange(f"fxmatrix:scalp_history:{inst}", 0, -1)
        records = [json.loads(item) for item in raw_list]
        day_records = [
            record
            for record in records
            if _closed_record_date(record) == date
        ]
        for record in day_records:
            merged = dict(record)
            merged["instance_id"] = inst
            all_records.append(merged)

    all_records.sort(key=lambda item: item.get("close_time", ""))
    return date, all_records


def _count_scalp_records_for_summary(records):
    return sum(1 for record in records if not _scalp_excluded_from_counts(record))


def _collect_scalp_records_between(start_date, end_date, instances=None):
    """Cross-instance scalp exits for an inclusive broker-date range."""
    all_records = []

    for inst in (GRIND_INSTANCES if instances is None else instances):
        raw_list = r.lrange(f"fxmatrix:scalp_history:{inst}", 0, -1)
        records = [json.loads(item) for item in raw_list]
        range_records = [
            record
            for record in records
            if (rec_date := _closed_record_date(record))
            and start_date <= rec_date <= end_date
        ]
        for record in range_records:
            merged = dict(record)
            merged["instance_id"] = inst
            all_records.append(merged)

    all_records.sort(key=lambda item: item.get("close_time", ""))
    return all_records


def _parse_broker_date(date_str):
    """Validate YYYY-MM-DD broker date string."""
    if not isinstance(date_str, str) or not date_str:
        return None
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
    return date_str


def _format_broker_date_label(date_str):
    """Human-readable broker calendar date, e.g. Sat 12 Sep 2026."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%a %d %b %Y")


def _pip_multiplier_for_prices(*prices):
    """Return 10000 for 5-digit symbols, 100 when price implies 3-digit."""
    for price in prices:
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            if float(price) > 50:
                return 100
    return 10000


# Commission per closed layer (two IN deals), measured on the broker ledger
# 26-28 Sep (639 IN deals): FTMO 0.03 + 0.03, IC Markets 0.04 + 0.04.
# An account not listed here is reported as unknown, never guessed.
COMMISSION_PER_CLOSE_BY_ACCOUNT = {
    1514731800: 0.06,   # FTMO cycle 3
    53066709: 0.08,     # IC Fleet B (box 1)
    53071896: 0.08,     # IC Fleet C (box 2)
}


def _scalp_signed_pips(record):
    """Pips won (+) or lost (-) by one closed layer, from its direction."""
    entry = record.get("entry_price")
    exit_price = record.get("exit_price")
    if not isinstance(entry, (int, float)) or not isinstance(exit_price, (int, float)):
        return None
    if isinstance(entry, bool) or isinstance(exit_price, bool):
        return None
    direction = str(record.get("direction") or "").upper()
    if direction == "LONG":
        move = float(exit_price) - float(entry)
    elif direction == "SHORT":
        move = float(entry) - float(exit_price)
    else:
        return None
    return move * _pip_multiplier_for_prices(entry, exit_price)


def _commission_for_records(records):
    """(total USD as a negative number, or None if any account is unknown;
    count of records whose account has no known rate)."""
    total = 0.0
    unknown = 0
    for record in records:
        login = record.get("account_login")
        try:
            rate = COMMISSION_PER_CLOSE_BY_ACCOUNT.get(int(login)) if login is not None else None
        except (TypeError, ValueError):
            rate = None
        if rate is None:
            unknown += 1
        else:
            total -= rate
    return (None if unknown else round(total, 2)), unknown


def _scalp_gross_pips(record):
    """Absolute pip distance for one scalp exit."""
    entry = record.get("entry_price")
    exit_price = record.get("exit_price")
    if not isinstance(entry, (int, float)) or not isinstance(exit_price, (int, float)):
        return None
    if isinstance(entry, bool) or isinstance(exit_price, bool):
        return None
    mult = _pip_multiplier_for_prices(entry, exit_price)
    return abs(float(exit_price) - float(entry)) * mult


def _fmt_signed(value, decimals):
    """Format a number with explicit + or - sign."""
    return f"{value:+.{decimals}f}"


def _fmt_money(value, signed=True):
    """Format USD with thousands separators; optional explicit sign."""
    amount = abs(float(value))
    text = f"{amount:,.2f}"
    if not signed:
        return text
    if float(value) >= 0:
        return f"+{text}"
    return f"-{text}"


def _cycle_day_number(start_date_str, selected_date_str, broker_today_str):
    """Weekday-based cycle day count for the selected broker date."""
    start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    selected = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
    broker_today = datetime.strptime(broker_today_str, "%Y-%m-%d").date()
    count = 0
    day = start
    while day <= selected:
        if day.weekday() < 5:
            count += 1
        day += timedelta(days=1)
    if selected.weekday() < 5 and selected == broker_today:
        count -= 1
    return max(count, 1)


def _scalp_usd_gross(records):
    """Sum gross USD from scalp records."""
    total = 0.0
    for record in records:
        usd = record.get("gross_pnl")
        if isinstance(usd, (int, float)) and not isinstance(usd, bool):
            total += float(usd)
    return total


def _fmt_deepest_side(deepest):
    n, sym, side = deepest
    if not n:
        return "0"
    return f"{n} ({sym} {side})"


def _collect_open_book_stats():
    """Open position count, pair count, deepest stack, and MTM from heartbeat book."""
    position_count = 0
    symbols_with_positions = set()
    deepest_stack = 0
    deepest_side = (0, None, None)          # (layers, symbol, "L"/"S")
    open_mtm = 0.0
    has_mtm = False

    for inst in GRIND_INSTANCES:
        raw = r.get(f"fxmatrix:state:{inst}")
        if raw is None:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

        open_long = data.get("open_layers_long")
        open_short = data.get("open_layers_short")
        if isinstance(open_long, (int, float)) and not isinstance(open_long, bool):
            if isinstance(open_short, (int, float)) and not isinstance(open_short, bool):
                stack = int(open_long) + int(open_short)
                deepest_stack = max(deepest_stack, stack)
                sym = inst.split("_")[1] if "_" in inst else inst
                for n_side, side in ((int(open_long), "L"), (int(open_short), "S")):
                    if n_side > deepest_side[0]:
                        deepest_side = (n_side, sym, side)

        book = data.get("book")
        if not isinstance(book, dict):
            continue
        positions = book.get("positions")
        if not isinstance(positions, list):
            continue

        symbol = inst.split("_")[1] if "_" in inst else inst
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            position_count += 1
            symbols_with_positions.add(symbol)
            profit = pos.get("profit")
            if isinstance(profit, (int, float)) and not isinstance(profit, bool):
                open_mtm += float(profit)
                has_mtm = True

    return {
        "position_count": position_count,
        "pair_count": len(symbols_with_positions),
        "deepest_stack": deepest_stack,
        "deepest_side": deepest_side,
        "open_mtm": round(open_mtm, 2) if has_mtm else 0.0,
    }


def _summary_kind(record):
    if record.get("rolled") is True:
        return "rolls"
    if record.get("ejected") is True:
        return "ejections"
    return "scalps"


def _summary_data(records):
    """The daily summary's numbers for a set of closed-layer records: one
    source for the text summary and the fleet cards. Pips are signed; money
    includes every close; counts keep scalps apart from ejections and rolls;
    commission by account (None when any account's rate is unknown)."""
    kinds = {k: {"count": 0, "pips": 0.0, "usd": 0.0, "pips_unknown": 0}
             for k in ("scalps", "ejections", "rolls")}
    by_symbol = {}
    for record in records:
        kind = _summary_kind(record)
        pips = _scalp_signed_pips(record)
        usd = record.get("gross_pnl")
        usd_ok = isinstance(usd, (int, float)) and not isinstance(usd, bool)
        k = kinds[kind]
        k["count"] += 1
        if pips is None:
            k["pips_unknown"] += 1
        else:
            k["pips"] += pips
        if usd_ok:
            k["usd"] += float(usd)
        pair = record.get("instrument") or "?"
        b = by_symbol.setdefault(pair, {"pair": pair, "scalps": 0, "ejections": 0,
                                        "rolls": 0, "pips": 0.0, "usd": 0.0})
        b[kind] += 1
        if pips is not None:
            b["pips"] += pips
        if usd_ok:
            b["usd"] += float(usd)
    commission, comm_unknown = _commission_for_records(records)
    net_pips = sum(k["pips"] for k in kinds.values())
    usd_before = sum(k["usd"] for k in kinds.values())
    for k in kinds.values():
        k["pips"] = round(k["pips"], 1)
        k["usd"] = round(k["usd"], 2)
    pairs = []
    for b in by_symbol.values():
        b["pips"] = round(b["pips"], 1)
        b["usd"] = round(b["usd"], 2)
        pairs.append(b)
    pairs.sort(key=lambda b: (-b["usd"], b["pair"]))
    return {
        "scalps": kinds["scalps"],
        "ejections": kinds["ejections"],
        "rolls": kinds["rolls"],
        "closes": len(records),
        "usd_before_commission": round(usd_before, 2),
        "commission": commission,
        "commission_unknown": comm_unknown,
        "net_pips": round(net_pips, 1),
        "net_usd": (round(usd_before + commission, 2) if commission is not None else None),
        "by_pair": pairs,
    }


def _summary_cycle(cycle_all, cycle_start, date, broker_today):
    """Cycle totals since cycle_start (same rules as the day)."""
    scalps = [r for r in cycle_all if not _scalp_excluded_from_counts(r)]
    gross = _scalp_usd_gross(cycle_all)
    commission, unknown = _commission_for_records(cycle_all)
    truncated = bool(scalps) and min(_closed_record_date(r) for r in scalps) > cycle_start
    return {
        "start": cycle_start,
        "day": _cycle_day_number(cycle_start, date, broker_today),
        "scalps": len(scalps),
        "usd_before_commission": round(gross, 2),
        "commission": commission,
        "commission_unknown": unknown,
        "closes": len(cycle_all),
        "net_usd": (round(gross + commission, 2) if commission is not None else None),
        "rolls": sum(1 for r in cycle_all if r.get("rolled") is True),
        "ejections": sum(1 for r in cycle_all if r.get("ejected") is True),
        "truncated": truncated,
    }


def _build_daily_summary_text(selected_date=None):
    """Plain-text broker-day summary for copy/paste."""
    broker_today = _broker_today()
    date = selected_date or broker_today
    is_historical = date != broker_today
    live_suffix = " (live, not historical)" if is_historical else ""
    header_tag = "(historical)" if is_historical else "(today)"

    _, scalps = _collect_today_scalp_records(date)
    metrics = _read_global_account_metrics()
    book_stats = _collect_open_book_stats()

    lines = [
        f"FXGRIND -- {_format_broker_date_label(date)}            {header_tag}",
        "",
    ]

    equity = metrics.get("equity") if metrics else None
    balance = metrics.get("balance") if metrics else None
    if equity is not None and balance is not None:
        lines.append(
            f"Account      Equity {_fmt_money(equity, signed=False)}   "
            f"Balance {_fmt_money(balance, signed=False)} USD{live_suffix}"
        )
    else:
        lines.append(f"Account      n/a{live_suffix}")

    lines.append(
        f"Open risk    {book_stats['position_count']} positions, "
        f"{book_stats['pair_count']} pairs, deepest side "
        f"{_fmt_deepest_side(book_stats['deepest_side'])}{live_suffix}"
    )

    open_mtm = book_stats["open_mtm"]
    if equity is not None and balance is not None:
        financing = round((equity - balance) - open_mtm, 2)
        financing_str = _fmt_money(financing)
    else:
        financing_str = "n/a"
    lines.append(
        f"Open MTM     {_fmt_money(open_mtm)} USD{live_suffix}         "
        f"Financing accrued {financing_str} USD{live_suffix}"
    )
    lines.append("")

    if not scalps:
        lines.append("Scalps       none closed")
    else:
        d = _summary_data(scalps)
        sk, ek, rk = d["scalps"], d["ejections"], d["rolls"]
        lines.append(
            f"Scalps     {sk['count']:>4} closed   {_fmt_signed(sk['pips'], 1):>9} pips  "
            f"{_fmt_money(sk['usd']):>10} USD"
        )
        lines.append(
            f"Ejections  {ek['count']:>4}          {_fmt_signed(ek['pips'], 1):>9} pips  "
            f"{_fmt_money(ek['usd']):>10} USD"
        )
        lines.append(
            f"Rolls      {rk['count']:>4}          {_fmt_signed(rk['pips'], 1):>9} pips  "
            f"{_fmt_money(rk['usd']):>10} USD"
        )
        if d["commission"] is None:
            lines.append(
                f"Commission {d['closes']:>4} closes   unknown ({d['commission_unknown']} of "
                f"{d['closes']} closes on an account with no known rate)"
            )
            lines.append(
                f"Net                      {_fmt_signed(d['net_pips'], 1):>9} pips   n/a (commission unknown)"
            )
        else:
            lines.append(
                f"Commission {d['closes']:>4} closes                   "
                f"{_fmt_money(d['commission']):>10} USD"
            )
            lines.append(
                f"Net                      {_fmt_signed(d['net_pips'], 1):>9} pips  "
                f"{_fmt_money(d['net_usd']):>10} USD"
            )
        unknown_pips = sk["pips_unknown"] + ek["pips_unknown"] + rk["pips_unknown"]
        if unknown_pips:
            lines.append(f"             ({unknown_pips} closes without a direction: pips not counted)")
        lines.append("")

        for bucket in d["by_pair"]:
            parts = [f"{bucket['scalps']} {'scalp' if bucket['scalps'] == 1 else 'scalps'}"]
            if bucket["ejections"]:
                parts.append(f"{bucket['ejections']} {'ejection' if bucket['ejections'] == 1 else 'ejections'}")
            if bucket["rolls"]:
                parts.append(f"{bucket['rolls']} {'roll' if bucket['rolls'] == 1 else 'rolls'}")
            lines.append(
                f"  {bucket['pair']:<6} {', '.join(parts)}   "
                f"{_fmt_signed(bucket['pips'], 1)} pips   "
                f"{_fmt_money(bucket['usd'])} USD"
            )
        lines.append("")

    cycle_start = CYCLE_START_DATE or DEFAULT_CYCLE_START_DATE
    cyc = _summary_cycle(_collect_scalp_records_between(cycle_start, date),
                         cycle_start, date, broker_today)
    truncated = " (history truncated)" if cyc["truncated"] else ""
    lines.append(
        f"Cycle        day {cyc['day']} (since {_format_broker_date_label(cycle_start)})"
        f"{truncated}"
    )
    if cyc["commission"] is None:
        lines.append(
            f"             {cyc['scalps']} scalps, {_fmt_money(cyc['usd_before_commission'])} USD before "
            f"commission, commission unknown ({cyc['commission_unknown']} of {cyc['closes']} closes)"
        )
    else:
        lines.append(
            f"             {cyc['scalps']} scalps, {_fmt_money(cyc['usd_before_commission'])} USD before "
            f"commission, {_fmt_money(cyc['commission'])} commission, "
            f"{_fmt_money(cyc['net_usd'])} net"
        )
    lines.append(
        f"             rolls {cyc['rolls']}, ejections {cyc['ejections']}"
    )

    return "\n".join(lines) + "\n"


def _parse_grind_comment(comment):
    """Parse GRIND|slot|L|S|Lnn|ENT|EXT order comments."""
    if not isinstance(comment, str):
        return None
    parts = comment.split("|")
    if len(parts) < 5 or parts[0] != "GRIND":
        return None
    side = parts[2]
    if side not in ("L", "S"):
        return None
    role_tag = parts[4]
    if role_tag not in ("ENT", "EXT"):
        return None
    layer_token = parts[3]
    if not layer_token.startswith("L"):
        return None
    try:
        layer = int(layer_token[1:])
    except ValueError:
        return None
    return {
        "slot": parts[1],
        "side": side,
        "layer": layer,
        "role": role_tag,
    }


def _pip_size_from_carry_row(carry_row, ref_price=None):
    """Pip size in price units from carry-table digits or price heuristic."""
    if isinstance(carry_row, dict) and carry_row.get("digits") is not None:
        digits = carry_row["digits"]
        if isinstance(digits, (int, float)) and not isinstance(digits, bool):
            return 10 ** (-(int(digits) - 1))
    if isinstance(ref_price, (int, float)) and not isinstance(ref_price, bool):
        if float(ref_price) > 50:
            return 0.01
    return 0.0001


def _read_carry_rows_by_symbol():
    """Load carry table rows indexed by symbol."""
    raw = r.get(ARCHIVE_CARRY_KEY)
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return {}
    out = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = row.get("symbol")
        if isinstance(symbol, str) and symbol:
            out[symbol] = row
    return out


def _build_carry_audit_rows():
    """Working orders with tonight's carry-adjusted prices (independent of EA projection)."""
    carry_by_symbol = _read_carry_rows_by_symbol()
    rows = []

    for inst in GRIND_INSTANCES:
        raw = r.get(f"fxmatrix:state:{inst}")
        if raw is None:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

        book = data.get("book")
        if not isinstance(book, dict):
            continue
        orders = book.get("orders")
        if not isinstance(orders, list):
            continue

        symbol = inst.split("_")[1] if "_" in inst else inst
        carry_row = carry_by_symbol.get(symbol)

        for order in orders:
            if not isinstance(order, dict):
                continue
            price_now = order.get("price")
            if not isinstance(price_now, (int, float)) or isinstance(price_now, bool):
                continue
            price_now = round(float(price_now), 5)

            parsed = _parse_grind_comment(order.get("comment"))
            row = {
                "instance": inst,
                "side": parsed["side"] if parsed else None,
                "layer": parsed["layer"] if parsed else None,
                "role": parsed["role"] if parsed else None,
                "type": order.get("type"),
                "price_now": price_now,
                "carry_pips": None,
                "pip_size": None,
                "price_tonight": price_now,
                "changed": False,
                "why": "unparsed comment",
            }

            if parsed is None:
                rows.append(row)
                continue

            if carry_row is None:
                row["why"] = "no carry data"
                rows.append(row)
                continue

            pip_size = _pip_size_from_carry_row(carry_row, price_now)
            row["pip_size"] = pip_size

            if parsed["role"] == "ENT":
                row["why"] = "entry order -- carry applies to inventory, not unfilled quotes"
                rows.append(row)
                continue

            side = parsed["side"]
            carry_pips = carry_row.get("long_pips") if side == "L" else carry_row.get("short_pips")
            if not isinstance(carry_pips, (int, float)) or isinstance(carry_pips, bool):
                row["why"] = "no carry data"
                rows.append(row)
                continue

            carry_pips = float(carry_pips)
            direction = 1 if side == "L" else -1
            price_tonight = round(price_now - direction * carry_pips * pip_size, 5)

            row["carry_pips"] = carry_pips
            row["price_tonight"] = price_tonight
            row["changed"] = True
            row["why"] = "carry applied"
            rows.append(row)

    rows.sort(key=lambda item: (
        item.get("instance") or "",
        item.get("side") or "",
        item.get("layer") if item.get("layer") is not None else -1,
    ))
    return rows


def _apply_no_cache_headers(response):
    """Block browser, proxy, and CDN caching for dynamic unauthenticated responses.

    Cloudflare may cache JSON GET responses when a Cache Rule sets Edge TTL
    while ignoring origin Cache-Control. Cloudflare-CDN-Cache-Control is evaluated
    separately and prevents that override (see Cloudflare CDN-Cache-Control docs).
    """
    response.cache_control.no_store = True
    response.cache_control.no_cache = True
    response.cache_control.must_revalidate = True
    response.cache_control.max_age = 0
    response.cache_control.private = True
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["CDN-Cache-Control"] = "no-store"
    response.headers["Cloudflare-CDN-Cache-Control"] = "no-store"
    response.headers["Surrogate-Control"] = "no-store"
    response.headers["Vary"] = "*"
    return response


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route(
    "/api/g/<token>/status",
    methods=["GET"],
    defaults={"_ignored": None},
    strict_slashes=False,
)
@app.route(
    "/api/g/<token>/status/<path:_ignored>",
    methods=["GET"],
    strict_slashes=False,
)
def public_grind_status(token, _ignored):
    if token != PUBLIC_GRIND_STATUS_TOKEN:
        return jsonify({"error": "not found"}), 404

    try:
        grind_cards = {}
        for inst in GRIND_INSTANCES:
            raw_grind = r.get(f"fxmatrix:state:{inst}")
            grind_cards[inst] = _summarize_grind_instance_state(inst, raw_grind)

        grind_rings = _build_grind_ring_summaries(grind_cards)

        payload = {
            "generated_at": datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "instances": {
                inst: _public_grind_instance_fields(grind_cards[inst])
                for inst in GRIND_INSTANCES
            },
            "rings": {
                ring_id: {
                    "label": ring["label"],
                    "symbols": ring["symbols"],
                    "instances": ring["instances"],
                    "arms": {
                        "opt": _public_grind_arm_fields(ring["arm_summaries"]["opt"]),
                        "alt": _public_grind_arm_fields(ring["arm_summaries"]["alt"]),
                    },
                }
                for ring_id, ring in grind_rings.items()
            },
        }
        response = jsonify(payload)
        return _apply_no_cache_headers(response), 200
    except Exception:
        app.logger.exception("public_grind_status failed")
        response = jsonify({"error": "internal error"})
        return _apply_no_cache_headers(response), 500


def _fleet_status_response(fleet_letter, instances, log_name):
    try:
        grind_cards = {}
        raw_by_inst = {}
        for inst in instances:
            raw_grind = r.get(f"fxmatrix:state:{inst}")
            raw_by_inst[inst] = raw_grind
            grind_cards[inst] = _summarize_grind_instance_state(inst, raw_grind)

        payload = {
            "generated_at": datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fleet": fleet_letter,
            "instances": {
                inst: _public_grind_instance_fields(grind_cards[inst])
                for inst in instances
            },
            "summary": _fleet_summary(grind_cards, raw_by_inst, instances),
        }
        response = jsonify(payload)
        return _apply_no_cache_headers(response), 200
    except Exception:
        app.logger.exception("%s failed", log_name)
        response = jsonify({"error": "internal error"})
        return _apply_no_cache_headers(response), 500


@app.route(
    "/api/g/<token>/status_b",
    methods=["GET"],
    defaults={"_ignored": None},
    strict_slashes=False,
)
@app.route(
    "/api/g/<token>/status_b/<path:_ignored>",
    methods=["GET"],
    strict_slashes=False,
)
def public_grind_status_b(token, _ignored):
    if token != PUBLIC_GRIND_STATUS_TOKEN:
        return jsonify({"error": "not found"}), 404
    return _fleet_status_response("B", GRIND_B_INSTANCES, "public_grind_status_b")


@app.route(
    "/api/g/<token>/status_c",
    methods=["GET"],
    defaults={"_ignored": None},
    strict_slashes=False,
)
@app.route(
    "/api/g/<token>/status_c/<path:_ignored>",
    methods=["GET"],
    strict_slashes=False,
)
def public_grind_status_c(token, _ignored):
    if token != PUBLIC_GRIND_STATUS_TOKEN:
        return jsonify({"error": "not found"}), 404
    return _fleet_status_response("C", GRIND_C_INSTANCES, "public_grind_status_c")


@app.route(
    "/api/g/<token>/status_d",
    methods=["GET"],
    defaults={"_ignored": None},
    strict_slashes=False,
)
@app.route(
    "/api/g/<token>/status_d/<path:_ignored>",
    methods=["GET"],
    strict_slashes=False,
)
def public_grind_status_d(token, _ignored):
    if token != PUBLIC_GRIND_STATUS_TOKEN:
        return jsonify({"error": "not found"}), 404
    return _fleet_status_response("D", GRIND_D_INSTANCES, "public_grind_status_d")


@app.route(
    "/api/g/<token>/fleets",
    methods=["GET"],
    defaults={"_ignored": None},
    strict_slashes=False,
)
@app.route(
    "/api/g/<token>/fleets/<path:_ignored>",
    methods=["GET"],
    strict_slashes=False,
)
def public_fleet_strip(token, _ignored):
    if token != PUBLIC_GRIND_STATUS_TOKEN:
        return jsonify({"error": "not found"}), 404

    try:
        payload = _build_fleet_strip_payload()
        response = jsonify(payload)
        return _apply_no_cache_headers(response), 200
    except Exception:
        app.logger.exception("public_fleet_strip failed")
        response = jsonify({"error": "internal error"})
        return _apply_no_cache_headers(response), 500


@app.route(
    "/api/g/<token>/scalps",
    methods=["GET"],
    defaults={"_ignored": None},
    strict_slashes=False,
)
@app.route(
    "/api/g/<token>/scalps/<path:_ignored>",
    methods=["GET"],
    strict_slashes=False,
)
def public_grind_scalps(token, _ignored):
    if token != PUBLIC_GRIND_STATUS_TOKEN:
        return jsonify({"error": "not found"}), 404

    try:
        date_filter = request.args.get("date")
        selected_date, all_records = _collect_today_scalp_records(date_filter)
        payload = {
            "date": selected_date,
            "total": _count_scalp_records_for_summary(all_records),
            "records": [_public_scalp_fields(record) for record in all_records],
        }
        response = jsonify(payload)
        return _apply_no_cache_headers(response), 200
    except Exception:
        app.logger.exception("public_grind_scalps failed")
        response = jsonify({"error": "internal error"})
        return _apply_no_cache_headers(response), 500


@app.route(
    "/api/g/<token>/archive",
    methods=["GET"],
    defaults={"_ignored": None},
    strict_slashes=False,
)
@app.route(
    "/api/g/<token>/archive/<path:_ignored>",
    methods=["GET"],
    strict_slashes=False,
)
def public_archive_status(token, _ignored):
    if token != PUBLIC_GRIND_STATUS_TOKEN:
        return jsonify({"error": "not found"}), 404

    try:
        worker_raw = r.get(ARCHIVE_WORKER_KEY)
        worker = json.loads(worker_raw) if worker_raw else None
        payload = {
            "generated_at": datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "worker": worker,
            "queue_len": r.llen(ARCHIVE_QUEUE_KEY),
            "processing_len": r.llen(ARCHIVE_PROCESSING_KEY),
            "deadletter_len": r.llen(ARCHIVE_DEADLETTER_KEY),
        }
        response = jsonify(payload)
        return _apply_no_cache_headers(response), 200
    except Exception:
        app.logger.exception("public_archive_status failed")
        response = jsonify({"error": "internal error"})
        return _apply_no_cache_headers(response), 500


@app.route(
    "/api/g/<token>/carry",
    methods=["GET"],
    defaults={"_ignored": None},
    strict_slashes=False,
)
@app.route(
    "/api/g/<token>/carry/<path:_ignored>",
    methods=["GET"],
    strict_slashes=False,
)
def public_carry_table(token, _ignored):
    if token != PUBLIC_GRIND_STATUS_TOKEN:
        return jsonify({"error": "not found"}), 404

    try:
        raw = r.get(ARCHIVE_CARRY_KEY)
        if raw:
            payload = json.loads(raw)
        else:
            payload = {"generated_at": None, "rows": []}
        response = jsonify(payload)
        return _apply_no_cache_headers(response), 200
    except Exception:
        app.logger.exception("public_carry_table failed")
        response = jsonify({"error": "internal error"})
        return _apply_no_cache_headers(response), 500


@app.route(
    "/api/g/<token>/daily",
    methods=["GET"],
    defaults={"_ignored": None},
    strict_slashes=False,
)
@app.route(
    "/api/g/<token>/daily/<path:_ignored>",
    methods=["GET"],
    strict_slashes=False,
)
def public_daily_table(token, _ignored):
    if token != PUBLIC_GRIND_STATUS_TOKEN:
        return jsonify({"error": "not found"}), 404

    try:
        raw = r.get(ARCHIVE_DAILY_KEY)
        if raw:
            payload = json.loads(raw)
        else:
            payload = {"generated_at": None, "rows": []}
        response = jsonify(payload)
        return _apply_no_cache_headers(response), 200
    except Exception:
        app.logger.exception("public_daily_table failed")
        response = jsonify({"error": "internal error"})
        return _apply_no_cache_headers(response), 500


def _critical_mark_resolved(payload):
    """Add "resolved": true to each halt-code CRITICAL row whose instance is
    live, not halted and invariant_ok true now (same rule as the fleet
    strip: a halt clears only on an EA restart). Works on the parsed copy;
    the Redis payload is never written."""
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return
    cache = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("level") != "CRITICAL" or row.get("code") not in _FLEET_STRIP_HALT_CODES:
            continue
        inst = row.get("instance_id")
        if not inst:
            continue
        if inst not in cache:
            card = _summarize_grind_instance_state(inst, r.get(f"fxmatrix:state:{inst}"))
            # a card without a heartbeat has invariant_ok None, so "live" is implied
            cache[inst] = (card.get("halted") is not True
                           and card.get("invariant_ok") is True)
        if cache[inst]:
            row["resolved"] = True


@app.route(
    "/api/g/<token>/critical",
    methods=["GET"],
    defaults={"_ignored": None},
    strict_slashes=False,
)
@app.route(
    "/api/g/<token>/critical/<path:_ignored>",
    methods=["GET"],
    strict_slashes=False,
)
def public_critical_list(token, _ignored):
    if token != PUBLIC_GRIND_STATUS_TOKEN:
        return jsonify({"error": "not found"}), 404

    try:
        raw = r.get(ARCHIVE_CRITICAL_KEY)
        if raw:
            payload = json.loads(raw)
        else:
            payload = {"generated_at": None, "rows": []}
        _critical_mark_resolved(payload)
        response = jsonify(payload)
        return _apply_no_cache_headers(response), 200
    except Exception:
        app.logger.exception("public_critical_list failed")
        response = jsonify({"error": "internal error"})
        return _apply_no_cache_headers(response), 500


@app.route(
    "/api/g/<token>/summary",
    methods=["GET"],
    defaults={"_ignored": None},
    strict_slashes=False,
)
@app.route(
    "/api/g/<token>/summary/<path:_ignored>",
    methods=["GET"],
    strict_slashes=False,
)
def public_daily_summary(token, _ignored):
    if token != PUBLIC_GRIND_STATUS_TOKEN:
        return jsonify({"error": "not found"}), 404

    try:
        date_filter = request.args.get("date")
        if date_filter is not None:
            parsed = _parse_broker_date(date_filter)
            if parsed is None:
                response = Response("invalid date\n", mimetype="text/plain")
                return _apply_no_cache_headers(response), 400
            text = _build_daily_summary_text(parsed)
        else:
            text = _build_daily_summary_text()
        response = Response(text, mimetype="text/plain")
        return _apply_no_cache_headers(response), 200
    except Exception:
        app.logger.exception("public_daily_summary failed")
        response = Response("error\n", mimetype="text/plain", status=500)
        return _apply_no_cache_headers(response), 500


@app.route(
    "/api/g/<token>/carry_audit",
    methods=["GET"],
    defaults={"_ignored": None},
    strict_slashes=False,
)
@app.route(
    "/api/g/<token>/carry_audit/<path:_ignored>",
    methods=["GET"],
    strict_slashes=False,
)
def public_carry_audit(token, _ignored):
    if token != PUBLIC_GRIND_STATUS_TOKEN:
        return jsonify({"error": "not found"}), 404

    try:
        payload = {
            "generated_at": datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "rows": _build_carry_audit_rows(),
        }
        response = jsonify(payload)
        return _apply_no_cache_headers(response), 200
    except Exception:
        app.logger.exception("public_carry_audit failed")
        response = jsonify({"error": "internal error"})
        return _apply_no_cache_headers(response), 500


@app.route(
    "/api/g/<token>/ejection",
    methods=["GET"],
    defaults={"_ignored": None},
    strict_slashes=False,
)
@app.route(
    "/api/g/<token>/ejection/<path:_ignored>",
    methods=["GET"],
    strict_slashes=False,
)
def public_ejection_telemetry(token, _ignored):
    if token != PUBLIC_GRIND_STATUS_TOKEN:
        return jsonify({"error": "not found"}), 404

    try:
        import ejection_view as ev

        hours = request.args.get("hours", 48)
        payload, err = ev.serve_ejection_from_redis(
            r,
            hours,
            GRIND_FLEET,
            GRIND_FLEET_LABEL,
            GRIND_INSTANCES,
        )
        if err is not None:
            response = jsonify(err)
            return _apply_no_cache_headers(response), 503
        response = jsonify(payload)
        return _apply_no_cache_headers(response), 200
    except Exception:
        app.logger.exception("public_ejection_telemetry failed")
        response = jsonify({"error": "internal error"})
        return _apply_no_cache_headers(response), 500


@app.route("/api/telemetry/push", methods=["POST"])
def telemetry_push():
    auth = request.headers.get("Authorization", "")
    if not TELEMETRY_API_KEY or auth != f"Bearer {TELEMETRY_API_KEY}":
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Invalid JSON"}), 400

    instance_id = payload.get("instance_id", "unknown")
    redis_key = f"fxmatrix:state:{instance_id}"
    payload["_received_at"] = _utc_now_iso()

    r.set(redis_key, json.dumps(payload), ex=REDIS_TTL_SECONDS)

    return jsonify({"status": "ok"}), 200


@app.route("/api/telemetry/action", methods=["POST"])
def telemetry_action():
    auth = request.headers.get("Authorization", "")
    if not TELEMETRY_API_KEY or auth != f"Bearer {TELEMETRY_API_KEY}":
        return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json(silent=True)
    error = _validate_archive_action_body(body)
    if error:
        return jsonify({"error": error}), 400

    instance_id = body["instance_id"]
    session_id = body["session_id"]
    received_at = _utc_now_iso()
    queue_items = []
    for event in body["events"]:
        queue_items.append(json.dumps({
            "type": event["type"],
            "instance_id": instance_id,
            "session_id": session_id,
            "received_at": received_at,
            "event": event,
        }))

    try:
        pipe = r.pipeline()
        for item in queue_items:
            pipe.rpush(ARCHIVE_QUEUE_KEY, item)
        pipe.execute()
    except redis.RedisError:
        app.logger.exception("telemetry_action queue failed")
        return jsonify({"error": "queue unavailable"}), 503

    return jsonify({"status": "ok", "queued": len(queue_items)}), 200


@app.route("/api/telemetry/live", methods=["GET"])
def telemetry_live():
    instance_id = request.args.get("instance", GRIND_DEFAULT_INSTANCE)
    redis_key = f"fxmatrix:state:{instance_id}"

    raw = r.get(redis_key)
    intraday_mae = _read_intraday_mae()
    if raw is None:
        return jsonify({
            "status": "connection_lost",
            "instance_id": instance_id,
            "intraday_mae": intraday_mae,
        }), 200

    data = json.loads(raw)
    data["status"] = "live"
    data["intraday_mae"] = intraday_mae
    return jsonify(data), 200


@app.route("/")
def dashboard():
    rings_ctx = {
        ring_id: {
            "label": ring["label"],
            "instances": _grind_instances_for_ring(ring_id),
        }
        for ring_id, ring in GRIND_RINGS.items()
    }
    return render_template(
        "dashboard.html",
        rings=rings_ctx,
        fleet_label=GRIND_FLEET_LABEL,
    )


@app.route("/api/telemetry/pod_closed", methods=["POST"])
def telemetry_pod_closed():
    # Bearer token auth
    auth = request.headers.get("Authorization", "")
    if not TELEMETRY_API_KEY or auth != f"Bearer {TELEMETRY_API_KEY}":
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Invalid JSON"}), 400

    instance_id = payload.get("instance_id", "unknown")
    redis_key = f"fxmatrix:closed_history:{instance_id}"

    # Atomic LPUSH + LTRIM — newest first, capped at 50, 7-day TTL
    pipe = r.pipeline()
    pipe.lpush(redis_key, json.dumps(payload))
    pipe.ltrim(redis_key, 0, 299)  # bumped from 50 -- MM alone hit 99
                                    # closed trades on 2026-06-29
    pipe.expire(redis_key, 604800)  # 7 days
    pipe.execute()

    return jsonify({"status": "ok"}), 200


def _closed_record_date(record):
    trade_date = record.get("trade_date")
    if trade_date:
        return trade_date
    close_time = record.get("close_time", "")
    return close_time[:10] if close_time else ""


def _group_closed_records(records):
    """Merge per-layer close events within 2s on same symbol + direction."""
    sorted_records = sorted(
        records,
        key=lambda item: item.get("close_time", ""),
        reverse=True,
    )
    grouped = []
    used = [False] * len(sorted_records)
    for i, base in enumerate(sorted_records):
        if used[i]:
            continue
        group = [base]
        used[i] = True
        base_time = base.get("close_time")
        base_ms = None
        if base_time:
            try:
                base_ms = int(
                    datetime.fromisoformat(
                        base_time.replace("Z", "+00:00")
                    ).timestamp()
                    * 1000
                )
            except ValueError:
                base_ms = None
        for j in range(i + 1, len(sorted_records)):
            if used[j]:
                continue
            other = sorted_records[j]
            if other.get("instrument") != base.get("instrument"):
                continue
            if other.get("direction") != base.get("direction"):
                continue
            other_time = other.get("close_time")
            if not base_time or not other_time or base_ms is None:
                continue
            try:
                other_ms = int(
                    datetime.fromisoformat(
                        other_time.replace("Z", "+00:00")
                    ).timestamp()
                    * 1000
                )
            except ValueError:
                continue
            if abs(base_ms - other_ms) > 2000:
                continue
            group.append(other)
            used[j] = True
        merged = dict(group[0])
        merged["layers_closed"] = group[0].get("layers_closed") or len(group)
        merged["gross_pnl"] = sum(item.get("gross_pnl") or 0 for item in group)
        merged["avg_entry_price"] = group[0].get("avg_entry_price")
        merged["exit_price"] = group[0].get("exit_price")
        grouped.append(merged)
    return grouped


@app.route("/api/telemetry/closed", methods=["GET"])
def telemetry_closed():
    instance_id = request.args.get("instance", GRIND_DEFAULT_INSTANCE)
    date_filter = request.args.get("date")
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = min(100, max(1, int(request.args.get("per_page", 10))))
    except (TypeError, ValueError):
        per_page = 10

    redis_key = f"fxmatrix:closed_history:{instance_id}"
    raw_list = r.lrange(redis_key, 0, -1)
    records = [json.loads(item) for item in raw_list]

    broker_today = _broker_today()
    available_dates = sorted(
        {date for record in records if (date := _closed_record_date(record))},
        reverse=True,
    )
    if date_filter:
        selected_date = date_filter
    elif broker_today in available_dates:
        selected_date = broker_today
    else:
        selected_date = available_dates[0] if available_dates else broker_today

    day_records = [
        record
        for record in records
        if _closed_record_date(record) == selected_date
    ]

    grouped = _group_closed_records(day_records)
    total = len(grouped)
    total_pages = max(1, (total + per_page - 1) // per_page) if total else 0
    if total_pages:
        page = min(page, total_pages)
        start = (page - 1) * per_page
        page_records = grouped[start : start + per_page]
    else:
        page = 1
        page_records = []

    return jsonify({
        "instance_id": instance_id,
        "records": page_records,
        "date": selected_date,
        "broker_today": broker_today,
        "available_dates": available_dates,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    }), 200


@app.route("/api/telemetry/scalp_closed", methods=["POST"])
def telemetry_scalp_closed():
    auth = request.headers.get("Authorization", "")
    if not TELEMETRY_API_KEY or auth != f"Bearer {TELEMETRY_API_KEY}":
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"error": "Invalid JSON"}), 400

    instance_id = payload.get("instance_id", "unknown")
    redis_key = f"fxmatrix:scalp_history:{instance_id}"

    received_at = _utc_now_iso()
    archive_item = json.dumps({
        "type": "scalp",
        "instance_id": instance_id,
        "session_id": None,
        "received_at": received_at,
        "event": payload,
    })

    pipe = r.pipeline()
    pipe.lpush(redis_key, json.dumps(payload))
    pipe.ltrim(redis_key, 0, SCALP_HISTORY_LIST_MAX)
    pipe.expire(redis_key, SCALP_HISTORY_TTL_SECONDS)
    pipe.rpush(ARCHIVE_QUEUE_KEY, archive_item)
    pipe.execute()

    return jsonify({"status": "ok"}), 200


def _paginate_history_records(records, date_filter, page, per_page, transform=None):
    broker_today = _broker_today()
    available_dates = sorted(
        {date for record in records if (date := _closed_record_date(record))},
        reverse=True,
    )
    if date_filter:
        selected_date = date_filter
    elif broker_today in available_dates:
        selected_date = broker_today
    else:
        selected_date = available_dates[0] if available_dates else broker_today

    day_records = [
        record
        for record in records
        if _closed_record_date(record) == selected_date
    ]

    if transform:
        day_records = transform(day_records)

    total = len(day_records)
    total_pages = max(1, (total + per_page - 1) // per_page) if total else 0
    if total_pages:
        page = min(page, total_pages)
        start = (page - 1) * per_page
        page_records = day_records[start : start + per_page]
    else:
        page = 1
        page_records = []

    return {
        "records": page_records,
        "date": selected_date,
        "broker_today": broker_today,
        "available_dates": available_dates,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    }


@app.route("/api/telemetry/scalps", methods=["GET"])
def telemetry_scalps():
    instance_id = request.args.get("instance", GRIND_DEFAULT_INSTANCE)
    date_filter = request.args.get("date")
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = min(100, max(1, int(request.args.get("per_page", 10))))
    except (TypeError, ValueError):
        per_page = 10

    redis_key = f"fxmatrix:scalp_history:{instance_id}"
    raw_list = r.lrange(redis_key, 0, -1)
    records = [json.loads(item) for item in raw_list]

    def sort_scalps(day_records):
        return sorted(
            day_records,
            key=lambda item: item.get("close_time", ""),
            reverse=True,
        )

    result = _paginate_history_records(
        records, date_filter, page, per_page, transform=sort_scalps
    )
    result["instance_id"] = instance_id
    return jsonify(result), 200


def _collect_closed_history_meta():
    """Scan grind instance closed-history lists — dates, retention, list lengths."""
    all_dates = set()
    per_instance = {}

    for inst in GRIND_INSTANCES:
        raw_list = r.lrange(f"fxmatrix:closed_history:{inst}", 0, -1)
        records = [json.loads(item) for item in raw_list]
        dates = {
            d for rec in records if (d := _closed_record_date(rec))
        }
        all_dates.update(dates)
        per_instance[inst] = {
            "list_length": len(records),
            "earliest_date": min(dates) if dates else None,
            "latest_date": max(dates) if dates else None,
            "date_count": len(dates),
        }

    available_dates = sorted(all_dates, reverse=True)
    earliest_date = min(all_dates) if all_dates else None
    return available_dates, earliest_date, per_instance


def _collect_scalp_history_meta():
    """Scan grind instance scalp lists — dates present, earliest retained, list lengths."""
    all_dates = set()
    per_instance = {}

    for inst in GRIND_INSTANCES:
        raw_list = r.lrange(f"fxmatrix:scalp_history:{inst}", 0, -1)
        records = [json.loads(item) for item in raw_list]
        dates = {
            d for rec in records if (d := _closed_record_date(rec))
        }
        all_dates.update(dates)
        per_instance[inst] = {
            "list_length": len(records),
            "earliest_date": min(dates) if dates else None,
            "latest_date": max(dates) if dates else None,
            "date_count": len(dates),
        }

    available_dates = sorted(all_dates, reverse=True)
    earliest_date = min(all_dates) if all_dates else None
    return available_dates, earliest_date, per_instance


@app.route("/api/telemetry/today_scalps", methods=["GET"])
def telemetry_today_scalps():
    """Cross-instance layer exits (scalp_history) for a broker calendar date."""
    broker_today = _broker_today()
    date_filter = request.args.get("date")
    selected_date, all_records = _collect_today_scalp_records(date_filter)

    available_dates, earliest_date, retention = _collect_scalp_history_meta()

    return jsonify({
        "broker_today": broker_today,
        "date": selected_date,
        "available_dates": available_dates,
        "earliest_date": earliest_date,
        "retention_by_instance": retention,
        "records": all_records,
        "total": _count_scalp_records_for_summary(all_records),
    }), 200


@app.route("/api/telemetry/today_closed", methods=["GET"])
def telemetry_today_closed():
    """Cross-instance pod closes for a broker calendar date (default: today)."""
    broker_today = _broker_today()
    date_filter = request.args.get("date")
    selected_date = date_filter or broker_today

    available_dates, earliest_date, retention = _collect_closed_history_meta()
    all_records = []

    for inst in GRIND_INSTANCES:
        raw_list = r.lrange(f"fxmatrix:closed_history:{inst}", 0, -1)
        records = [json.loads(item) for item in raw_list]
        day_records = [
            record
            for record in records
            if _closed_record_date(record) == selected_date
        ]
        grouped = _group_closed_records(day_records)
        for record in grouped:
            merged = dict(record)
            merged["instance_id"] = inst
            all_records.append(merged)

    all_records.sort(key=lambda item: item.get("close_time", ""))

    return jsonify({
        "broker_today": broker_today,
        "date": selected_date,
        "available_dates": available_dates,
        "earliest_date": earliest_date,
        "retention_by_instance": retention,
        "records": all_records,
        "total": len(all_records),
    }), 200


def _grind_symbol_from_instance_id(instance_id):
    """Derive pair symbol from GRIND_{SYMBOL}_{SLOT} — payload has no symbol field."""
    parts = instance_id.split("_")
    if len(parts) >= 3 and parts[0] == "GRIND":
        return parts[1]
    return None


def _grind_open_layer_count(value):
    """Null-safe layer count for open-position rows — missing fields become 0."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _grind_exposure_symbol(instance_id):
    """Positional split GRIND_SYMBOL_SLOT -> SYMBOL; skip and log if unknown."""
    parts = instance_id.split("_")
    if len(parts) < 3 or parts[0] != "GRIND":
        app.logger.warning(
            "grind net_exposure: skipping %r — expected GRIND_SYMBOL_SLOT", instance_id
        )
        return None
    symbol = parts[1]
    if symbol not in GRIND_KNOWN_SYMBOLS:
        app.logger.warning(
            "grind net_exposure: skipping %r — unknown symbol %r", instance_id, symbol
        )
        return None
    return symbol


def _accumulate_grind_net_exposure(net_exposure, instance_id, data):
    """Add grind signed lots to net_exposure."""
    symbol = _grind_exposure_symbol(instance_id)
    if symbol is None:
        return
    long_count = _grind_open_layer_count(data.get("open_layers_long"))
    short_count = _grind_open_layer_count(data.get("open_layers_short"))
    signed_lots = (long_count - short_count) * GRIND_ASSUMED_LOT_SIZE
    net_exposure[symbol] = net_exposure.get(symbol, 0.0) + signed_lots


@app.route("/api/telemetry/open_positions", methods=["GET"])
def telemetry_open_positions():
    """Cross-instance snapshot of grind instances with open layers."""
    positions = []
    instance_status = {}

    for inst in GRIND_INSTANCES:
        raw = r.get(f"fxmatrix:state:{inst}")
        if raw is None:
            instance_status[inst] = "connection_lost"
            continue

        instance_status[inst] = "live"
        data = json.loads(raw)
        symbol = _grind_symbol_from_instance_id(inst)
        if not symbol:
            continue

        long_count = _grind_open_layer_count(data.get("open_layers_long"))
        short_count = _grind_open_layer_count(data.get("open_layers_short"))
        if long_count <= 0 and short_count <= 0:
            continue

        net_mtm_val = data.get("net_mtm")
        net_mtm = (
            round(float(net_mtm_val), 2)
            if isinstance(net_mtm_val, (int, float)) and not isinstance(net_mtm_val, bool)
            else None
        )
        # net_mtm is per-instance; when both sides are open it cannot be attributed
        # to one direction — show a dash on both rows.
        both_sides = long_count > 0 and short_count > 0
        row_net_pnl = None if both_sides else net_mtm

        if long_count > 0:
            positions.append({
                "instance_id": inst,
                "instrument": symbol,
                "direction": "LONG",
                "avg_entry_price": None,
                "layers": long_count,
                "net_pnl": row_net_pnl,
            })
        if short_count > 0:
            positions.append({
                "instance_id": inst,
                "instrument": symbol,
                "direction": "SHORT",
                "avg_entry_price": None,
                "layers": short_count,
                "net_pnl": row_net_pnl,
            })

    positions.sort(
        key=lambda item: (item.get("instrument", ""), item.get("instance_id", ""))
    )

    return jsonify({
        "positions": positions,
        "total": len(positions),
        "instance_status": instance_status,
        "tracked_grind_count": len(GRIND_INSTANCES),
        "tracked_total_count": len(GRIND_INSTANCES),
    }), 200


@app.route("/api/telemetry/aggregate", methods=["GET"])
def telemetry_aggregate():
    net_exposure = {}
    grind_api_count_max = 0
    global_account_metrics = _read_global_account_metrics()
    intraday_mae = (
        global_account_metrics.get("intraday_mae")
        if global_account_metrics
        else None
    )

    grind_cards = {}
    for inst in GRIND_INSTANCES:
        raw_grind = r.get(f"fxmatrix:state:{inst}")
        grind_cards[inst] = _summarize_grind_instance_state(inst, raw_grind)
        if raw_grind is None:
            continue

        try:
            grind_data = json.loads(raw_grind)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

        api_val = grind_data.get("api_count")
        if isinstance(api_val, (int, float)) and not isinstance(api_val, bool):
            grind_api_count_max = max(grind_api_count_max, int(api_val))

        _accumulate_grind_net_exposure(net_exposure, inst, grind_data)

    grind_rings = _build_grind_ring_summaries(grind_cards)

    return jsonify({
        "net_exposure": net_exposure,
        "grind_api_count": grind_api_count_max if grind_api_count_max else None,
        "grind_api_count_limit": GRIND_API_DAILY_LIMIT,
        "global_account_metrics": global_account_metrics,
        "intraday_mae": intraday_mae or _empty_intraday_mae(),
        "grind_cards": grind_cards,
        "grind_rings": grind_rings,
    }), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
