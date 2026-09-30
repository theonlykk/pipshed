"""Passive ejection telemetry view builder (C56). Pure functions, no Flask/Postgres I/O."""

import json
from datetime import datetime, timedelta, timezone

import ftmo_daily as fd

EJECTION_VIEW_MAX_AGE_S = 300
WORKER_EJECTION_HOURS = 168


def clamp_hours(raw):
    try:
        hours = int(raw)
    except (TypeError, ValueError):
        hours = 48
    return max(1, min(168, hours))


def ea_ms_to_iso(ms):
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _side_code(detail=None, direction=None):
    if isinstance(detail, dict):
        side = detail.get("side")
        if side in ("L", "S"):
            return side
    if direction == "LONG":
        return "L"
    if direction == "SHORT":
        return "S"
    return None


def _fill_entry_kind(row):
    entry = (row.get("entry_type") or "").upper()
    deal = (row.get("deal_type") or "").upper()
    if entry == "OUT_BY" or deal == "OUT_BY":
        return "OUT_BY"
    if entry == "OUT" or deal == "OUT":
        return "OUT"
    if entry == "IN" or deal == "IN":
        return "IN"
    return entry or deal


def _side_letter(row):
    side = row.get("side")
    if isinstance(side, str):
        s = side.strip().upper()
        if s in ("L", "S"):
            return s
        if s in ("BUY", "LONG"):
            return "L"
        if s in ("SELL", "SHORT"):
            return "S"
    return None


def _sum_deals_for_positions(fill_rows, position_ids):
    gross = 0.0
    commission = 0.0
    swap = 0.0
    seen = set()
    for row in fill_rows:
        if row.get("position_id") not in position_ids:
            continue
        deal_ticket = row.get("deal_ticket")
        if deal_ticket in seen:
            continue
        if deal_ticket is not None:
            seen.add(deal_ticket)
        if row.get("profit") is not None:
            gross += float(row["profit"])
        if row.get("commission") is not None:
            commission += float(row["commission"])
        if row.get("swap") is not None:
            swap += float(row["swap"])
    return (
        round(gross, 2),
        round(commission, 2),
        round(swap, 2),
        round(gross + commission + swap, 2),
    )


def _layer_from_ent(fill_rows, position_ids):
    for row in fill_rows:
        if row.get("position_id") not in position_ids:
            continue
        if _fill_entry_kind(row) != "IN":
            continue
        if (row.get("role") or "").upper() != "ENT":
            continue
        return row.get("position_id"), _side_letter(row), row.get("layer_index")
    return None, None, None


def closed_trades_from_fills(fill_rows, roll_positions=None, eject_positions=None):
    """Build closed-trade buckets from broker fill_logs (ADR-159 close-by grouping)."""
    roll_positions = set(roll_positions or [])
    eject_positions = set(eject_positions or [])
    by_order = {}
    single_out = []
    for row in fill_rows:
        kind = _fill_entry_kind(row)
        if kind == "OUT_BY":
            order_ticket = row.get("order_ticket")
            if order_ticket is None:
                continue
            by_order.setdefault(order_ticket, []).append(row)
        elif kind == "OUT":
            single_out.append(row)

    closes = []
    odd_closeby = []
    for order_ticket, out_deals in by_order.items():
        if len(out_deals) != 2:
            odd_closeby.append({
                "order_ticket": order_ticket,
                "deal_count": len(out_deals),
                "instance_id": out_deals[0].get("instance_id") if out_deals else None,
            })
            continue
        positions = {
            d.get("position_id") for d in out_deals if d.get("position_id") is not None
        }
        if not positions:
            continue
        close_ms = max(int(d.get("ea_time_ms") or 0) for d in out_deals)
        inst = out_deals[0].get("instance_id")
        layer_pos, side, layer_index = _layer_from_ent(fill_rows, positions)
        incomplete = layer_pos is None
        if side is None:
            for deal in out_deals:
                side = _side_letter(deal)
                if side:
                    break
        gross, commission, swap, net = _sum_deals_for_positions(fill_rows, positions)
        if incomplete:
            net = None
            commission = None
            swap = None
        if layer_pos in roll_positions:
            trade_class = "roll"
        elif layer_pos in eject_positions:
            trade_class = "eject"
        else:
            trade_class = "scalp"
        closes.append({
            "instance_id": inst,
            "order_ticket": order_ticket,
            "close_ms": close_ms,
            "side": side,
            "layer_index": layer_index,
            "layer_position": layer_pos,
            "positions": sorted(positions),
            "class": trade_class,
            "gross": gross,
            "commission": commission,
            "swap": swap,
            "net": net,
            "incomplete": incomplete,
            "net_known": not incomplete,
        })

    for row in single_out:
        pos = row.get("position_id")
        if pos is None:
            continue
        positions = {pos}
        close_ms = int(row.get("ea_time_ms") or 0)
        inst = row.get("instance_id")
        layer_pos, side, layer_index = _layer_from_ent(fill_rows, positions)
        incomplete = layer_pos is None
        if side is None:
            side = _side_letter(row)
        gross, commission, swap, net = _sum_deals_for_positions(fill_rows, positions)
        if incomplete:
            net = None
            commission = None
            swap = None
        if layer_pos in roll_positions:
            trade_class = "roll"
        elif layer_pos in eject_positions:
            trade_class = "eject"
        else:
            trade_class = "scalp"
        closes.append({
            "instance_id": inst,
            "order_ticket": row.get("order_ticket"),
            "close_ms": close_ms,
            "side": side,
            "layer_index": layer_index,
            "layer_position": layer_pos,
            "positions": [pos],
            "class": trade_class,
            "gross": gross,
            "commission": commission,
            "swap": swap,
            "net": net,
            "incomplete": incomplete,
            "net_known": not incomplete,
        })

    return closes, odd_closeby


