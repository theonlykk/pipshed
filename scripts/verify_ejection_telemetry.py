"""Verification for C56 passive ejection telemetry (rolls + ejections).

Scratch PostgreSQL only via VERIFY_DATABASE_URL (never production).
"""
import contextlib
import io
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

import psycopg2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import ftmo_daily as fd  # noqa: E402

URL = os.environ.get("VERIFY_DATABASE_URL")
FIXTURE_INSTANCE = "GRIND_GBPUSD_OPTB"
FIXTURE_ACCOUNT = 1
FIXTURE_SESSION = "c56-fixture-sess"
FTMO_D = date(2026, 9, 24)
OUTSIDER_INSTANCE = "GRIND_GBPUSD_OPT"

DAILY_ROLL_COLS = (
    "rolls_accepted",
    "rolls_refused",
    "roll_filled_events",
    "rolled_fills",
    "rolled_realised",
    "roll_mismatch",
    "roll_stranded_warns",
    "roll_stuck_warns",
)

EJECTION_TOP_KEYS = (
    "generated_at",
    "fleet",
    "fleet_label",
    "hours",
    "now",
    "rolls",
    "ejections",
    "days",
    "warnings",
    "reconciliation",
)


def _ms(iso_z):
    dt = datetime.fromisoformat(iso_z.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def _apply_base_migrations(cur):
    cur.execute("SELECT to_regclass('public.ea_events')")
    if cur.fetchone()[0] is not None:
        return
    for name in ("001_archive_phase1.sql", "002_adr159_daily.sql", "003_adr160_gated.sql"):
        with open(os.path.join(ROOT, "migrations", name), encoding="ascii") as f:
            cur.execute(f.read())


def _apply_004(cur):
    path = os.path.join(ROOT, "migrations", "004_c56_rolls.sql")
    if not os.path.isfile(path):
        return False
    cur.execute("SELECT 1 FROM schema_migrations WHERE version = %s", ("004_c56_rolls",))
    if cur.fetchone():
        return True
    with open(path, encoding="ascii") as f:
        cur.execute(f.read())
    cur.execute(
        "INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING",
        ("004_c56_rolls",),
    )
    return True


def _day_bounds_ms(day):
    start, end = fd.ftmo_day_bounds_utc(day)
    return start, end, int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _seed_session(cur):
    cur.execute(
        "INSERT INTO config_events (instance_id, magic, session_id, seq, ea_time_ms,"
        " received_at, event, account_login) VALUES (%s, 1, %s, 1, 0, now(), 'startup', %s)",
        (FIXTURE_INSTANCE, FIXTURE_SESSION, FIXTURE_ACCOUNT),
    )


def _insert_ea(cur, seq, code, level, ea_time_ms, ticket, detail):
    cur.execute(
        "INSERT INTO ea_events (instance_id, magic, session_id, seq, ea_time_ms, received_at,"
        " level, code, reason, ticket, detail) VALUES (%s, 1, %s, %s, %s, now(), %s, %s, '', %s, %s)",
        (
            FIXTURE_INSTANCE,
            FIXTURE_SESSION,
            seq,
            ea_time_ms,
            level,
            code,
            ticket,
            json.dumps(detail) if detail is not None else None,
        ),
    )


def _insert_scalp(
    cur,
    seq,
    direction,
    gross,
    close_utc,
    *,
    rolled=False,
    ejected=False,
    entry_deal=100,
    exit_deal=101,
    layer=0,
):
    offset_s = 0
    broker_close = close_utc.replace(tzinfo=None)
    cur.execute(
        "INSERT INTO scalp_history (instance_id, instrument, direction, entry_price, exit_price,"
        " gross_pnl, layer_depth, stack_depth, entry_deal_ticket, exit_deal_ticket,"
        " close_time_broker, source, received_at, broker_utc_offset_s, account_login,"
        " ejected, rolled) VALUES (%s, 'GBPUSD', %s, 1.33, 1.3305, %s, %s, 1,"
        " %s, %s, %s, 'test', %s, %s, %s, %s, %s)",
        (
            FIXTURE_INSTANCE,
            direction,
            gross,
            layer,
            entry_deal,
            exit_deal,
            broker_close,
            close_utc,
            offset_s,
            FIXTURE_ACCOUNT,
            ejected if ejected else None,
            rolled if rolled else None,
        ),
    )


def _insert_out_by(cur, seq, order_ticket, position_id, ea_time_ms):
    cur.execute(
        "INSERT INTO fill_logs (instance_id, magic, session_id, seq, ea_time_ms, received_at,"
        " deal_ticket, order_ticket, position_id, entry_type, deal_type, side,"
        " profit, swap, commission) VALUES (%s, 1, %s, %s, %s, now(), %s, %s, %s,"
        " 'OUT_BY', 'sell', 'buy', 0, 0, -0.07)",
        (FIXTURE_INSTANCE, FIXTURE_SESSION, seq, ea_time_ms, 5000 + seq, order_ticket, position_id),
    )


def seed_full_fixture(cur):
    _apply_base_migrations(cur)
    _apply_004(cur)
    for tbl in ("fill_logs", "scalp_history", "ea_events", "config_events", "daily_snapshots"):
        cur.execute(f"DELETE FROM {tbl}")
    _seed_session(cur)
    start, end, start_ms, end_ms = _day_bounds_ms(FTMO_D)
    mid = start + (end - start) / 2
    t_scalp = int(mid.timestamp() * 1000)

    seq = 0
    scalp_specs = [
        ("LONG", 0.50, 6001, 6002),
        ("LONG", 0.50, 6003, 6004),
        ("LONG", 0.50, 6005, 6006),
        ("SHORT", 0.50, 6007, 6008),
    ]
    for direction, gross, entry_d, exit_d in scalp_specs:
        seq += 1
        _insert_out_by(cur, seq, 1000 + seq, entry_d, t_scalp + seq)
        seq += 1
        _insert_out_by(cur, seq, 1000 + seq, exit_d, t_scalp + seq + 1)
        close_utc = datetime.fromtimestamp(t_scalp / 1000.0, tz=timezone.utc) + timedelta(minutes=seq)
        _insert_scalp(cur, seq, direction, gross, close_utc, entry_deal=entry_d, exit_deal=exit_d)

    roll_accept_ms = _ms("2026-09-24T10:00:00Z")
    roll_fill_ms = _ms("2026-09-24T10:17:00Z")
    seq += 1
    _insert_ea(
        cur,
        seq,
        "ROLL_ACCEPTED",
        "INFO",
        roll_accept_ms,
        9001,
        {
            "side": "L",
            "layer_index": 0,
            "entry": 1.33,
            "level": 1.326,
            "target": 1.3265,
            "cost_pips": 35.0,
            "clamped": False,
            "source": "live",
        },
    )
    seq += 1
    _insert_ea(cur, seq, "ROLL_FILLED", "INFO", roll_fill_ms, 9001, {"level": 1.326})
    seq += 1
    _insert_out_by(cur, seq, 9001, 7001, roll_fill_ms)
    seq += 1
    _insert_out_by(cur, seq, 9001, 7002, roll_fill_ms + 1)
    roll_close = datetime(2026, 9, 24, 10, 20, tzinfo=timezone.utc)
    _insert_scalp(
        cur,
        seq,
        "LONG",
        -3.50,
        roll_close,
        rolled=True,
        entry_deal=7001,
        exit_deal=7002,
        layer=0,
    )
    for deal_ticket, pos, comm, swap in (
        (7001, 7001, -0.07, 0),
        (7002, 7001, -0.07, -0.20),
        (7003, 7002, -0.07, 0),
        (7004, 7002, -0.07, 0),
    ):
        seq += 1
        cur.execute(
            "INSERT INTO fill_logs (instance_id, magic, session_id, seq, ea_time_ms, received_at,"
            " deal_ticket, order_ticket, position_id, entry_type, deal_type, side,"
            " profit, swap, commission) VALUES (%s, 1, %s, %s, %s, now(), %s, %s, %s,"
            " 'IN', 'buy', 'buy', 0, %s, %s)",
            (
                FIXTURE_INSTANCE,
                FIXTURE_SESSION,
                seq,
                roll_fill_ms,
                deal_ticket,
                9001,
                pos,
                swap,
                comm,
            ),
        )

    seq += 1
    _insert_ea(
        cur,
        seq,
        "ROLL_REFUSED",
        "INFO",
        roll_accept_ms + 1000,
        9002,
        {"reason": "MODIFY_FAILED", "source": "live"},
    )
    seq += 1
    _insert_ea(
        cur,
        seq,
        "ROLL_STRANDED",
        "WARN",
        roll_accept_ms + 2000,
        0,
        {"side": "L", "depth": 1},
    )

    eject_accept_ms = _ms("2026-09-24T11:00:00Z")
    eject_fill_ms = _ms("2026-09-24T11:05:00Z")
    seq += 1
    _insert_ea(cur, seq, "EJECT_ACCEPTED", "INFO", eject_accept_ms, 9003, {"source": "auto"})
    seq += 1
    _insert_ea(cur, seq, "EJECT_FILLED", "INFO", eject_fill_ms, 9003, {"offset": 0})
    seq += 1
    _insert_out_by(cur, seq, 9003, 8001, eject_fill_ms)
    seq += 1
    _insert_out_by(cur, seq, 9003, 8002, eject_fill_ms + 1)
    eject_close = datetime(2026, 9, 24, 11, 10, tzinfo=timezone.utc)
    _insert_scalp(
        cur,
        seq,
        "LONG",
        -1.00,
        eject_close,
        ejected=True,
        entry_deal=8001,
        exit_deal=8002,
    )

    seq += 1
    cur.execute(
        "INSERT INTO ea_events (instance_id, magic, session_id, seq, ea_time_ms, received_at,"
        " level, code, reason, ticket, detail) VALUES (%s, 1, %s, %s, %s, now(), 'INFO',"
        " 'EJECT_ACCEPTED', '', %s, %s)",
        (
            OUTSIDER_INSTANCE,
            FIXTURE_SESSION,
            seq,
            eject_accept_ms,
            9999,
            json.dumps({"source": "auto"}),
        ),
    )

    return start, end, start_ms, end_ms


def check_et1():
    if not URL:
        raise AssertionError("VERIFY_DATABASE_URL not set")
    conn = psycopg2.connect(URL)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            _apply_base_migrations(cur)
            has_004 = _apply_004(cur)
            if not has_004:
                raise AssertionError("migration 004_c56_rolls.sql missing or empty")
            cur.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name = 'scalp_history' AND column_name = 'rolled'"
            )
            if cur.fetchone() is None:
                raise AssertionError("scalp_history.rolled missing")
            cur.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name = 'daily_snapshots'"
            )
            cols = {r[0] for r in cur.fetchall()}
            missing = [c for c in DAILY_ROLL_COLS if c not in cols]
            if missing:
                raise AssertionError(f"daily_snapshots missing {missing}")
    finally:
        conn.close()
    return "004 adds scalp_history.rolled and 8 daily columns"


