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
  GET  /api/g/<token>/scalps       — public broker-today scalp exits
  GET  /api/g/<token>/archive      — public archive worker health
  GET  /                         — dashboard UI
  GET  /health                   — Railway health check
"""

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import redis
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

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
ARCHIVE_ACTION_MAX_EVENTS = 500
ARCHIVE_EVENT_TYPES = frozenset({"send_log", "fill_log", "config_event", "ea_event"})

GRIND_INSTANCES = [
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
]

GRIND_OPT_INSTANCES = [inst for inst in GRIND_INSTANCES if inst.endswith("_OPT")]
GRIND_ALT_INSTANCES = [inst for inst in GRIND_INSTANCES if inst.endswith("_ALT")]

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
        opt_instances = [inst for inst in ring_instances if inst.endswith("_OPT")]
        alt_instances = [inst for inst in ring_instances if inst.endswith("_ALT")]
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
)


def _public_scalp_fields(record):
    """Whitelist scalp exit fields safe for the unauthenticated scalps route."""
    return {key: record.get(key) for key in _PUBLIC_SCALP_KEYS}


def _collect_today_scalp_records(selected_date=None):
    """Cross-instance scalp exits for one broker calendar date."""
    broker_today = _broker_today()
    date = selected_date or broker_today
    all_records = []

    for inst in GRIND_INSTANCES:
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
            "total": len(all_records),
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
    return render_template("dashboard.html")


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
        "total": len(all_records),
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