def _roll_eject_tickets(events):
    roll = {
        e.get("ticket")
        for e in events
        if e.get("code") == "ROLL_FILLED" and e.get("ticket") is not None
    }
    eject = {
        e.get("ticket")
        for e in events
        if e.get("code") == "EJECT_FILLED" and e.get("ticket") is not None
    }
    return roll, eject


def _close_on_ftmo_day(close, day):
    ms = close.get("close_ms")
    if not ms:
        return False
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return fd.ftmo_day_of_utc(dt) == day


def _realised_from_close(close):
    if not close or close.get("incomplete"):
        return None
    return {
        "gross": close.get("gross"),
        "commission": close.get("commission"),
        "swap": close.get("swap"),
        "net": close.get("net"),
    }


def _aggregate_class_bucket(closes):
    incomplete = sum(1 for c in closes if c.get("incomplete"))
    gross = round(sum(float(c.get("gross") or 0) for c in closes), 2)
    if incomplete:
        return {
            "count": len(closes),
            "gross": gross,
            "commission": None,
            "swap": None,
            "net": None,
            "incomplete": incomplete,
            "net_known": False,
        }
    commission = round(sum(float(c.get("commission") or 0) for c in closes), 2)
    swap = round(sum(float(c.get("swap") or 0) for c in closes), 2)
    net = round(sum(float(c.get("net") or 0) for c in closes), 2)
    return {
        "count": len(closes),
        "gross": gross,
        "commission": commission,
        "swap": swap,
        "net": net,
        "incomplete": 0,
        "net_known": True,
    }


def _filter_instance_rows(rows, grind_instances):
    allowed = set(grind_instances)
    return [r for r in rows if r.get("instance_id") in allowed]


def _events_by_ticket(events, prefix):
    out = {}
    for ev in events:
        code = ev.get("code") or ""
        if not code.startswith(prefix):
            continue
        ticket = ev.get("ticket")
        if ticket is None:
            continue
        out.setdefault(ticket, []).append(ev)
    return out


def _minutes_between(ms_a, ms_b):
    if ms_a is None or ms_b is None:
        return None
    return int(round((ms_b - ms_a) / 60000.0))


def _build_roll_rows(events, close_by_layer):
    accepted = _events_by_ticket(events, "ROLL_")
    rows = []
    seen = set()
    for ticket, evlist in accepted.items():
        if ticket in seen:
            continue
        seen.add(ticket)
        acc = next((e for e in evlist if e.get("code") == "ROLL_ACCEPTED"), None)
        refused = next((e for e in evlist if e.get("code") == "ROLL_REFUSED"), None)
        if acc is None and refused is None:
            continue
        detail = (acc or refused).get("detail") or {}
        inst = (acc or refused).get("instance_id")
        filled = next((e for e in evlist if e.get("code") == "ROLL_FILLED"), None)
        status = "accepted"
        filled_at = None
        minutes_to_fill = None
        realised = None
        accepted_ms = (acc or refused).get("ea_time_ms")
        if filled:
            status = "filled"
            filled_at = ea_ms_to_iso(filled.get("ea_time_ms"))
            minutes_to_fill = _minutes_between(accepted_ms, filled.get("ea_time_ms"))
            realised = _realised_from_close(close_by_layer.get(ticket))
        elif refused:
            status = "refused"
        rows.append({
            "instance_id": inst,
            "side": _side_code(detail),
            "layer_index": detail.get("layer_index"),
            "ticket": ticket,
            "entry": detail.get("entry"),
            "level": detail.get("level"),
            "target": detail.get("target"),
            "cost_pips": detail.get("cost_pips"),
            "clamped": detail.get("clamped"),
            "source": detail.get("source"),
            "accepted_at": ea_ms_to_iso(accepted_ms),
            "status": status,
            "filled_at": filled_at,
            "minutes_to_fill": minutes_to_fill,
            "realised": realised,
        })
    rows.sort(key=lambda r: (r.get("accepted_at") or "", r.get("ticket") or 0))
    return rows