def check_et2():
    if not URL:
        raise AssertionError("VERIFY_DATABASE_URL not set")
    import archive_worker as aw

    conn = psycopg2.connect(URL)
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            _apply_base_migrations(cur)
            _apply_004(cur)
            cur.execute("DELETE FROM scalp_history")
            _seed_session(cur)
            item = json.dumps({
                "type": "scalp",
                "instance_id": FIXTURE_INSTANCE,
                "session_id": FIXTURE_SESSION,
                "received_at": "2026-09-24T12:00:00+00:00",
                "event": {
                    "close_time": "2026-09-24 12:00:00",
                    "instrument": "GBPUSD",
                    "direction": "LONG",
                    "entry_price": 1.33,
                    "exit_price": 1.3305,
                    "gross_pnl": 1.0,
                    "layer_depth": 0,
                    "stack_depth": 1,
                    "rolled": True,
                },
            })
            aw.insert_single(conn, item)
            conn.commit()
            cur.execute(
                "SELECT rolled FROM scalp_history WHERE instance_id = %s ORDER BY id DESC LIMIT 1",
                (FIXTURE_INSTANCE,),
            )
            if cur.fetchone()[0] is not True:
                raise AssertionError("rolled:true not stored")
            item2 = json.dumps({
                "type": "scalp",
                "instance_id": FIXTURE_INSTANCE,
                "session_id": FIXTURE_SESSION,
                "received_at": "2026-09-24T12:01:00+00:00",
                "event": {
                    "close_time": "2026-09-24 12:01:00",
                    "instrument": "GBPUSD",
                    "direction": "LONG",
                    "entry_price": 1.33,
                    "exit_price": 1.3305,
                    "gross_pnl": 1.0,
                    "layer_depth": 0,
                    "stack_depth": 1,
                },
            })
            aw.insert_single(conn, item2)
            conn.commit()
            cur.execute(
                "SELECT rolled FROM scalp_history WHERE gross_pnl = 1.0 AND received_at > "
                "'2026-09-24T12:00:30+00' ORDER BY id DESC LIMIT 1"
            )
            if cur.fetchone()[0] is not None:
                raise AssertionError("missing rolled key should be NULL")
        conn.rollback()
    finally:
        conn.close()
    return 'scalp payload "rolled":true stored; missing key -> NULL'


