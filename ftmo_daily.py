"""FTMO calendar day helpers and daily snapshot derivations (ADR-159). Pure functions, no I/O."""

from datetime import date, datetime, timedelta, timezone

WARN_CRITICAL_ALLOW = frozenset({
    "STARTUP_EXIT_SHORTFALL",
    "QUARANTINE_ENTER",
    "WARN_API_ENTRY_STOP",
    "ROLL_STRANDED",
    "ROLL_CLOSING_STUCK",
})


def _last_sunday(year, month):
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    d = next_month - timedelta(days=1)
    while d.weekday() != 6:
        d -= timedelta(days=1)
    return d


def _cest_window_utc(year):
    march = _last_sunday(year, 3)
    october = _last_sunday(year, 10)
    start = datetime(march.year, march.month, march.day, 1, 0, tzinfo=timezone.utc)
    end = datetime(october.year, october.month, october.day, 1, 0, tzinfo=timezone.utc)
    return start, end


def _in_cest(utc_dt):
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    for year in (utc_dt.year - 1, utc_dt.year, utc_dt.year + 1):
        start, end = _cest_window_utc(year)
        if start <= utc_dt < end:
            return True
    return False


def _prague_midnight_utc(day):
    utc_cet = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - timedelta(hours=1)
    if _in_cest(utc_cet):
        return utc_cet - timedelta(hours=1)
    return utc_cet


def ftmo_day_bounds_utc(day):
    start = _prague_midnight_utc(day)
    end = _prague_midnight_utc(day + timedelta(days=1))
    return start, end


