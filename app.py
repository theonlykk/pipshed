"""
Pipshed — FXMatrix Live Telemetry Dashboard
Flask backend: telemetry receiver + state server

Routes:
  POST /api/telemetry/push         — receives MQL5 payload, writes to Redis
  POST /api/telemetry/pod_closed   — pod-level close history
  POST /api/telemetry/scalp_closed — per-layer scalp close history
  GET  /api/telemetry/live         — serves current state to dashboard
  GET  /api/telemetry/closed       — paginated pod-close history
  GET  /api/telemetry/scalps       — paginated scalp-close history
  GET  /api/telemetry/today_scalps    — cross-instance broker-today scalp exits
  GET  /api/telemetry/today_closed    — cross-instance broker-today pod closes
  GET  /api/telemetry/open_positions — cross-instance open pod snapshot
  GET  /                         — dashboard UI
  GET  /health                   — Railway health check
"""

import json
import os
from datetime import datetime
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

ALL_INSTANCES = [
    "MM_LONG_V2",
    "MM_SHORT_V2",
    "MM_LONG_EURUSD",
    "MM_SHORT_EURUSD",
    "MM_LONG_EURGBP",
    "MM_SHORT_EURGBP",
]

DUMB_INSTANCES = [f"{inst}_DUMB" for inst in ALL_INSTANCES]
TRACKED_INSTANCES = ALL_INSTANCES + DUMB_INSTANCES

GRIND_INSTANCES = [
    "GRIND_GBPUSD_OPT",
    "GRIND_GBPUSD_ALT",
    "GRIND_EURUSD_OPT",
    "GRIND_EURUSD_ALT",
    "GRIND_EURGBP_OPT",
    "GRIND_EURGBP_ALT",
]

GRIND_OPT_INSTANCES = [
    "GRIND_GBPUSD_OPT",
    "GRIND_EURUSD_OPT",
    "GRIND_EURGBP_OPT",
]

GRIND_ALT_INSTANCES = [
    "GRIND_GBPUSD_ALT",
    "GRIND_EURUSD_ALT",
    "GRIND_EURGBP_ALT",
]

GRIND_API_DAILY_LIMIT = 2000

# FTMO / MT5 server time — matches EA trade_date (TimeCurrent() on broker)
BROKER_TIMEZONE = os.environ.get("BROKER_TIMEZONE", "Europe/Athens")


def _broker_today():
    """Return YYYY-MM-DD for the current broker session calendar date."""
    return datetime.now(ZoneInfo(BROKER_TIMEZONE)).strftime("%Y-%m-%d")


def _instance_arm(instance_id):
    """Tag instance as signal or dumb arm via the _DUMB suffix."""
    return "dumb" if instance_id.endswith("_DUMB") else "signal"


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
    """Pull account-level MAE from one engine_state. Do not sum across instances."""
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


def _read_intraday_mae():
    """Account-level intraday MAE from one live instance (prefer signal arm).

    MAE fields are identical across a running arm — never sum across the fleet.
    """
    # Prefer signal-arm instances; fall back to dumb if none are live.
    for inst in ALL_INSTANCES + DUMB_INSTANCES:
        raw = r.get(f"fxmatrix:state:{inst}")
        if raw is None:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        return _mae_from_engine_state(data.get("engine_state", {}), inst)
    return _empty_intraday_mae()


def _count_history_for_date(redis_key, selected_date):
    """Count history list entries whose trade/close date matches selected_date."""
    raw_list = r.lrange(redis_key, 0, -1)
    count = 0
    for item in raw_list:
        record = json.loads(item)
        if _closed_record_date(record) == selected_date:
            count += 1
    return count


def _parse_ta_signal(msg):
    """Extract signal= value from a TA | CRITICAL alert, if present."""
    upper = msg.upper()
    marker = "SIGNAL="
    idx = upper.find(marker)
    if idx < 0:
        return None
    tail = msg[idx + len(marker):].strip()
    for sep in (" ", "|"):
        if sep in tail:
            tail = tail.split(sep)[0]
    return tail.strip() or None