def check_et3():
    if not URL:
        raise AssertionError("VERIFY_DATABASE_URL not set")
    import s4_scalps

    conn = psycopg2.connect(URL)
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            seed_full_fixture(cur)
        conn.commit()
        _, _, start_ms, end_ms = _day_bounds_ms(FTMO_D)
        with conn.cursor() as cur:
            cur.execute(s4_scalps.OUT_BY_SQL, (start_ms, end_ms))
            fill_rows = cur.fetchall()
            cur.execute(s4_scalps.EJECT_SQL, (start_ms, end_ms))
            eject_tickets = {row[0] for row in cur.fetchall() if row[0] is not None}
        counts = fd.s4_counts(fill_rows, eject_tickets, FTMO_D)
        n = counts.get((FIXTURE_INSTANCE, FTMO_D))
        if n != 4:
            raise AssertionError(f"expected s4 count 4, got {n!r} (tickets={eject_tickets})")
    finally:
        conn.close()
    return "s4 count GBPUSD_OPTB on D excludes roll and eject (4 scalps)"


def check_et4():
    start, end, _, _ = _day_bounds_ms(FTMO_D)
    events = [
        ("ROLL_ACCEPTED", "INFO", {"source": "live"}),
        ("ROLL_REFUSED", "INFO", {}),
        ("ROLL_FILLED", "INFO", {}),
        ("ROLL_STRANDED", "WARN", {}),
    ]
    close = datetime(2026, 9, 24, 10, 20, tzinfo=timezone.utc)
    scalps = [
        (close, 0, FIXTURE_ACCOUNT, -3.50, False, True),
    ]
    counts = fd.derive_counts(events, scalps, start, end, FIXTURE_ACCOUNT)
    expected = {
        "rolls_accepted": 1,
        "rolls_refused": 1,
        "roll_filled_events": 1,
        "rolled_fills": 1,
        "rolled_realised": -3.50,
        "roll_mismatch": 0,
        "roll_stranded_warns": 1,
        "roll_stuck_warns": 0,
    }
    for key, val in expected.items():
        if counts.get(key) != val:
            raise AssertionError(f"{key} expected {val}, got {counts.get(key)!r}")
    return "derive_counts roll figures"


