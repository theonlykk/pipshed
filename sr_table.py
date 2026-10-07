"""C137: scalps per roll (fxmatrix docs/research/scalps-per-roll.md s1, s4).

Per pair SIDE, over a window, a side realises e*S - (D - e)*R pips
(D = N*a), so it makes money only while S/R exceeds the break-even

    k* = (N*a - e + c) / (e - c)        (c = cost per close, pips)

which is N*a/e - 1 before costs. This module holds the counting rules and
the arithmetic. The archive worker calls `aggregate` on scalp_history and
ROLL_ACCEPTED rows every 60 s and publishes the result under SR_TABLE_KEY;
the web app joins it with each instance's live geometry through
`side_row`. Imported by both (it needs nothing from either).
"""
from datetime import datetime, timedelta, timezone

import ftmo_daily as fd

SR_TABLE_KEY = "fxmatrix:sr:table"
SR_TABLE_MAX_AGE_S = 300
MIN_ROLLS = 3
WINDOWS = ("today", "d5", "cycle")
D5_DAYS = 5

# Commission per closed layer (two IN deals), measured on the broker ledger
# 26-28 Sep (639 IN deals): FTMO 0.03 + 0.03, IC Markets 0.04 + 0.04.
# An account not listed here is reported as unknown, never guessed.
COMMISSION_PER_CLOSE_BY_ACCOUNT = {
    1514731800: 0.06,   # FTMO cycle 3
    1514878887: 0.06,   # FTMO-IC trial from 7 Oct 22:08Z (card 7 Oct: 84 closes, -$5.04)
    53066709: 0.08,     # IC Fleet B (box 1)
    53071896: 0.08,     # IC Fleet C (box 2)
    53077984: 0.08,     # IC Fleet D (wine-d): same Raw account type, checked on its ledger
}

# Cycle 3 ejected at cap instead of rolling: there an ejection is the roll.
CYCLE3_ACCOUNT = 1514731800

# The "cycle" window: the current regime per account (previous chat, 7 Oct
# ~23:00Z): IC since the gate build (the C91 running-report start), A since
# the FTMO-IC trial's attach.
REGIME_START_BY_ACCOUNT = {
    53066709: datetime(2026, 10, 7, 2, 25, tzinfo=timezone.utc),
    53071896: datetime(2026, 10, 7, 2, 25, tzinfo=timezone.utc),
    53077984: datetime(2026, 10, 7, 2, 25, tzinfo=timezone.utc),
    1514878887: datetime(2026, 10, 7, 22, 8, tzinfo=timezone.utc),
}


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def pip_multiplier(*prices):
    """10000 for 5-digit symbols, 100 when a price implies 3-digit (as app)."""
    for price in prices:
        if _num(price) and float(price) > 50:
            return 100
    return 10000


def signed_pips(direction, entry, exit_price):
    """Pips won (+) or lost (-) by one closed layer, or None."""
    if not _num(entry) or not _num(exit_price):
        return None
    d = str(direction or "").upper()
    if d == "LONG":
        move = float(exit_price) - float(entry)
    elif d == "SHORT":
        move = float(entry) - float(exit_price)
    else:
        return None
    return move * pip_multiplier(entry, exit_price)


def close_kind(rolled, ejected, account_login):
    """'roll', 'eject' or 'scalp' for one closed layer."""
    if rolled is True:
        return "roll"
    if ejected is True:
        try:
            on_cycle3 = account_login is not None and int(account_login) == CYCLE3_ACCOUNT
        except (TypeError, ValueError):
            on_cycle3 = False
        return "roll" if on_cycle3 else "eject"
    return "scalp"


def side_of(direction):
    d = str(direction or "").upper()
    return {"LONG": "L", "SHORT": "S"}.get(d)


def windows_for(now):
    """{'today': (start, end), 'd5': (start, end)} in UTC. today = the FTMO
    day holding `now`; d5 = from the start of the fifth most recent weekday
    FTMO day (today counts when it is a weekday) to the end of today."""
    today = fd.ftmo_day_of_utc(now)
    t0, t1 = fd.ftmo_day_bounds_utc(today)
    day = today
    found = 0
    first = today
    while found < D5_DAYS:
        if day.weekday() < 5:
            found += 1
            first = day
        day = day - timedelta(days=1)
    d0, _ = fd.ftmo_day_bounds_utc(first)
    return {"today": (t0, t1), "d5": (d0, t1)}


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_stats():
    return {"S": 0, "R": 0, "E": 0, "rolls_started": 0,
            "scalp_pips": 0.0, "roll_pips": 0.0, "eject_pips": 0.0}


def _in_windows(t, account_login, bounds):
    """The windows a time (and its account, for the cycle) falls in."""
    out = []
    if t is None:
        return out
    for name in ("today", "d5"):
        start, end = bounds[name]
        if start <= t < end:
            out.append(name)
    try:
        start = REGIME_START_BY_ACCOUNT.get(int(account_login)) if account_login is not None else None
    except (TypeError, ValueError):
        start = None
    if start is not None and start <= t < bounds["today"][1]:
        out.append("cycle")
    return out


