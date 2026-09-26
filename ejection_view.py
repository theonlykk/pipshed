"""Passive ejection telemetry view builder (C56). Pure functions, no Flask/Redis I/O."""

from datetime import datetime, timedelta, timezone

import ftmo_daily as fd


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


def commission_position_ids(scalp, fill_rows):
    """Q1 position set for commission/swap (de-duplicated position_id values)."""
    ids = set()
    by_deal = {}
    by_order = {}
    for row in fill_rows:
        if row.get("instance_id") and scalp.get("instance_id"):
            if row["instance_id"] != scalp["instance_id"]:
                continue
        dt = row.get("deal_ticket")
        if dt is not None:
            by_deal[dt] = row
        ot = row.get("order_ticket")
        if ot is not None:
            by_order.setdefault(ot, []).append(row)

    for ticket in (scalp.get("entry_deal_ticket"), scalp.get("exit_deal_ticket")):
        if ticket is None:
            continue
        deal = by_deal.get(ticket)
        if deal and deal.get("position_id") is not None:
            ids.add(deal["position_id"])

    exit_deal = scalp.get("exit_deal_ticket")
    exit_order = None
    if exit_deal in by_deal:
        exit_order = by_deal[exit_deal].get("order_ticket")
    if exit_order is not None:
        for row in by_order.get(exit_order, []):
            if row.get("position_id") is not None:
                ids.add(row["position_id"])
    return ids


def layer_realised_from_fills(scalp, fill_rows):
    gross_val = scalp.get("gross_pnl")
    gross = float(gross_val) if gross_val is not None else 0.0
    pos_ids = commission_position_ids(scalp, fill_rows)
    commission = 0.0
    swap = 0.0
    seen_deals = set()
    for row in fill_rows:
        if scalp.get("instance_id") and row.get("instance_id"):
            if row["instance_id"] != scalp["instance_id"]:
                continue
        if pos_ids and row.get("position_id") not in pos_ids:
            continue
        deal_ticket = row.get("deal_ticket")
        if deal_ticket in seen_deals:
            continue
        if deal_ticket is not None:
            seen_deals.add(deal_ticket)
        if row.get("commission") is not None:
            commission += float(row["commission"])
        if row.get("swap") is not None:
            swap += float(row["swap"])
    net = gross + commission + swap
    return (
        gross,
        round(commission, 2),
        round(swap, 2),
        round(net, 2),
    )


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


def _find_scalp_for_order(scalps, fill_rows, ticket, instance_id, flag):
    for scalp in scalps:
        if scalp.get("instance_id") != instance_id:
            continue
        if flag == "rolled" and not scalp.get("rolled"):
            continue
        if flag == "ejected" and not scalp.get("ejected"):
            continue
        for row in fill_rows:
            if row.get("instance_id") != instance_id:
                continue
            if row.get("order_ticket") == ticket:
                return scalp
    for scalp in scalps:
        if scalp.get("instance_id") != instance_id:
            continue
        if flag == "rolled" and scalp.get("rolled"):
            return scalp
        if flag == "ejected" and scalp.get("ejected"):
            return scalp
    return None


def _minutes_between(ms_a, ms_b):
    if ms_a is None or ms_b is None:
        return None
    return int(round((ms_b - ms_a) / 60000.0))


def _build_roll_rows(events, scalps, fill_rows):
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
            scalp = _find_scalp_for_order(scalps, fill_rows, ticket, inst, "rolled")
            if scalp:
                gross, comm, swap, net = layer_realised_from_fills(scalp, fill_rows)
                realised = {"gross": gross, "commission": comm, "swap": swap, "net": net}
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


def _build_ejection_rows(events, scalps, fill_rows):
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
            scalp = _find_scalp_for_order(
                scalps, fill_rows, ticket, acc.get("instance_id"), "ejected"
            )
            if scalp:
                gross, comm, swap, net = layer_realised_from_fills(scalp, fill_rows)
                realised = {"gross": gross, "commission": comm, "swap": swap, "net": net}
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