def check_et5():
    start, end, _, _ = _day_bounds_ms(FTMO_D)
    events = [
        ("EJECT_ACCEPTED", "INFO", {"source": "auto"}),
        ("EJECT_FILLED", "INFO", {}),
    ]
    close = datetime(2026, 9, 24, 11, 10, tzinfo=timezone.utc)
    scalps = [(close, 0, FIXTURE_ACCOUNT, -1.00, True, False)]
    counts = fd.derive_counts(events, scalps, start, end, FIXTURE_ACCOUNT)
    if counts.get("ejections_auto") != 1:
        raise AssertionError("ejections_auto")
    if counts.get("ejected_fills") != 1:
        raise AssertionError("ejected_fills")
    if counts.get("ejected_realised") != -1.00:
        raise AssertionError("ejected_realised")
    return "eject figures unchanged (guard)"


def check_et6():
    if "ROLL_STRANDED" not in fd.WARN_CRITICAL_ALLOW:
        raise AssertionError("ROLL_STRANDED not in allow list")
    if "ROLL_CLOSING_STUCK" not in fd.WARN_CRITICAL_ALLOW:
        raise AssertionError("ROLL_CLOSING_STUCK not in allow list")
    return "WARN allow-list contains ROLL_* codes"


def _reload_app_fleet_b():
    os.environ["GRIND_FLEET"] = "B"
    import importlib
    import app as pipshed

    importlib.reload(pipshed)
    return pipshed