def _classify_alert_messages(messages):
    """Return (is_halted, halt_kind, halt_detail) from system alert strings."""
    # These must match the EA's ACTUAL alert prefixes (fxmatrix: CB|CRITICAL,
    # TA|CRITICAL, HALT|, BCC|). Do NOT invent tokens; verify against the EA
    # source when alert formats change.
    halt_cb = False
    halt_ta = False
    halt_instance = False
    cb_detail = ""
    ta_detail = ""
    halt_detail = ""

    for msg in messages:
        upper = msg.upper()
        if "BCC |" in upper:
            continue

        if "CB | CRITICAL" in upper:
            halt_cb = True
            if not cb_detail:
                cb_detail = msg
        elif "TA | CRITICAL" in upper:
            halt_ta = True
            signal = _parse_ta_signal(msg)
            if not ta_detail:
                ta_detail = f"Trigger A: {signal}" if signal else msg
        elif "HALT |" in upper:
            halt_instance = True
            if not halt_detail:
                halt_detail = msg

    is_halted = halt_cb or halt_ta or halt_instance

    if halt_cb:
        return is_halted, "cb", cb_detail or "Equity floor circuit breaker"
    if halt_ta:
        return is_halted, "ta", ta_detail or "Trigger A anomaly"
    if halt_instance:
        return is_halted, "halt", halt_detail or "Instance halted"
    return False, None, ""


def _summarize_instance_state(instance_id, raw_payload, broker_today):
    """Build per-instance card fields from a live redis payload (or None)."""
    if raw_payload is None:
        return {
            "instance_id": instance_id,
            "arm": _instance_arm(instance_id),
            "connection": "no_data",
            "open_long_layers": 0,
            "open_short_layers": 0,
            "net_mtm": 0.0,
            "instance_daily_api_count": 0,
            "alerts": [],
        }

    data = json.loads(raw_payload)
    es = data.get("engine_state", {})
    open_long = 0
    open_short = 0
    net_mtm = 0.0

    for pod in data.get("active_pods", {}).values():
        net_mtm += float(pod.get("net_pnl") or 0.0)
        for layer in pod.get("layer_detail", []):
            direction = layer.get("direction", 0)
            if direction == 1:
                open_long += 1
            elif direction == -1:
                open_short += 1

    inst_api = es.get("instance_daily_api_count")
    inst_api_count = int(inst_api) if isinstance(inst_api, (int, float)) else 0

    return {
        "instance_id": instance_id,
        "arm": _instance_arm(instance_id),
        "connection": "live",
        "open_long_layers": open_long,
        "open_short_layers": open_short,
        "net_mtm": round(net_mtm, 2),
        "instance_daily_api_count": inst_api_count,
        "alerts": list(data.get("system_alerts", [])),
    }


