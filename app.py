"""
Pipshed — FXMatrix Live Telemetry Dashboard
Flask backend: telemetry receiver + state server

Routes:
  POST /api/telemetry/push   — receives MQL5 payload, writes to Redis
  GET  /api/telemetry/live   — serves current state to dashboard
  GET  /                     — dashboard UI
  GET  /health               — Railway health check
"""

import json
import os

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
    instance_id = request.args.get("instance", "MM")
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


@app.route("/api/telemetry/closed", methods=["GET"])
def telemetry_closed():
    instance_id = request.args.get("instance", "MM")
    redis_key = f"fxmatrix:closed_history:{instance_id}"

    raw_list = r.lrange(redis_key, 0, -1)
    records = [json.loads(item) for item in raw_list]

    return jsonify({"instance_id": instance_id, "records": records}), 200


@app.route("/api/telemetry/aggregate", methods=["GET"])
def telemetry_aggregate():
    instances = ["MM", "SNIPER_LONG", "SNIPER_SHORT"]
    net_exposure = {}       # symbol -> net signed lots (sum of direction * lot_size)
    alerts = []              # [{instance, message}, ...]
    instance_status = {}     # instance -> "live" | "connection_lost"
    best_quotes = {}  # symbol -> {"best_bid": float|None, "best_offer": float|None}

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
        "best_quotes": best_quotes
    }), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