def check_et7():
    pipshed = _reload_app_fleet_b()
    client = pipshed.app.test_client()
    bad = client.get("/api/g/wrong-token/ejection")
    if bad.status_code != 404:
        raise AssertionError("bad token should 404")
    good = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/ejection")
    if good.status_code != 200:
        raise AssertionError(f"good token expected 200, got {good.status_code}")
    body = good.get_json()
    for key in EJECTION_TOP_KEYS:
        if key not in body:
            raise AssertionError(f"missing key {key}")
    return "endpoint token 404/200 and top-level keys"


def check_et8():
    import ejection_view as ev

    view = ev.build_ejection_view(**_fixture_view_kwargs())
    rolls = {r["ticket"]: r for r in view.get("rolls", [])}
    row = rolls.get(9001)
    if not row:
        raise AssertionError("roll 9001 missing")
    if row.get("status") != "filled":
        raise AssertionError("status")
    if row.get("minutes_to_fill") != 17:
        raise AssertionError("minutes_to_fill")
    realised = row.get("realised") or {}
    if realised.get("gross") != -3.50:
        raise AssertionError("gross")
    if realised.get("commission") != -0.14:
        raise AssertionError("commission")
    if realised.get("swap") != -0.20:
        raise AssertionError("swap")
    if realised.get("net") != -3.84:
        raise AssertionError("net")
    return "rolls row 9001 filled with Q1 realised"


def check_et9():
    import ejection_view as ev

    view = ev.build_ejection_view(**_fixture_view_kwargs())
    days = view.get("days") or []
    side_l = None
    side_s = None
    for block in days:
        if block.get("ftmo_day") != FTMO_D.isoformat():
            continue
        for inst in block.get("instances") or []:
            if inst.get("instance_id") != FIXTURE_INSTANCE:
                continue
            for side in inst.get("sides") or []:
                if side.get("side") == "L":
                    side_l = side
                if side.get("side") == "S":
                    side_s = side
    if side_l is None:
        raise AssertionError("side L block missing")
    scalps = side_l.get("scalps") or {}
    if scalps.get("count") != 3:
        raise AssertionError(f"L scalps count {scalps.get('count')}")
    if abs(float(scalps.get("gross", 0)) - 1.50) > 0.001:
        raise AssertionError("L scalps gross")
    if abs(float(scalps.get("net", 0)) - 1.08) > 0.001:
        raise AssertionError("L scalps net")
    rolls = side_l.get("rolls") or {}
    if rolls.get("filled") != 1:
        raise AssertionError("rolls filled")
    if abs(float(rolls.get("net", 0)) - (-3.84)) > 0.001:
        raise AssertionError("rolls net")
    eject = side_l.get("ejections") or {}
    if eject.get("filled") != 1:
        raise AssertionError("ejections filled")
    if abs(float(eject.get("net", 0)) - (-1.14)) > 0.001:
        raise AssertionError("ejections net")
    if abs(float(side_l.get("closed_net", 0)) - (-3.90)) > 0.001:
        raise AssertionError("closed_net")
    if side_s is None:
        raise AssertionError("side S missing")
    ss = side_s.get("scalps") or {}
    if ss.get("count") != 1:
        raise AssertionError("S scalps count")
    if abs(float(ss.get("net", 0)) - 0.36) > 0.001:
        raise AssertionError("S scalps net")
    return "days side L and S totals"