def _grind_bool(value):
    """Coerce fxgrind heartbeat booleans (JSON true/false or legacy strings)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == "true"
    return False


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
    }


def _summarize_grind_arm(group_label, instances, grind_cards):
    """Aggregate operator-facing totals for one grind variant (OPT or ALT).

    Separate from v2 _summarize_arm — deletable when v2 arms retire.
    """
    open_long = 0
    open_short = 0
    fills_total = 0
    scalps_total = 0
    # MAX not SUM: GRIND_DAILY_API_COUNT (ea/grind_api_counter.mqh) is one shared
    # GlobalVariable incremented by all six grind instances; each heartbeat
    # reports the same family-wide count against the 2,000 FTMO limit.
    api_count_max = 0
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
        "api_count": api_count_max if instances_live > 0 else None,
        "api_count_limit": GRIND_API_DAILY_LIMIT,
        "instances_live": instances_live,
        "instances_total": len(instances),
        "halted_instances": halted_instances,
    }


def _summarize_arm(instances, broker_today):
    """Aggregate operator-facing totals for one arm (signal or dumb)."""
    open_long = 0
    open_short = 0
    scalps_today = 0
    fills_today = 0
    instance_daily_api_count = 0
    net_mtm = 0.0
    instances_live = 0
    all_alerts = []

    for inst in instances:
        raw = r.get(f"fxmatrix:state:{inst}")
        card = _summarize_instance_state(inst, raw, broker_today)
        if card["connection"] != "live":
            continue

        instances_live += 1
        open_long += card["open_long_layers"]
        open_short += card["open_short_layers"]
        net_mtm += card["net_mtm"]
        instance_daily_api_count += card["instance_daily_api_count"]
        all_alerts.extend(card["alerts"])

        scalps_today += _count_history_for_date(
            f"fxmatrix:scalp_history:{inst}", broker_today
        )
        fills_today += _count_history_for_date(
            f"fxmatrix:closed_history:{inst}", broker_today
        )

    is_halted, halt_kind, halt_detail = _classify_alert_messages(all_alerts)

    if instances_live == 0:
        status = "no_data"
        status_label = "NO DATA"
        status_detail = "No telemetry received for this arm"
    elif is_halted and halt_kind == "cb":
        status = "halted"
        status_label = "HALTED — circuit breaker"
        status_detail = halt_detail or "Equity floor circuit breaker (CB | CRITICAL)"
    elif is_halted and halt_kind == "ta":
        status = "halted"
        status_label = "HALTED — trigger A"
        status_detail = halt_detail or "Trigger A anomaly (TA | CRITICAL)"
    elif is_halted:
        status = "halted"
        status_label = "HALTED — instance halt"
        status_detail = halt_detail or "Instance halted (HALT |)"
    else:
        status = "running"
        status_label = "RUNNING"
        status_detail = f"{instances_live}/{len(instances)} instances live"

    return {
        "arm": _instance_arm(instances[0]) if instances else "unknown",
        "status": status,
        "status_label": status_label,
        "status_detail": status_detail,
        "open_long_layers": open_long,
        "open_short_layers": open_short,
        "fills_today": fills_today,
        "scalps_today": scalps_today,
        "instance_daily_api_count": instance_daily_api_count,
        "net_mtm": round(net_mtm, 2),
        "instances_live": instances_live,
        "instances_total": len(instances),
    }


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


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


@app.route("/api/telemetry/live", methods=["GET"])
def telemetry_live():
    instance_id = request.args.get("instance", "MM_LONG_V2")
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
    instance_id = request.args.get("instance", "MM_LONG_V2")
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

    pipe = r.pipeline()
    pipe.lpush(redis_key, json.dumps(payload))
    pipe.ltrim(redis_key, 0, SCALP_HISTORY_LIST_MAX)
    pipe.expire(redis_key, SCALP_HISTORY_TTL_SECONDS)
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
    instance_id = request.args.get("instance", "MM_LONG_V2")
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
    """Scan all instance lists — dates present, earliest retained, list lengths."""
    all_dates = set()
    per_instance = {}

    for inst in TRACKED_INSTANCES:
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
    """Scan all instance scalp lists — dates present, earliest retained, list lengths."""
    all_dates = set()
    per_instance = {}

    for inst in TRACKED_INSTANCES:
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
    selected_date = date_filter or broker_today

    available_dates, earliest_date, retention = _collect_scalp_history_meta()
    all_records = []

    for inst in TRACKED_INSTANCES:
        raw_list = r.lrange(f"fxmatrix:scalp_history:{inst}", 0, -1)
        records = [json.loads(item) for item in raw_list]
        day_records = [
            record
            for record in records
            if _closed_record_date(record) == selected_date
        ]
        for record in day_records:
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


@app.route("/api/telemetry/today_closed", methods=["GET"])
def telemetry_today_closed():
    """Cross-instance pod closes for a broker calendar date (default: today)."""
    broker_today = _broker_today()
    date_filter = request.args.get("date")
    selected_date = date_filter or broker_today

    available_dates, earliest_date, retention = _collect_closed_history_meta()
    all_records = []

    for inst in TRACKED_INSTANCES:
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


@app.route("/api/telemetry/open_positions", methods=["GET"])
def telemetry_open_positions():
    """Cross-instance snapshot of every pod with open layers."""
    positions = []
    instance_status = {}

    for inst in TRACKED_INSTANCES:
        raw = r.get(f"fxmatrix:state:{inst}")
        if raw is None:
            instance_status[inst] = "connection_lost"
            continue

        instance_status[inst] = "live"
        data = json.loads(raw)
        pods = data.get("active_pods", {})

        for symbol, pod in pods.items():
            layer_count = pod.get("layers", 0)
            if layer_count <= 0:
                continue

            layer_detail = pod.get("layer_detail", [])
            direction_int = layer_detail[0].get("direction") if layer_detail else None
            if direction_int == 1:
                direction = "LONG"
            elif direction_int == -1:
                direction = "SHORT"
            else:
                direction = "—"

            avg_entry = layer_detail[0].get("entry_price") if layer_detail else None

            positions.append({
                "instance_id": inst,
                "instrument": symbol,
                "direction": direction,
                "avg_entry_price": avg_entry,
                "layers": layer_count,
                "net_pnl": pod.get("net_pnl"),
            })

    positions.sort(
        key=lambda item: (item.get("instrument", ""), item.get("instance_id", ""))
    )

    return jsonify({
        "positions": positions,
        "total": len(positions),
        "instance_status": instance_status,
    }), 200


@app.route("/api/telemetry/aggregate", methods=["GET"])
def telemetry_aggregate():
    instances = TRACKED_INSTANCES
    broker_today = _broker_today()
    net_exposure = {}       # symbol -> net signed lots (sum of direction * lot_size)
    alerts = []              # [{instance, message, arm}, ...]
    instance_status = {}     # instance -> "live" | "connection_lost"
    instance_cards = {}    # instance -> per-instance summary for grouped cards
    best_quotes = {}  # symbol -> {"best_bid": float|None, "best_offer": float|None}
    full_best_quotes = {}  # symbol -> {"best_bid", "best_offer", "direction_conflict"}
    account_daily_api_count = 0
    account_daily_api_warning = False
    # Account-level MAE: capture from the first live instance only (SIGNAL
    # instances are listed first in TRACKED_INSTANCES). Never sum these.
    intraday_mae = None

    for inst in instances:
        raw = r.get(f"fxmatrix:state:{inst}")
        card = _summarize_instance_state(inst, raw, broker_today)
        instance_cards[inst] = card

        if raw is None:
            instance_status[inst] = "connection_lost"
            continue

        data = json.loads(raw)
        instance_status[inst] = "live"
        arm = _instance_arm(inst)

        es = data.get("engine_state", {})
        if intraday_mae is None:
            intraday_mae = _mae_from_engine_state(es, inst)
        api_count = es.get("account_daily_api_count")
        if isinstance(api_count, (int, float)):
            account_daily_api_count = max(account_daily_api_count, int(api_count))
        if es.get("account_daily_api_warning") is True:
            account_daily_api_warning = True

        pods = data.get("active_pods", {})
        for symbol, pod in pods.items():
            for layer in pod.get("layer_detail", []):
                direction = layer.get("direction", 0)
                lot = layer.get("lot_size", 0.0)
                net_exposure[symbol] = net_exposure.get(symbol, 0.0) + (direction * lot)

            layers = pod.get("layer_detail", [])
            directions = set(
                layer.get("direction")
                for layer in layers
                if layer.get("direction") is not None
            )

            if symbol not in full_best_quotes:
                full_best_quotes[symbol] = {
                    "best_bid": None,
                    "best_offer": None,
                    "direction_conflict": False,
                }

            if len(directions) > 1:
                full_best_quotes[symbol]["direction_conflict"] = True
            else:
                slot_direction = next(iter(directions), None)
                working = data.get("working_orders", {}).get(symbol, {})

                l0_bid = working.get("layer0_bid_price")
                l0_offer = working.get("layer0_offer_price")
                if l0_bid is not None:
                    cur = full_best_quotes[symbol]["best_bid"]
                    if cur is None or l0_bid > cur:
                        full_best_quotes[symbol]["best_bid"] = l0_bid
                if l0_offer is not None:
                    cur = full_best_quotes[symbol]["best_offer"]
                    if cur is None or l0_offer < cur:
                        full_best_quotes[symbol]["best_offer"] = l0_offer

                if slot_direction is not None:
                    add_price = working.get("add_next_price")
                    if add_price is not None:
                        if slot_direction == 1:
                            cur = full_best_quotes[symbol]["best_bid"]
                            if cur is None or add_price > cur:
                                full_best_quotes[symbol]["best_bid"] = add_price
                        elif slot_direction == -1:
                            cur = full_best_quotes[symbol]["best_offer"]
                            if cur is None or add_price < cur:
                                full_best_quotes[symbol]["best_offer"] = add_price

                    for exit_order in working.get("exit_orders", []):
                        exit_price = exit_order.get("price")
                        if exit_price is None:
                            continue
                        if slot_direction == 1:
                            cur = full_best_quotes[symbol]["best_offer"]
                            if cur is None or exit_price < cur:
                                full_best_quotes[symbol]["best_offer"] = exit_price
                        elif slot_direction == -1:
                            cur = full_best_quotes[symbol]["best_bid"]
                            if cur is None or exit_price > cur:
                                full_best_quotes[symbol]["best_bid"] = exit_price

        working = data.get("working_orders", {})
        for symbol, quote in working.items():
            if symbol not in best_quotes:
                best_quotes[symbol] = {"best_bid": None, "best_offer": None}
            bid = quote.get("layer0_bid_price")
            offer = quote.get("layer0_offer_price")
            if bid is not None:
                if best_quotes[symbol]["best_bid"] is None or bid > best_quotes[symbol]["best_bid"]:
                    best_quotes[symbol]["best_bid"] = bid
            if offer is not None:
                if best_quotes[symbol]["best_offer"] is None or offer < best_quotes[symbol]["best_offer"]:
                    best_quotes[symbol]["best_offer"] = offer

        for msg in data.get("system_alerts", []):
            alerts.append({"instance": inst, "arm": arm, "message": msg})

    arm_summaries = {
        "signal": _summarize_arm(ALL_INSTANCES, broker_today),
        "dumb": _summarize_arm(DUMB_INSTANCES, broker_today),
    }

    grind_cards = {}
    for inst in GRIND_INSTANCES:
        raw_grind = r.get(f"fxmatrix:state:{inst}")
        grind_cards[inst] = _summarize_grind_instance_state(inst, raw_grind)

    grind_arm_summaries = {
        "opt": _summarize_grind_arm("GRIND OPT", GRIND_OPT_INSTANCES, grind_cards),
        "alt": _summarize_grind_arm("GRIND ALT", GRIND_ALT_INSTANCES, grind_cards),
    }

    return jsonify({
        "net_exposure": net_exposure,
        "system_alerts": alerts,
        "instance_status": instance_status,
        "instance_cards": instance_cards,
        "arm_summaries": arm_summaries,
        "best_quotes": best_quotes,
        "full_best_quotes": full_best_quotes,
        "account_daily_api_count": account_daily_api_count,
        "account_daily_api_warning": account_daily_api_warning,
        "account_daily_api_limit": 2000,
        "intraday_mae": intraday_mae or _empty_intraday_mae(),
        "grind_cards": grind_cards,
        "grind_arm_summaries": grind_arm_summaries,
    }), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