def aggregate(rows, roll_events, now):
    """Counts per instance, side and window.

    rows: dicts with instance_id, account_login, direction, entry_price,
    exit_price, gross_pnl, close_utc (aware datetime), rolled, ejected.
    roll_events: (instance_id, side, received_at) for ROLL_ACCEPTED; the
    cycle window of a started roll uses the instance's account (from its
    newest close)."""
    bounds = windows_for(now)
    instances = {}
    acc_time = {}
    pv = {}

    def inst_entry(inst):
        if inst not in instances:
            parts = str(inst).split("_")
            instances[inst] = {"pair": parts[1] if len(parts) > 1 else None,
                               "account_login": None, "sides": {}, "pip_value": {}}
            pv[inst] = {w: [0.0, 0.0] for w in WINDOWS}
        return instances[inst]

    def cell(inst, side, win):
        sides = inst_entry(inst)["sides"]
        return sides.setdefault(side, {w: _empty_stats() for w in WINDOWS})[win]

    for row in rows:
        inst = row.get("instance_id")
        side = side_of(row.get("direction"))
        t = row.get("close_utc")
        if not inst or side is None or t is None:
            continue
        acc = row.get("account_login")
        entry = inst_entry(inst)
        if acc is not None and (inst not in acc_time or t >= acc_time[inst]):
            acc_time[inst] = t
            entry["account_login"] = int(acc)
        wins = _in_windows(t, acc, bounds)
        if not wins:
            continue
        kind = close_kind(row.get("rolled"), row.get("ejected"), acc)
        pips = signed_pips(row.get("direction"), row.get("entry_price"), row.get("exit_price"))
        usd = row.get("gross_pnl")
        for win in wins:
            c = cell(inst, side, win)
            key = {"scalp": "S", "roll": "R", "eject": "E"}[kind]
            c[key] += 1
            if pips is not None:
                c[{"scalp": "scalp_pips", "roll": "roll_pips", "eject": "eject_pips"}[kind]] += pips
                if _num(usd) and pips != 0:
                    pv[inst][win][0] += abs(float(usd))
                    pv[inst][win][1] += abs(pips)

    for inst, side, received_at in roll_events:
        if not inst or side not in ("L", "S") or received_at is None:
            continue
        acc = (instances.get(inst) or {}).get("account_login")
        for win in _in_windows(received_at, acc, bounds):
            cell(inst, side, win)["rolls_started"] += 1

    for inst, entry in instances.items():
        for sides in entry["sides"].values():
            for c in sides.values():
                for k in ("scalp_pips", "roll_pips", "eject_pips"):
                    c[k] = round(c[k], 1) + 0.0
        entry["pip_value"] = {w: (round(pv[inst][w][0] / pv[inst][w][1], 6) if pv[inst][w][1] > 0 else None)
                              for w in WINDOWS}

    return {
        "now": _iso(now),
        "windows": {
            "today": {"start": _iso(bounds["today"][0]), "end": _iso(bounds["today"][1]),
                      "label": f"FTMO day {fd.ftmo_day_of_utc(now).isoformat()}"},
            "d5": {"start": _iso(bounds["d5"][0]), "end": _iso(bounds["d5"][1]),
                   "label": "last 5 weekday FTMO days"},
            "cycle": {"starts": {str(a): _iso(s) for a, s in REGIME_START_BY_ACCOUNT.items()},
                      "label": "since the current regime started"},
        },
        "instances": instances,
    }


def k_star(cap, add, exit_, c_pips=0.0):
    """Break-even scalps per roll, or None (a dial missing or e <= c)."""
    if not _num(cap) or not _num(add) or not _num(exit_) or not _num(c_pips):
        return None
    if cap <= 0 or add <= 0:
        return None
    e = float(exit_)
    c = float(c_pips)
    if e - c <= 0:
        return None
    return (float(cap) * float(add) - e + c) / (e - c)


def _r2(x):
    return None if x is None else round(x, 2) + 0.0


def side_row(stats, cap, add, exit_, rate_usd, pip_value):
    """One displayed row: the window's counts with S/R, k* and the edge.

    rate_usd: the account's commission per close; pip_value: USD per pip
    per close. c is None when either is unknown; then k* (with costs), the
    edge and k actual are None and k* before costs is still shown."""
    stats = stats or _empty_stats()
    S, R = int(stats.get("S") or 0), int(stats.get("R") or 0)
    c = rate_usd / pip_value if _num(rate_usd) and _num(pip_value) and pip_value > 0 else None
    sr = S / R if R > 0 else None
    ks = k_star(cap, add, exit_, c) if c is not None else None
    kg = k_star(cap, add, exit_, 0.0)
    k_act = None
    if c is not None and S > 0 and R > 0:
        gain = stats["scalp_pips"] / S
        loss = -stats["roll_pips"] / R
        if gain - c > 0:
            k_act = (loss + c) / (gain - c)
    edge = sr - ks if sr is not None and ks is not None else None
    return {
        "S": S, "R": R, "E": int(stats.get("E") or 0),
        "rolls_started": int(stats.get("rolls_started") or 0),
        "sr": _r2(sr), "k_star": _r2(ks), "k_star_gross": _r2(kg), "k_actual": _r2(k_act),
        "edge": _r2(edge),
        "realised_pips": round(float(stats.get("scalp_pips") or 0.0) + float(stats.get("roll_pips") or 0.0), 1) + 0.0,
        "c_pips": _r2(c), "grey": R < MIN_ROLLS,
    }