def check_et10():
    pipshed = _reload_app_fleet_b()
    client = pipshed.app.test_client()
    tok = pipshed.PUBLIC_GRIND_STATUS_TOKEN
    a = client.get(f"/api/g/{tok}/ejection").get_json()
    b = client.get(f"/api/g/{tok}/ejection/abc123").get_json()
    a.pop("generated_at", None)
    b.pop("generated_at", None)
    if a != b:
        raise AssertionError("cache-buster path differs from base")
    return "cache-buster path equals base (except generated_at)"


def check_et11():
    import ejection_view as ev

    assert ev.clamp_hours(0) == 1
    assert ev.clamp_hours(999) == 168
    assert ev.clamp_hours(48) == 48
    pipshed = _reload_app_fleet_b()
    client = pipshed.app.test_client()
    tok = pipshed.PUBLIC_GRIND_STATUS_TOKEN
    r0 = client.get(f"/api/g/{tok}/ejection?hours=0").get_json()
    r9 = client.get(f"/api/g/{tok}/ejection?hours=999").get_json()
    if r0.get("hours") != 1:
        raise AssertionError("hours=0 not clamped to 1")
    if r9.get("hours") != 168:
        raise AssertionError("hours=999 not clamped to 168")
    return "hours query clamped 1..168"


def check_et12():
    view = __import__("ejection_view").build_ejection_view(**_fixture_view_kwargs())
    if not view.get("fleet"):
        raise AssertionError("stub empty payload")
    for section in ("rolls", "ejections", "warnings"):
        for row in view.get(section) or []:
            if row.get("instance_id") == OUTSIDER_INSTANCE:
                raise AssertionError(f"{section} contains outsider instance")
    for block in view.get("reconciliation") or []:
        if block.get("instance_id") == OUTSIDER_INSTANCE:
            raise AssertionError("reconciliation contains outsider")
    return "outsider instance absent from view"


def check_et13():
    view = __import__("ejection_view").build_ejection_view(**_fixture_view_kwargs())
    recon = None
    for block in view.get("reconciliation") or []:
        if block.get("instance_id") == FIXTURE_INSTANCE:
            recon = block
    if recon is None:
        raise AssertionError("reconciliation block missing")
    refused = recon.get("refused") or {}
    if refused.get("MODIFY_FAILED") != 1:
        raise AssertionError("MODIFY_FAILED count")
    unfilled = recon.get("accepted_unfilled") or []
    if any(u.get("ticket") == 9002 for u in unfilled):
        raise AssertionError("9002 should not be accepted_unfilled")
    return "reconciliation ticket 9002 refused not unfilled"


def check_et14():
    import ejection_view as ev

    gross, commission, swap, net = ev.layer_realised_from_fills(
        {"gross_pnl": -3.50, "entry_deal_ticket": 7001, "exit_deal_ticket": 7002},
        _q1_fill_rows(),
    )
    if commission != -0.28:
        raise AssertionError(f"commission expected -0.28 got {commission}")
    if swap != -0.20:
        raise AssertionError(f"swap expected -0.20 got {swap}")
    if abs(net - (-3.98)) > 0.001:
        raise AssertionError(f"net expected -3.98 got {net}")
    return "Q1 commission position set (-0.28 comm, -0.20 swap)"