def _build_ejection_rows(events, close_by_layer):
    by_ticket = _events_by_ticket(events, "EJECT_")
    rows = []
    for ticket, evlist in by_ticket.items():
        acc = next((e for e in evlist if e.get("code") == "EJECT_ACCEPTED"), None)
        if acc is None:
            continue
        detail = acc.get("detail") or {}
        filled = next((e for e in evlist if e.get("code") == "EJECT_FILLED"), None)
        refused = next((e for e in evlist if e.get("code") == "EJECT_REFUSED"), None)
        status = "accepted"
        filled_at = None
        minutes_to_fill = None
        realised = None
        offset = detail.get("offset")
        if filled:
            status = "filled"
            filled_at = ea_ms_to_iso(filled.get("ea_time_ms"))
            minutes_to_fill = _minutes_between(acc.get("ea_time_ms"), filled.get("ea_time_ms"))
            fdetail = filled.get("detail") or {}
            if fdetail.get("offset") is not None:
                offset = fdetail.get("offset")
            realised = _realised_from_close(close_by_layer.get(ticket))
        elif refused:
            status = "refused"
        rows.append({
            "instance_id": acc.get("instance_id"),
            "side": _side_code(detail),
            "layer_index": detail.get("layer_index"),
            "ticket": ticket,
            "entry": detail.get("entry"),
            "offset": offset,
            "source": detail.get("source"),
            "accepted_at": ea_ms_to_iso(acc.get("ea_time_ms")),
            "status": status,
            "filled_at": filled_at,
            "minutes_to_fill": minutes_to_fill,
            "realised": realised,
        })
    rows.sort(key=lambda r: (r.get("accepted_at") or "", r.get("ticket") or 0))
    return rows


def _scalp_in_ftmo_day(scalp, day):
    offset_s = scalp.get("broker_utc_offset_s")
    if offset_s is None:
        return False
    utc_close = fd._scalp_utc_close(scalp.get("close_time_broker"), offset_s)
    if utc_close is None:
        return False
    start, end = fd.ftmo_day_bounds_utc(day)
    return start <= utc_close < end


def _days_in_window(window_start_ms, window_end_ms):
    start = datetime.fromtimestamp(window_start_ms / 1000.0, tz=timezone.utc)
    end = datetime.fromtimestamp(window_end_ms / 1000.0, tz=timezone.utc)
    days = set()
    day = fd.ftmo_day_of_utc(start)
    last = fd.ftmo_day_of_utc(end - timedelta(seconds=1))
    while day <= last:
        days.add(day)
        day += timedelta(days=1)
    return sorted(days)


def _build_days(closes, grind_instances, window_start_ms, window_end_ms):
    blocks = []
    for ftmo_day in _days_in_window(window_start_ms, window_end_ms):
        day_block = {"ftmo_day": ftmo_day.isoformat(), "instances": []}
        for inst in grind_instances:
            inst_block = {"instance_id": inst, "sides": []}
            for side in ("L", "S"):
                day_closes = [
                    c
                    for c in closes
                    if c.get("instance_id") == inst
                    and c.get("side") == side
                    and _close_on_ftmo_day(c, ftmo_day)
                ]
                scalps_bucket = _aggregate_class_bucket(
                    [c for c in day_closes if c.get("class") == "scalp"]
                )
                rolls_bucket = _aggregate_class_bucket(
                    [c for c in day_closes if c.get("class") == "roll"]
                )
                eject_bucket = _aggregate_class_bucket(
                    [c for c in day_closes if c.get("class") == "eject"]
                )
                incomplete = (
                    scalps_bucket.get("incomplete", 0)
                    + rolls_bucket.get("incomplete", 0)
                    + eject_bucket.get("incomplete", 0)
                )
                if incomplete:
                    closed_net = None
                else:
                    closed_net = round(
                        float(scalps_bucket.get("net") or 0)
                        + float(rolls_bucket.get("net") or 0)
                        + float(eject_bucket.get("net") or 0),
                        2,
                    )
                side_block = {
                    "side": side,
                    "scalps": scalps_bucket,
                    "rolls": rolls_bucket,
                    "ejections": eject_bucket,
                    "closed_net": closed_net,
                    "incomplete": incomplete,
                    "net_known": incomplete == 0,
                }
                inst_block["sides"].append(side_block)
            day_block["instances"].append(inst_block)
        blocks.append(day_block)
    return blocks


