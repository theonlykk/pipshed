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
  GET  /                         — dashboard UI
  GET  /health                   — Railway health check
"""

import json
import os
from datetime import datetime

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
    if raw is None:
        return jsonify({"status": "connection_lost", "instance_id": instance_id}), 200

    data = json.loads(raw)
    data["status"] = "live"
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

    available_dates = sorted(
        {date for record in records if (date := _closed_record_date(record))},
        reverse=True,
    )
    selected_date = date_filter or (available_dates[0] if available_dates else None)

    if selected_date:
        day_records = [
            record
            for record in records
            if _closed_record_date(record) == selected_date
        ]
    else:
        day_records = []

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
    available_dates = sorted(
        {date for record in records if (date := _closed_record_date(record))},
        reverse=True,
    )
    selected_date = date_filter or (available_dates[0] if available_dates else None)

    if selected_date:
        day_records = [
            record
            for record in records
            if _closed_record_date(record) == selected_date
        ]
    else:
        day_records = []

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


@app.route("/api/telemetry/aggregate", methods=["GET"])
def telemetry_aggregate():
    instances = ["MM_LONG_V2", "MM_SHORT_V2"]
    net_exposure = {}       # symbol -> net signed lots (sum of direction * lot_size)
    alerts = []              # [{instance, message}, ...]
    instance_status = {}     # instance -> "live" | "connection_lost"
    best_quotes = {}  # symbol -> {"best_bid": float|None, "best_offer": float|None}
    full_best_quotes = {}  # symbol -> {"best_bid", "best_offer", "direction_conflict"}

    for inst in instances:
        raw = r.get(f"fxmatrix:state:{inst}")
        if raw is None:
            instance_status[inst] = "connection_lost"
            continue

        data = json.loads(raw)
        instance_status[inst] = "live"

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
            alerts.append({"instance": inst, "message": msg})

    return jsonify({
        "net_exposure": net_exposure,
        "system_alerts": alerts,
        "instance_status": instance_status,
        "best_quotes": best_quotes,
        "full_best_quotes": full_best_quotes,
    }), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