def check_et15():
    kwargs = _fixture_view_kwargs()
    kwargs["state_by_instance"] = {
        FIXTURE_INSTANCE: {
            "age_s": 5,
            "layers": [{
                "layer_index": 0,
                "ticket": 1,
                "entry": 1.33,
                "virtual_level": 1.326,
                "exit_target": 1.3265,
                "side": "L",
            }],
        }
    }
    kwargs["events"] = [e for e in kwargs["events"] if e.get("code") != "ROLL_ACCEPTED"]
    view = __import__("ejection_view").build_ejection_view(**kwargs)
    now_l = view.get("now", {}).get(FIXTURE_INSTANCE, {}).get("L", {})
    if now_l.get("disagree") is not True:
        raise AssertionError("disagree should be true when state rolled and events none")
    return "Q4 disagree when state rolled and events empty"


def _q1_fill_rows():
    rows = []
    for deal_ticket, order_ticket, position_id, comm, swap in (
        (7001, 9001, 7001, -0.07, 0),
        (7002, 9001, 7001, -0.07, -0.20),
        (7003, 9001, 7002, -0.07, 0),
        (7004, 9001, 7002, -0.07, 0),
    ):
        rows.append({
            "deal_ticket": deal_ticket,
            "order_ticket": order_ticket,
            "position_id": position_id,
            "commission": comm,
            "swap": swap,
            "instance_id": FIXTURE_INSTANCE,
        })
    return rows