def _rolled_by_events(events, side):
    accepted = {}
    for ev in events:
        if ev.get("code") == "ROLL_ACCEPTED":
            detail = ev.get("detail") or {}
            if _side_code(detail) != side:
                continue
            accepted[ev.get("ticket")] = ev.get("ea_time_ms")
    for ev in events:
        code = ev.get("code")
        if code in ("ROLL_FILLED", "ROLL_REFUSED"):
            accepted.pop(ev.get("ticket"), None)
    return len(accepted)


def _price_or_none(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 5)
    return None


def _heartbeat_timestamp_age_s(data, now_dt):
    """Age of stored grind state — `_received_at` from telemetry_push, else legacy timestamp."""
    ts = data.get("_received_at") or data.get("timestamp")
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        payload_ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if payload_ts.tzinfo is None:
        payload_ts = payload_ts.replace(tzinfo=timezone.utc)
    return max(0, int((now_dt - payload_ts).total_seconds()))


def _heartbeat_market_price(data):
    # Grind heartbeats carry no market price today; fxmatrix backlog may add one later.
    return _price_or_none(data.get("market"))


def _normalize_state_layers(raw_layers):
    rows = []
    for layer in raw_layers or []:
        if not isinstance(layer, dict):
            continue
        side = layer.get("side")
        if isinstance(side, str):
            side = side.strip().upper()
            if side not in ("L", "S"):
                side = None
        entry = layer.get("entry_price")
        if entry is None:
            entry = layer.get("entry")
        idx = layer.get("layer_index")
        rows.append({
            "layer_index": int(idx) if isinstance(idx, (int, float)) and not isinstance(idx, bool) else None,
            "side": side,
            "entry": _price_or_none(entry),
            "virtual_level": _price_or_none(layer.get("virtual_level")),
            "exit_target": _price_or_none(layer.get("exit_target")),
        })
    return rows


def _parse_live_heartbeat(raw_payload, now_dt):
    if not raw_payload:
        return {}
    try:
        data = json.loads(raw_payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "layers": _normalize_state_layers(data.get("layers")),
        "max_layers": data.get("max_layers"),
        "market": _heartbeat_market_price(data),
        "state_age_s": _heartbeat_timestamp_age_s(data, now_dt),
    }


def _build_now(events, state_by_instance, grind_instances):
    now = {}
    for inst in grind_instances:
        now[inst] = {}
        state = state_by_instance.get(inst) or {}
        inst_events = [e for e in events if e.get("instance_id") == inst]
        state_layers = state.get("layers") or []
        for side in ("L", "S"):
            layers = []
            for layer in state_layers:
                layer_side = layer.get("side")
                if layer_side is None:
                    layer_side = _side_code(detail=layer)
                if layer_side is not None and layer_side != side:
                    continue
                if layer_side is None and side != "L":
                    continue
                layers.append({
                    "layer_index": layer.get("layer_index"),
                    # EA heartbeat layers carry no position ticket.
                    "ticket": None,
                    "entry": layer.get("entry"),
                    "virtual_level": layer.get("virtual_level"),
                    "exit_target": layer.get("exit_target"),
                })
            layers.sort(key=lambda x: x.get("layer_index") or 0)
            rolled_state = sum(
                1 for layer in layers if layer.get("virtual_level") is not None
            )
            rolled_events = _rolled_by_events(inst_events, side)
            rolled_by_state = rolled_state if state_layers else None
            disagree = (
                rolled_by_state is not None
                and rolled_by_state != rolled_events
            )
            effective = []
            for layer in layers:
                eff = layer.get("virtual_level")
                if eff is None:
                    eff = layer.get("entry")
                if eff is not None:
                    effective.append(float(eff))
            if side == "L":
                lowest_effective = min(effective) if effective else None
            else:
                lowest_effective = max(effective) if effective else None
            stranded_at = None
            for ev in inst_events:
                if ev.get("code") != "ROLL_STRANDED":
                    continue
                detail = ev.get("detail") or {}
                if _side_code(detail) == side:
                    stranded_at = ea_ms_to_iso(ev.get("ea_time_ms"))
            now[inst][side] = {
                "depth": len(layers) if state_layers else None,
                "max_layers": state.get("max_layers"),
                "rolled": rolled_state,
                "lowest_effective": lowest_effective,
                "market": state.get("market"),
                "last_stranded_at": stranded_at,
                "state_age_s": state.get("state_age_s"),
                "layers": layers,
                "rolled_by_events": rolled_events,
                "rolled_by_state": rolled_by_state,
                "disagree": disagree,
            }
    return now