def ftmo_day_of_utc(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    base = dt.date()
    for candidate in (base - timedelta(days=1), base, base + timedelta(days=1)):
        start, end = ftmo_day_bounds_utc(candidate)
        if start <= dt < end:
            return candidate
    raise ValueError(f"no FTMO day contains {dt!r}")


def parse_ftmo_day(text):
    raw = str(text).strip()
    for fmt in ("%Y.%m.%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"invalid ftmo day: {text!r}")


def _parse_bool(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


def _parse_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_numeric(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_account_login(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def snapshot_row_from_detail(detail):
    if not isinstance(detail, dict):
        return None
    account_login = _parse_account_login(detail.get("account_login"))
    ftmo_day_raw = detail.get("ftmo_day")
    if account_login is None or ftmo_day_raw is None:
        return None
    try:
        ftmo_day = parse_ftmo_day(ftmo_day_raw)
    except ValueError:
        return None

    start_known = _parse_bool(detail.get("start_known"))
    hide_start_derived = start_known is False

    def money(key):
        if hide_start_derived and key in (
            "equity_start",
            "inventory_pnl",
            "total",
            "swap_day",
        ):
            return None
        return _parse_numeric(detail.get(key))

    return {
        "account_login": account_login,
        "ftmo_day": ftmo_day,
        "balance_start": _parse_numeric(detail.get("balance_start")),
        "equity_start": money("equity_start"),
        "balance_end": _parse_numeric(detail.get("balance_end")),
        "equity_end": _parse_numeric(detail.get("equity_end")),
        "realised": _parse_numeric(detail.get("realised")),
        "nontrade": _parse_numeric(detail.get("nontrade")),
        "inventory_pnl": money("inventory_pnl"),
        "total": money("total"),
        "swap_day": money("swap_day"),
        "positions_long": _parse_int(detail.get("positions_long")),
        "positions_short": _parse_int(detail.get("positions_short")),
        "orders": _parse_int(detail.get("orders")),
        "guard_total": _parse_int(detail.get("guard_total")),
        "guard_age_s": _parse_int(detail.get("guard_age_s")),
        "breaker_tripped": _parse_bool(detail.get("breaker_tripped")),
        "premidnight_seen": _parse_bool(detail.get("premidnight_seen")),
        "broker_utc_offset_s": _parse_int(detail.get("broker_utc_offset_s")),
        "start_known": start_known,
        "balance_start_source": detail.get("balance_start_source"),
    }


def _scalp_utc_close(close_time_broker, broker_utc_offset_s):
    if close_time_broker is None or broker_utc_offset_s is None:
        return None
    if isinstance(close_time_broker, datetime):
        naive = close_time_broker.replace(tzinfo=None)
    else:
        text = str(close_time_broker).rstrip("Z")
        if "T" in text:
            naive = datetime.fromisoformat(text)
        else:
            naive = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    return naive.replace(tzinfo=timezone.utc) - timedelta(seconds=int(broker_utc_offset_s))


def derive_counts(events, scalps, start, end, account_login):
    ejections_auto = 0
    ejections_command = 0
    eject_filled_events = 0
    rolls_accepted = 0
    rolls_refused = 0
    roll_filled_events = 0
    roll_stranded_warns = 0
    roll_stuck_warns = 0
    carry_clamps = 0
    critical_events = 0

    for code, level, detail in events:
        if level == "CRITICAL":
            critical_events += 1
        if code == "EJECT_ACCEPTED" and isinstance(detail, dict):
            source = detail.get("source")
            if source == "auto":
                ejections_auto += 1
            elif source == "command":
                ejections_command += 1
        elif code == "EJECT_FILLED":
            eject_filled_events += 1
        elif code == "ROLL_ACCEPTED":
            rolls_accepted += 1
        elif code == "ROLL_REFUSED":
            rolls_refused += 1
        elif code == "ROLL_FILLED":
            roll_filled_events += 1
        elif code == "ROLL_STRANDED":
            roll_stranded_warns += 1
        elif code == "ROLL_CLOSING_STUCK":
            roll_stuck_warns += 1
        elif code in ("CARRY_PASS_SUMMARY", "CARRY_PASS_INCOMPLETE") and isinstance(
            detail, dict
        ):
            clamped = detail.get("clamped")
            if clamped is not None:
                try:
                    carry_clamps += int(clamped)
                except (TypeError, ValueError):
                    pass

    ejected_fills = 0
    ejected_realised = 0.0
    ejected_realised_has = False
    rolled_fills = 0
    rolled_realised = 0.0
    rolled_realised_has = False
    for row in scalps:
        if len(row) >= 6:
            (
                close_time_broker,
                broker_utc_offset_s,
                scalp_account,
                gross_pnl,
                ejected,
                rolled,
            ) = row[:6]
        else:
            close_time_broker, broker_utc_offset_s, scalp_account, gross_pnl = row
            ejected, rolled = True, False
        if broker_utc_offset_s is None:
            continue
        if scalp_account is not None and scalp_account != account_login:
            continue
        utc_close = _scalp_utc_close(close_time_broker, broker_utc_offset_s)
        if utc_close is None or not (start <= utc_close < end):
            continue
        if rolled:
            rolled_fills += 1
            if gross_pnl is not None:
                rolled_realised += float(gross_pnl)
                rolled_realised_has = True
        elif ejected:
            ejected_fills += 1
            if gross_pnl is not None:
                ejected_realised += float(gross_pnl)
                ejected_realised_has = True

    return {
        "ejections_auto": ejections_auto,
        "ejections_command": ejections_command,
        "eject_filled_events": eject_filled_events,
        "carry_clamps": carry_clamps,
        "critical_events": critical_events,
        "ejected_fills": ejected_fills,
        "ejected_realised": ejected_realised if ejected_realised_has else None,
        "eject_mismatch": ejected_fills - eject_filled_events,
        "rolls_accepted": rolls_accepted,
        "rolls_refused": rolls_refused,
        "roll_filled_events": roll_filled_events,
        "rolled_fills": rolled_fills,
        "rolled_realised": rolled_realised if rolled_realised_has else None,
        "roll_mismatch": rolled_fills - roll_filled_events,
        "roll_stranded_warns": roll_stranded_warns,
        "roll_stuck_warns": roll_stuck_warns,
    }


def critical_groups(rows, now):
    filtered = []
    for instance_id, level, code, received_at in rows:
        if level == "CRITICAL":
            filtered.append((instance_id, level, code, received_at))
        elif level == "WARN" and code in WARN_CRITICAL_ALLOW:
            filtered.append((instance_id, level, code, received_at))

    groups = {}
    for instance_id, level, code, received_at in filtered:
        key = (instance_id, level, code)
        if key not in groups:
            groups[key] = {
                "instance_id": instance_id,
                "level": level,
                "code": code,
                "count": 0,
                "first_at": received_at,
                "last_at": received_at,
            }
        g = groups[key]
        g["count"] += 1
        if received_at < g["first_at"]:
            g["first_at"] = received_at
        if received_at > g["last_at"]:
            g["last_at"] = received_at

    out = list(groups.values())
    out.sort(
        key=lambda r: (
            0 if r["level"] == "CRITICAL" else 1,
            -(r["last_at"].timestamp() if hasattr(r["last_at"], "timestamp") else 0),
        )
    )
    return out


def s4_counts(fill_rows, eject_tickets, day_of):
    by_instance_ticket = {}
    for instance_id, order_ticket, position_id, ea_time_ms in fill_rows:
        day = ftmo_day_of_utc(datetime.fromtimestamp(ea_time_ms / 1000.0, tz=timezone.utc))
        if day != day_of:
            continue
        key = (instance_id, order_ticket)
        by_instance_ticket.setdefault(key, []).append(position_id)

    counts = {}
    for (instance_id, order_ticket), positions in by_instance_ticket.items():
        if any(pid in eject_tickets for pid in positions):
            continue
        counts[(instance_id, day_of)] = counts.get((instance_id, day_of), 0) + 1
    return counts