def _fixture_view_kwargs():
    start, end, start_ms, end_ms = _day_bounds_ms(FTMO_D)
    events = [
        {
            "instance_id": FIXTURE_INSTANCE,
            "code": "ROLL_ACCEPTED",
            "level": "INFO",
            "ea_time_ms": _ms("2026-09-24T10:00:00Z"),
            "ticket": 9001,
            "detail": {
                "side": "L",
                "layer_index": 0,
                "entry": 1.33,
                "level": 1.326,
                "target": 1.3265,
                "cost_pips": 35.0,
                "clamped": False,
                "source": "live",
            },
        },
        {
            "instance_id": FIXTURE_INSTANCE,
            "code": "ROLL_FILLED",
            "level": "INFO",
            "ea_time_ms": _ms("2026-09-24T10:17:00Z"),
            "ticket": 9001,
            "detail": {"level": 1.326},
        },
        {
            "instance_id": FIXTURE_INSTANCE,
            "code": "ROLL_REFUSED",
            "level": "INFO",
            "ea_time_ms": _ms("2026-09-24T10:00:01Z"),
            "ticket": 9002,
            "detail": {"reason": "MODIFY_FAILED", "source": "live"},
        },
        {
            "instance_id": FIXTURE_INSTANCE,
            "code": "ROLL_STRANDED",
            "level": "WARN",
            "ea_time_ms": _ms("2026-09-24T10:00:02Z"),
            "ticket": 0,
            "detail": {"side": "L"},
        },
        {
            "instance_id": FIXTURE_INSTANCE,
            "code": "EJECT_ACCEPTED",
            "level": "INFO",
            "ea_time_ms": _ms("2026-09-24T11:00:00Z"),
            "ticket": 9003,
            "detail": {"source": "auto"},
        },
        {
            "instance_id": FIXTURE_INSTANCE,
            "code": "EJECT_FILLED",
            "level": "INFO",
            "ea_time_ms": _ms("2026-09-24T11:05:00Z"),
            "ticket": 9003,
            "detail": {"offset": 0},
        },
        {
            "instance_id": OUTSIDER_INSTANCE,
            "code": "EJECT_ACCEPTED",
            "level": "INFO",
            "ea_time_ms": _ms("2026-09-24T11:00:00Z"),
            "ticket": 9999,
            "detail": {"source": "auto"},
        },
    ]
    scalps = []
    deal_pairs = [(6101, 6102), (6103, 6104), (6105, 6106), (6107, 6108)]
    for direction, gross, hour, (entry_d, exit_d) in zip(
        ["LONG", "LONG", "LONG", "SHORT"],
        [0.50, 0.50, 0.50, 0.50],
        [9, 9, 9, 9],
        deal_pairs,
    ):
        scalps.append({
            "instance_id": FIXTURE_INSTANCE,
            "direction": direction,
            "gross_pnl": gross,
            "ejected": False,
            "rolled": False,
            "broker_utc_offset_s": 0,
            "account_login": FIXTURE_ACCOUNT,
            "close_time_broker": datetime(2026, 9, 24, hour, 0, tzinfo=timezone.utc),
            "entry_deal_ticket": entry_d,
            "exit_deal_ticket": exit_d,
            "layer_depth": 0,
        })
    scalps.append({
        "instance_id": FIXTURE_INSTANCE,
        "direction": "LONG",
        "gross_pnl": -3.50,
        "ejected": False,
        "rolled": True,
        "broker_utc_offset_s": 0,
        "account_login": FIXTURE_ACCOUNT,
        "close_time_broker": datetime(2026, 9, 24, 10, 20, tzinfo=timezone.utc),
        "entry_deal_ticket": 7001,
        "exit_deal_ticket": 7002,
        "layer_depth": 0,
    })
    scalps.append({
        "instance_id": FIXTURE_INSTANCE,
        "direction": "LONG",
        "gross_pnl": -1.00,
        "ejected": True,
        "rolled": False,
        "broker_utc_offset_s": 0,
        "account_login": FIXTURE_ACCOUNT,
        "close_time_broker": datetime(2026, 9, 24, 11, 10, tzinfo=timezone.utc),
        "entry_deal_ticket": 8101,
        "exit_deal_ticket": 8102,
        "layer_depth": 0,
    })
    fill_logs = [
        {
            "deal_ticket": 7001,
            "order_ticket": 9001,
            "position_id": 7001,
            "commission": -0.07,
            "swap": 0,
            "instance_id": FIXTURE_INSTANCE,
        },
        {
            "deal_ticket": 7002,
            "order_ticket": 9001,
            "position_id": 7001,
            "commission": -0.07,
            "swap": -0.20,
            "instance_id": FIXTURE_INSTANCE,
        },
        {
            "deal_ticket": 8101,
            "order_ticket": 9003,
            "position_id": 8101,
            "commission": -0.07,
            "swap": 0,
            "instance_id": FIXTURE_INSTANCE,
        },
        {
            "deal_ticket": 8102,
            "order_ticket": 9003,
            "position_id": 8101,
            "commission": -0.07,
            "swap": 0,
            "instance_id": FIXTURE_INSTANCE,
        },
    ]
    for entry_d, exit_d in deal_pairs:
        fill_logs.append({
            "deal_ticket": entry_d,
            "order_ticket": entry_d,
            "position_id": entry_d,
            "commission": -0.07,
            "swap": 0,
            "instance_id": FIXTURE_INSTANCE,
        })
        fill_logs.append({
            "deal_ticket": exit_d,
            "order_ticket": exit_d,
            "position_id": entry_d,
            "commission": -0.07,
            "swap": 0,
            "instance_id": FIXTURE_INSTANCE,
        })
    return {
        "generated_at": "2026-09-24T12:00:00Z",
        "fleet": "B",
        "fleet_label": "Fleet B",
        "hours": 48,
        "grind_instances": [FIXTURE_INSTANCE],
        "events": events,
        "scalps": scalps,
        "fill_logs": fill_logs,
        "state_by_instance": {},
        "now_dt": datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc),
        "window_start_ms": start_ms,
        "window_end_ms": end_ms,
    }


CHECKS = [
    ("ET1", check_et1),
    ("ET2", check_et2),
    ("ET3", check_et3),
    ("ET4", check_et4),
    ("ET5", check_et5),
    ("ET6", check_et6),
    ("ET7", check_et7),
    ("ET8", check_et8),
    ("ET9", check_et9),
    ("ET10", check_et10),
    ("ET11", check_et11),
    ("ET12", check_et12),
    ("ET13", check_et13),
    ("ET14", check_et14),
    ("ET15", check_et15),
]


def main():
    passed = 0
    failed = 0
    for name, fn in CHECKS:
        try:
            msg = fn()
            print(f"{name} OK: {msg}")
            passed += 1
        except Exception as exc:
            print(f"{name} FAIL: {exc}")
            failed += 1
    print(f"SUMMARY passed={passed} failed={failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