def _build_warnings(events):
    rows = []
    for ev in events:
        if ev.get("code") not in ("ROLL_STRANDED", "ROLL_CLOSING_STUCK"):
            continue
        rows.append({
            "instance_id": ev.get("instance_id"),
            "code": ev.get("code"),
            "level": ev.get("level"),
            "ea_time_ms": ev.get("ea_time_ms"),
            "at": ea_ms_to_iso(ev.get("ea_time_ms")),
            "detail": ev.get("detail"),
        })
    rows.sort(key=lambda r: r.get("at") or "")
    return rows


def _build_reconciliation(
    events,
    closes,
    odd_closeby,
    scalps,
    close_by_layer,
    now_dt,
    grind_instances,
    window_start_ms,
    window_end_ms,
):
    blocks = []
    by_inst = {}
    for ev in events:
        by_inst.setdefault(ev.get("instance_id"), []).append(ev)

    for ftmo_day in _days_in_window(window_start_ms, window_end_ms):
        for inst in grind_instances:
            evlist = by_inst.get(inst, [])
            day_closes = [
                c
                for c in closes
                if c.get("instance_id") == inst and _close_on_ftmo_day(c, ftmo_day)
            ]
            scalp_rows = [
                s
                for s in scalps or []
                if s.get("instance_id") == inst and _scalp_in_ftmo_day(s, ftmo_day)
            ]
            ledger_gross = round(sum(float(c.get("gross") or 0) for c in day_closes), 2)
            scalp_gross = round(
                sum(float(s.get("gross_pnl") or 0) for s in scalp_rows), 2
            )
            # C66: the ledger's gross is price profit only, the EA's gross_pnl
            # includes swap. Compare ledger gross + swap with the EA; closes
            # whose swap is unknown (incomplete) are counted, not guessed.
            ledger_swap = round(
                sum(float(c.get("swap") or 0) for c in day_closes if c.get("swap") is not None), 2
            )
            swap_unknown = sum(1 for c in day_closes if c.get("swap") is None)
            ledger_gross_with_swap = round(ledger_gross + ledger_swap, 2)
            gross_delta = round(scalp_gross - ledger_gross_with_swap, 2)
            day_odd = [
                o
                for o in odd_closeby
                if o.get("instance_id") == inst
            ]
            incomplete = sum(1 for c in day_closes if c.get("incomplete"))

            accepted_unfilled = []
            filled_unmatched = []
            refused = {}
            roll_accepted = {
                e.get("ticket"): e
                for e in evlist
                if e.get("code") == "ROLL_ACCEPTED"
                and fd.ftmo_day_of_utc(
                    datetime.fromtimestamp(e["ea_time_ms"] / 1000.0, tz=timezone.utc)
                )
                == ftmo_day
            }
            roll_filled = {
                e.get("ticket")
                for e in evlist
                if e.get("code") == "ROLL_FILLED"
                and fd.ftmo_day_of_utc(
                    datetime.fromtimestamp(e["ea_time_ms"] / 1000.0, tz=timezone.utc)
                )
                == ftmo_day
            }
            roll_refused = {
                e.get("ticket")
                for e in evlist
                if e.get("code") == "ROLL_REFUSED"
                and fd.ftmo_day_of_utc(
                    datetime.fromtimestamp(e["ea_time_ms"] / 1000.0, tz=timezone.utc)
                )
                == ftmo_day
            }
            for ticket, ev in roll_accepted.items():
                if ticket in roll_filled or ticket in roll_refused:
                    continue
                age_h = None
                if ev.get("ea_time_ms") and now_dt:
                    age_h = round(
                        (now_dt.timestamp() * 1000 - ev["ea_time_ms"]) / 3600000.0, 2
                    )
                accepted_unfilled.append({
                    "ticket": ticket,
                    "accepted_at": ea_ms_to_iso(ev.get("ea_time_ms")),
                    "age_h": age_h,
                })
            for ev in evlist:
                if ev.get("code") == "ROLL_REFUSED":
                    if fd.ftmo_day_of_utc(
                        datetime.fromtimestamp(ev["ea_time_ms"] / 1000.0, tz=timezone.utc)
                    ) != ftmo_day:
                        continue
                    reason = (ev.get("detail") or {}).get("reason") or "unknown"
                    refused[reason] = refused.get(reason, 0) + 1
                if ev.get("code") == "EJECT_REFUSED":
                    if fd.ftmo_day_of_utc(
                        datetime.fromtimestamp(ev["ea_time_ms"] / 1000.0, tz=timezone.utc)
                    ) != ftmo_day:
                        continue
                    reason = (ev.get("detail") or {}).get("reason") or "unknown"
                    refused[reason] = refused.get(reason, 0) + 1
            for ev in evlist:
                if ev.get("code") != "ROLL_FILLED":
                    continue
                if fd.ftmo_day_of_utc(
                    datetime.fromtimestamp(ev["ea_time_ms"] / 1000.0, tz=timezone.utc)
                ) != ftmo_day:
                    continue
                ticket = ev.get("ticket")
                if close_by_layer.get(ticket) is None:
                    filled_unmatched.append({
                        "ticket": ticket,
                        "filled_at": ea_ms_to_iso(ev.get("ea_time_ms")),
                    })

            if (
                not day_closes
                and not scalp_rows
                and not refused
                and not accepted_unfilled
                and not filled_unmatched
                and not day_odd
            ):
                continue

            blocks.append({
                "instance_id": inst,
                "ftmo_day": ftmo_day.isoformat(),
                "ledger_closes": len(day_closes),
                "scalp_history_rows": len(scalp_rows),
                "ledger_gross": ledger_gross,
                "ledger_swap": ledger_swap,
                "ledger_gross_with_swap": ledger_gross_with_swap,
                "scalp_gross": scalp_gross,
                "gross_delta": gross_delta,
                "swap_unknown": swap_unknown,
                "odd_closeby": day_odd,
                "incomplete": incomplete,
                "accepted_unfilled": accepted_unfilled,
                "filled_unmatched": filled_unmatched,
                "refused": refused,
            })
    return blocks