def _build_days(events, scalps, fill_rows, grind_instances, window_start_ms, window_end_ms):
    blocks = []
    for ftmo_day in _days_in_window(window_start_ms, window_end_ms):
        day_block = {"ftmo_day": ftmo_day.isoformat(), "instances": []}
        for inst in grind_instances:
            inst_block = {"instance_id": inst, "sides": []}
            for side in ("L", "S"):
                side_scalps = [
                    s
                    for s in scalps
                    if s.get("instance_id") == inst
                    and not s.get("rolled")
                    and not s.get("ejected")
                    and _side_code(direction=s.get("direction")) == side
                    and _scalp_in_ftmo_day(s, ftmo_day)
                ]
                gross = sum(float(s.get("gross_pnl") or 0) for s in side_scalps)
                net = 0.0
                comm_total = 0.0
                swap_total = 0.0
                for s in side_scalps:
                    _, c, sw, n = layer_realised_from_fills(s, fill_rows)
                    net += n
                    comm_total += c
                    swap_total += sw

                roll_filled = [
                    s
                    for s in scalps
                    if s.get("instance_id") == inst
                    and s.get("rolled")
                    and _side_code(direction=s.get("direction")) == side
                    and _scalp_in_ftmo_day(s, ftmo_day)
                ]
                roll_net = 0.0
                for s in roll_filled:
                    _, _, _, n = layer_realised_from_fills(s, fill_rows)
                    roll_net += n
                roll_accepted = sum(
                    1
                    for e in events
                    if e.get("instance_id") == inst
                    and e.get("code") == "ROLL_ACCEPTED"
                    and _side_code(e.get("detail")) == side
                    and fd.ftmo_day_of_utc(
                        datetime.fromtimestamp(
                            e["ea_time_ms"] / 1000.0, tz=timezone.utc
                        )
                    )
                    == ftmo_day
                )

                eject_filled = [
                    s
                    for s in scalps
                    if s.get("instance_id") == inst
                    and s.get("ejected")
                    and _side_code(direction=s.get("direction")) == side
                    and _scalp_in_ftmo_day(s, ftmo_day)
                ]
                eject_net = 0.0
                for s in eject_filled:
                    _, _, _, n = layer_realised_from_fills(s, fill_rows)
                    eject_net += n

                side_block = {
                    "side": side,
                    "scalps": {
                        "count": len(side_scalps),
                        "gross": round(gross, 2),
                        "net": round(net, 2),
                    },
                    "rolls": {
                        "accepted": roll_accepted,
                        "filled": len(roll_filled),
                        "net": round(roll_net, 2),
                    },
                    "ejections": {
                        "filled": len(eject_filled),
                        "net": round(eject_net, 2),
                    },
                    "commission": round(comm_total, 2),
                    "swap": round(swap_total, 2),
                    "closed_net": round(net + roll_net + eject_net, 2),
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


def _build_now(events, state_by_instance, grind_instances):
    now = {}
    for inst in grind_instances:
        now[inst] = {}
        state = state_by_instance.get(inst) or {}
        inst_events = [e for e in events if e.get("instance_id") == inst]
        for side in ("L", "S"):
            layers = []
            state_layers = state.get("layers") or []
            for layer in state_layers:
                layer_side = _side_code(detail=layer)
                if layer_side is not None and layer_side != side:
                    continue
                if layer_side is None and side != "L":
                    continue
                layers.append({
                    "layer_index": layer.get("layer_index"),
                    "ticket": layer.get("ticket"),
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
            stranded_at = None
            for ev in inst_events:
                if ev.get("code") != "ROLL_STRANDED":
                    continue
                detail = ev.get("detail") or {}
                if _side_code(detail) == side:
                    stranded_at = ea_ms_to_iso(ev.get("ea_time_ms"))
            now[inst][side] = {
                "depth": state.get("depth"),
                "max_layers": state.get("max_layers"),
                "rolled": rolled_state,
                "lowest_effective": state.get("lowest_effective"),
                "market": state.get("market"),
                "last_stranded_at": stranded_at,
                "state_age_s": state.get("age_s"),
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


def _build_reconciliation(events, rolls_rows, eject_rows, now_dt):
    blocks = []
    by_inst = {}
    for ev in events:
        by_inst.setdefault(ev.get("instance_id"), []).append(ev)

    for inst, evlist in sorted(by_inst.items()):
        roll_mismatch = None
        eject_mismatch = None
        accepted_unfilled = []
        refused = {}

        roll_accepted = {
            e.get("ticket"): e
            for e in evlist
            if e.get("code") == "ROLL_ACCEPTED"
        }
        roll_filled = {e.get("ticket") for e in evlist if e.get("code") == "ROLL_FILLED"}
        roll_refused = {e.get("ticket") for e in evlist if e.get("code") == "ROLL_REFUSED"}
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
                reason = (ev.get("detail") or {}).get("reason") or "unknown"
                refused[reason] = refused.get(reason, 0) + 1
            if ev.get("code") == "EJECT_REFUSED":
                reason = (ev.get("detail") or {}).get("reason") or "unknown"
                refused[reason] = refused.get(reason, 0) + 1

        blocks.append({
            "instance_id": inst,
            "roll_mismatch": roll_mismatch,
            "eject_mismatch": eject_mismatch,
            "accepted_unfilled": accepted_unfilled,
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

    rolls = _build_roll_rows(events, scalps, fill_logs)
    ejections = _build_ejection_rows(events, scalps, fill_logs)
    days = _build_days(
        events, scalps, fill_logs, grind_instances, window_start_ms, window_end_ms
    )
    warnings = _build_warnings(events)
    now = _build_now(events, state_by_instance, grind_instances)
    reconciliation = _build_reconciliation(events, rolls, ejections, now_dt)

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


def _parse_state_payload(raw):
    if not raw:
        return {}
    try:
        import json

        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    layers_raw = data.get("layers") or []
    layers = []
    for layer in layers_raw:
        if not isinstance(layer, dict):
            continue
        layers.append({
            "layer_index": layer.get("layer_index"),
            "ticket": layer.get("ticket"),
            "entry": layer.get("entry"),
            "virtual_level": layer.get("virtual_level"),
            "exit_target": layer.get("exit_target"),
        })
    return {
        "depth": data.get("depth"),
        "max_layers": data.get("max_layers"),
        "lowest_effective": data.get("lowest_effective"),
        "market": data.get("market"),
        "layers": layers,
    }


def fetch_ejection_view(conn, hours, fleet, fleet_label, grind_instances, redis_client=None):
    hours = clamp_hours(hours)
    now_dt = datetime.now(timezone.utc)
    window_end_ms = int(now_dt.timestamp() * 1000)
    window_start_ms = window_end_ms - hours * 3600 * 1000
    generated_at = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    if conn is None:
        return build_ejection_view(
            generated_at=generated_at,
            fleet=fleet,
            fleet_label=fleet_label,
            hours=hours,
            grind_instances=list(grind_instances),
            events=[],
            scalps=[],
            fill_logs=[],
            state_by_instance={},
            now_dt=now_dt,
            window_start_ms=window_start_ms,
            window_end_ms=window_end_ms,
        )

    recv_start = datetime.fromtimestamp(window_start_ms / 1000.0, tz=timezone.utc) - timedelta(
        days=1
    )
    recv_end = datetime.fromtimestamp(window_end_ms / 1000.0, tz=timezone.utc) + timedelta(
        days=1
    )
    inst_tuple = tuple(grind_instances)
    events = []
    scalps = []
    fill_logs = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT instance_id, code, level, ea_time_ms, ticket, detail
            FROM ea_events
            WHERE ea_time_ms >= %s AND ea_time_ms < %s
              AND instance_id = ANY(%s)
            ORDER BY ea_time_ms
            """,
            (window_start_ms, window_end_ms, list(inst_tuple)),
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
              AND instance_id = ANY(%s)
            """,
            (recv_start, recv_end, list(inst_tuple)),
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
                   commission, swap
            FROM fill_logs
            WHERE ea_time_ms >= %s AND ea_time_ms < %s
              AND instance_id = ANY(%s)
            """,
            (window_start_ms, window_end_ms, list(inst_tuple)),
        )
        for inst, deal_ticket, order_ticket, position_id, commission, swap in cur.fetchall():
            fill_logs.append({
                "instance_id": inst,
                "deal_ticket": deal_ticket,
                "order_ticket": order_ticket,
                "position_id": position_id,
                "commission": float(commission) if commission is not None else None,
                "swap": float(swap) if swap is not None else None,
            })

    state_by_instance = {}
    if redis_client is not None:
        for inst in grind_instances:
            raw = redis_client.get(f"fxmatrix:state:{inst}")
            parsed = _parse_state_payload(raw)
            parsed["age_s"] = None
            state_by_instance[inst] = parsed
            if parsed.get("layers"):
                state_by_instance[inst]["source"] = "state"
            else:
                state_by_instance[inst]["source"] = "events"

    return build_ejection_view(
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