def build_ejection_view(
    *,
    generated_at,
    fleet,
    fleet_label,
    hours,
    grind_instances,
    events,
    scalps,
    fill_logs,
    state_by_instance,
    now_dt,
    window_start_ms,
    window_end_ms,
):
    events = _filter_instance_rows(events, grind_instances)
    scalps = _filter_instance_rows(scalps, grind_instances)
    events = [
        e
        for e in events
        if e.get("ea_time_ms") is not None
        and window_start_ms <= e["ea_time_ms"] < window_end_ms
    ]

    roll_tickets, eject_tickets = _roll_eject_tickets(events)
    closes, odd_closeby = closed_trades_from_fills(
        fill_logs, roll_tickets, eject_tickets
    )
    close_by_layer = {
        c["layer_position"]: c for c in closes if c.get("layer_position") is not None
    }
    rolls = _build_roll_rows(events, close_by_layer)
    ejections = _build_ejection_rows(events, close_by_layer)
    days = _build_days(closes, grind_instances, window_start_ms, window_end_ms)
    warnings = _build_warnings(events)
    now = _build_now(events, state_by_instance, grind_instances)
    reconciliation = _build_reconciliation(
        events,
        closes,
        odd_closeby,
        scalps,
        close_by_layer,
        now_dt,
        grind_instances,
        window_start_ms,
        window_end_ms,
    )

    return {
        "generated_at": generated_at,
        "fleet": fleet,
        "fleet_label": fleet_label,
        "hours": hours,
        "now": now,
        "rolls": rolls,
        "ejections": ejections,
        "days": days,
        "warnings": warnings,
        "reconciliation": reconciliation,
    }


def _serialize_scalp_for_snapshot(scalp):
    row = dict(scalp)
    close_broker = row.get("close_time_broker")
    if isinstance(close_broker, datetime):
        row["close_time_broker"] = close_broker.isoformat()
    return row


def build_worker_ejection_snapshot(
    *,
    built_at,
    window_start_ms,
    window_end_ms,
    events,
    scalps,
    fill_logs,
):
    return {
        "built_at": built_at,
        "window_start_ms": window_start_ms,
        "window_end_ms": window_end_ms,
        "events": events,
        "scalps": [_serialize_scalp_for_snapshot(s) for s in scalps],
        "fill_logs": fill_logs,
    }


def load_ejection_rows_from_db(conn, window_start_ms, window_end_ms):
    recv_start = datetime.fromtimestamp(window_start_ms / 1000.0, tz=timezone.utc) - timedelta(
        days=1
    )
    recv_end = datetime.fromtimestamp(window_end_ms / 1000.0, tz=timezone.utc) + timedelta(
        days=1
    )
    events = []
    scalps = []
    fill_logs = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT instance_id, code, level, ea_time_ms, ticket, detail
            FROM ea_events
            WHERE ea_time_ms >= %s AND ea_time_ms < %s
            ORDER BY ea_time_ms
            """,
            (window_start_ms, window_end_ms),
        )
        for inst, code, level, ea_time_ms, ticket, detail in cur.fetchall():
            events.append({
                "instance_id": inst,
                "code": code,
                "level": level,
                "ea_time_ms": ea_time_ms,
                "ticket": ticket,
                "detail": detail,
            })

        cur.execute(
            """
            SELECT instance_id, direction, gross_pnl, ejected, rolled,
                   broker_utc_offset_s, account_login, close_time_broker,
                   entry_deal_ticket, exit_deal_ticket, layer_depth
            FROM scalp_history
            WHERE received_at >= %s AND received_at < %s
            """,
            (recv_start, recv_end),
        )
        for row in cur.fetchall():
            scalps.append({
                "instance_id": row[0],
                "direction": row[1],
                "gross_pnl": float(row[2]) if row[2] is not None else None,
                "ejected": row[3],
                "rolled": row[4],
                "broker_utc_offset_s": row[5],
                "account_login": row[6],
                "close_time_broker": row[7],
                "entry_deal_ticket": row[8],
                "exit_deal_ticket": row[9],
                "layer_depth": row[10],
            })

        cur.execute(
            """
            SELECT instance_id, deal_ticket, order_ticket, position_id,
                   entry_type, deal_type, side, layer_index, role,
                   profit, commission, swap, ea_time_ms
            FROM fill_logs
            WHERE ea_time_ms >= %s AND ea_time_ms < %s
              AND (
                entry_type IN ('OUT_BY', 'OUT')
                OR deal_type IN ('OUT_BY', 'OUT')
              )
            """,
            (window_start_ms, window_end_ms),
        )
        closing_rows = []
        position_ids = set()
        for row in cur.fetchall():
            (
                inst,
                deal_ticket,
                order_ticket,
                position_id,
                entry_type,
                deal_type,
                side,
                layer_index,
                role,
                profit,
                commission,
                swap,
                ea_ms,
            ) = row
            rec = {
                "instance_id": inst,
                "deal_ticket": deal_ticket,
                "order_ticket": order_ticket,
                "position_id": position_id,
                "entry_type": entry_type,
                "deal_type": deal_type,
                "side": side,
                "layer_index": layer_index,
                "role": role,
                "profit": float(profit) if profit is not None else None,
                "commission": float(commission) if commission is not None else None,
                "swap": float(swap) if swap is not None else None,
                "ea_time_ms": ea_ms,
            }
            closing_rows.append(rec)
            if position_id is not None:
                position_ids.add(position_id)

        if position_ids:
            cur.execute(
                """
                SELECT instance_id, deal_ticket, order_ticket, position_id,
                       entry_type, deal_type, side, layer_index, role,
                       profit, commission, swap, ea_time_ms
                FROM fill_logs
                WHERE position_id = ANY(%s)
                """,
                (list(position_ids),),
            )
            seen_deals = set()
            for row in cur.fetchall():
                deal_ticket = row[1]
                if deal_ticket in seen_deals:
                    continue
                seen_deals.add(deal_ticket)
                fill_logs.append({
                    "instance_id": row[0],
                    "deal_ticket": deal_ticket,
                    "order_ticket": row[2],
                    "position_id": row[3],
                    "entry_type": row[4],
                    "deal_type": row[5],
                    "side": row[6],
                    "layer_index": row[7],
                    "role": row[8],
                    "profit": float(row[9]) if row[9] is not None else None,
                    "commission": float(row[10]) if row[10] is not None else None,
                    "swap": float(row[11]) if row[11] is not None else None,
                    "ea_time_ms": row[12],
                })
        else:
            fill_logs = closing_rows
    return events, scalps, fill_logs


def _ejection_unavailable(view_age_s=None):
    return {"error": "ejection view unavailable", "view_age_s": view_age_s}


def ejection_views_for_fleets(
    redis_client,
    fleets,
    hours,
    view_key="fxmatrix:ejection:view",
):
    """Parse ejection snapshot once; build per-fleet views (same staleness as serve_ejection_from_redis)."""
    import redis

    hours = clamp_hours(hours)
    now_dt = datetime.now(timezone.utc)
    window_end_ms = int(now_dt.timestamp() * 1000)
    window_start_ms = window_end_ms - hours * 3600 * 1000
    generated_at = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        raw = redis_client.get(view_key)
    except redis.exceptions.ConnectionError:
        return None

    if not raw:
        return None

    try:
        snap = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    built_at = snap.get("built_at")
    view_age_s = None
    if isinstance(built_at, str) and built_at.strip():
        try:
            built_dt = datetime.fromisoformat(built_at.replace("Z", "+00:00"))
            if built_dt.tzinfo is None:
                built_dt = built_dt.replace(tzinfo=timezone.utc)
            view_age_s = max(0, int((now_dt - built_dt).total_seconds()))
        except ValueError:
            view_age_s = None

    if view_age_s is None or view_age_s > EJECTION_VIEW_MAX_AGE_S:
        return None

    events = snap.get("events") or []
    scalps = snap.get("scalps") or []
    fill_logs = snap.get("fill_logs") or []

    views = {}
    try:
        for fleet_entry in fleets:
            if fleet_entry.get("placeholder"):
                continue
            letter = fleet_entry.get("letter") or ""
            grind_instances = list(fleet_entry.get("instances") or [])
            state_by_instance = {}
            for inst in grind_instances:
                raw_state = redis_client.get(f"fxmatrix:state:{inst}")
                state_by_instance[inst] = _parse_live_heartbeat(raw_state, now_dt)
            views[letter] = build_ejection_view(
                generated_at=generated_at,
                fleet=letter,
                fleet_label="",
                hours=hours,
                grind_instances=grind_instances,
                events=events,
                scalps=scalps,
                fill_logs=fill_logs,
                state_by_instance=state_by_instance,
                now_dt=now_dt,
                window_start_ms=window_start_ms,
                window_end_ms=window_end_ms,
            )
    except redis.exceptions.ConnectionError:
        return None

    return views


def serve_ejection_from_redis(
    redis_client,
    hours,
    fleet,
    fleet_label,
    grind_instances,
    view_key="fxmatrix:ejection:view",
):
    import redis

    hours = clamp_hours(hours)
    now_dt = datetime.now(timezone.utc)
    window_end_ms = int(now_dt.timestamp() * 1000)
    window_start_ms = window_end_ms - hours * 3600 * 1000
    generated_at = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        raw = redis_client.get(view_key)
    except redis.exceptions.ConnectionError:
        return None, _ejection_unavailable(None)

    if not raw:
        return None, _ejection_unavailable(None)

    try:
        snap = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, _ejection_unavailable(None)

    built_at = snap.get("built_at")
    view_age_s = None
    if isinstance(built_at, str) and built_at.strip():
        try:
            built_dt = datetime.fromisoformat(built_at.replace("Z", "+00:00"))
            if built_dt.tzinfo is None:
                built_dt = built_dt.replace(tzinfo=timezone.utc)
            view_age_s = max(0, int((now_dt - built_dt).total_seconds()))
        except ValueError:
            view_age_s = None

    if view_age_s is None or view_age_s > EJECTION_VIEW_MAX_AGE_S:
        return None, _ejection_unavailable(view_age_s)

    events = snap.get("events") or []
    scalps = snap.get("scalps") or []
    fill_logs = snap.get("fill_logs") or []

    state_by_instance = {}
    try:
        for inst in grind_instances:
            raw_state = redis_client.get(f"fxmatrix:state:{inst}")
            state_by_instance[inst] = _parse_live_heartbeat(raw_state, now_dt)
    except redis.exceptions.ConnectionError:
        return None, _ejection_unavailable(view_age_s)

    payload = build_ejection_view(
        generated_at=generated_at,
        fleet=fleet,
        fleet_label=fleet_label,
        hours=hours,
        grind_instances=list(grind_instances),
        events=events,
        scalps=scalps,
        fill_logs=fill_logs,
        state_by_instance=state_by_instance,
        now_dt=now_dt,
        window_start_ms=window_start_ms,
        window_end_ms=window_end_ms,
    )
    payload["view_built_at"] = built_at
    payload["view_age_s"] = view_age_s
    return payload, None
