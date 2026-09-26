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
    "view_built_at",
    "view_age_s",
    "now",
    "rolls",
    "ejections",
    "days",
    "warnings",
    "reconciliation",
)

ARCHIVE_EJECTION_KEY = "fxmatrix:ejection:view"
EJECTION_VIEW_MAX_AGE_S = 300


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
    for i, (direction, gross, entry_d, exit_d) in enumerate(scalp_specs):
        order_t = 5001 + i
        seq += 1
        _insert_out_by(cur, seq, order_t, entry_d, t_scalp + seq)
        seq += 1
        _insert_out_by(cur, seq, order_t, exit_d, t_scalp + seq + 1)
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
        7001,
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
    _insert_ea(cur, seq, "ROLL_FILLED", "INFO", roll_fill_ms, 7001, {"level": 1.326})
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
    _insert_ea(cur, seq, "EJECT_ACCEPTED", "INFO", eject_accept_ms, 8001, {"source": "auto"})
    seq += 1
    _insert_ea(cur, seq, "EJECT_FILLED", "INFO", eject_fill_ms, 8001, {"offset": 0})
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


class FakeRedis:
    def __init__(self):
        self._kv = {}
        self._lists = {}

    def get(self, key):
        return self._kv.get(key)

    def set(self, key, value, ex=None):
        self._kv[key] = value

    def lrange(self, key, start, end):
        items = self._lists.get(key, [])
        if end == -1:
            end = len(items) - 1
        if not items or start > end:
            return []
        return items[start : end + 1]


class BrokenRedis:
    def get(self, *args, **kwargs):
        import redis

        raise redis.exceptions.ConnectionError("redis unavailable")

    def lrange(self, *args, **kwargs):
        import redis

        raise redis.exceptions.ConnectionError("redis unavailable")

    def set(self, *args, **kwargs):
        import redis

        raise redis.exceptions.ConnectionError("redis unavailable")


def _publish_ejection_snapshot(redis_client, snapshot):
    import archive_worker as aw

    aw.publish_ejection_view(redis_client, snapshot)


def _worker_snapshot_from_fixture_kwargs(now=None):
    """Same payload shape the archive worker publishes (168 h window)."""
    import ejection_view as ev

    now = now or datetime.now(timezone.utc)
    end_ms = int(now.timestamp() * 1000)
    start_ms = end_ms - 168 * 3600 * 1000
    kwargs = _fixture_view_kwargs()
    kwargs["window_end_ms"] = end_ms
    kwargs["window_start_ms"] = start_ms
    kwargs["now_dt"] = now
    kwargs["grind_instances"] = sorted(
        {row.get("instance_id") for row in kwargs["events"] if row.get("instance_id")}
        | {row.get("instance_id") for row in kwargs["scalps"] if row.get("instance_id")}
        | {OUTSIDER_INSTANCE}
    )
    return ev.build_worker_ejection_snapshot(
        built_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        window_start_ms=start_ms,
        window_end_ms=end_ms,
        events=kwargs["events"],
        scalps=kwargs["scalps"],
        fill_logs=kwargs["fill_logs"],
    )


def _seed_fresh_ejection_view(redis_client, snapshot=None):
    snap = snapshot or _worker_snapshot_from_fixture_kwargs()
    _publish_ejection_snapshot(redis_client, snap)
    return snap


def _reload_app_fleet_b(redis_client=None):
    os.environ["GRIND_FLEET"] = "B"
    import importlib
    import app as pipshed

    importlib.reload(pipshed)
    pipshed.r = redis_client if redis_client is not None else FakeRedis()
    return pipshed


def check_et7():
    redis = FakeRedis()
    _seed_fresh_ejection_view(redis)
    pipshed = _reload_app_fleet_b(redis)
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
    row = rolls.get(7001)
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
    redis = FakeRedis()
    _seed_fresh_ejection_view(redis)
    pipshed = _reload_app_fleet_b(redis)
    client = pipshed.app.test_client()
    tok = pipshed.PUBLIC_GRIND_STATUS_TOKEN
    resp_a = client.get(f"/api/g/{tok}/ejection")
    resp_b = client.get(f"/api/g/{tok}/ejection/abc123")
    if resp_a.status_code != 200 or resp_b.status_code != 200:
        raise AssertionError("cache-buster routes must return 200")
    a = resp_a.get_json()
    b = resp_b.get_json()
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
    redis = FakeRedis()
    _seed_fresh_ejection_view(redis)
    pipshed = _reload_app_fleet_b(redis)
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


def _two_roll_view_kwargs():
    kwargs = _fixture_view_kwargs()
    base_ms = _ms("2026-09-24T10:00:00Z")
    events = [e for e in kwargs["events"] if e.get("code") not in ("ROLL_ACCEPTED", "ROLL_FILLED")]
    events.extend([
        {
            "instance_id": FIXTURE_INSTANCE,
            "code": "ROLL_ACCEPTED",
            "level": "INFO",
            "ea_time_ms": base_ms,
            "ticket": 7101,
            "detail": {"side": "L", "layer_index": 0, "source": "live"},
        },
        {
            "instance_id": FIXTURE_INSTANCE,
            "code": "ROLL_FILLED",
            "level": "INFO",
            "ea_time_ms": base_ms + 17 * 60 * 1000,
            "ticket": 7101,
            "detail": {},
        },
        {
            "instance_id": FIXTURE_INSTANCE,
            "code": "ROLL_ACCEPTED",
            "level": "INFO",
            "ea_time_ms": base_ms + 1000,
            "ticket": 7201,
            "detail": {"side": "L", "layer_index": 1, "source": "live"},
        },
        {
            "instance_id": FIXTURE_INSTANCE,
            "code": "ROLL_FILLED",
            "level": "INFO",
            "ea_time_ms": base_ms + 18 * 60 * 1000,
            "ticket": 7201,
            "detail": {},
        },
    ])
    scalps = [s for s in kwargs["scalps"] if not s.get("rolled")]
    scalps.extend([
        {
            "instance_id": FIXTURE_INSTANCE,
            "direction": "LONG",
            "gross_pnl": -3.50,
            "rolled": True,
            "ejected": False,
            "broker_utc_offset_s": 0,
            "account_login": FIXTURE_ACCOUNT,
            "close_time_broker": datetime(2026, 9, 24, 10, 20, tzinfo=timezone.utc),
            "entry_deal_ticket": 7101,
            "exit_deal_ticket": 7102,
            "layer_depth": 0,
        },
        {
            "instance_id": FIXTURE_INSTANCE,
            "direction": "LONG",
            "gross_pnl": -2.00,
            "rolled": True,
            "ejected": False,
            "broker_utc_offset_s": 0,
            "account_login": FIXTURE_ACCOUNT,
            "close_time_broker": datetime(2026, 9, 24, 10, 21, tzinfo=timezone.utc),
            "entry_deal_ticket": 7201,
            "exit_deal_ticket": 7202,
            "layer_depth": 1,
        },
    ])
    fill_logs = list(kwargs["fill_logs"])
    for pos, entry_d, exit_d in ((7101, 7101, 7102), (7201, 7201, 7202)):
        fill_logs.extend([
            {
                "deal_ticket": entry_d,
                "order_ticket": 9100 + pos,
                "position_id": pos,
                "commission": -0.07,
                "swap": 0,
                "instance_id": FIXTURE_INSTANCE,
            },
            {
                "deal_ticket": exit_d,
                "order_ticket": 9100 + pos,
                "position_id": pos,
                "commission": -0.07,
                "swap": 0,
                "instance_id": FIXTURE_INSTANCE,
            },
        ])
    kwargs["events"] = events
    kwargs["scalps"] = scalps
    kwargs["fill_logs"] = fill_logs
    return kwargs


def check_et16():
    import ejection_view as ev

    view = ev.build_ejection_view(**_two_roll_view_kwargs())
    rolls = {r["ticket"]: r for r in view.get("rolls", [])}
    r7101 = rolls.get(7101)
    r7201 = rolls.get(7201)
    if not r7101 or r7101.get("realised", {}).get("net") != -3.64:
        raise AssertionError(f"7101 net expected -3.64 got {r7101}")
    if not r7201 or r7201.get("realised", {}).get("net") != -2.14:
        raise AssertionError(f"7201 net expected -2.14 got {r7201}")
    return "two rolls same day distinct P&L by position ticket"


def check_et17():
    import ejection_view as ev

    kwargs = _fixture_view_kwargs()
    kwargs["events"].append({
        "instance_id": FIXTURE_INSTANCE,
        "code": "ROLL_FILLED",
        "level": "INFO",
        "ea_time_ms": _ms("2026-09-24T12:00:00Z"),
        "ticket": 7301,
        "detail": {},
    })
    view = ev.build_ejection_view(**kwargs)
    recon = next(
        (b for b in view.get("reconciliation") or [] if b.get("instance_id") == FIXTURE_INSTANCE),
        None,
    )
    if recon is None:
        raise AssertionError("reconciliation missing")
    unmatched = recon.get("filled_unmatched") or []
    tickets = {u.get("ticket") for u in unmatched}
    if 7301 not in tickets:
        raise AssertionError("7301 not in filled_unmatched")
    roll7301 = next((r for r in view.get("rolls") or [] if r.get("ticket") == 7301), None)
    if roll7301 and roll7301.get("realised") is not None:
        raise AssertionError("7301 realised should be null")
    return "ROLL_FILLED without scalp -> filled_unmatched"


def check_et18():
    import ejection_view as ev

    result = ev.layer_realised_from_fills(
        {
            "gross_pnl": -1.0,
            "entry_deal_ticket": 99991,
            "exit_deal_ticket": 99992,
            "instance_id": FIXTURE_INSTANCE,
        },
        [],
    )
    if result is not None:
        raise AssertionError("empty position set must return None")
    return "layer_realised_from_fills fail-closed on missing fills"


def check_et19():
    pipshed = _reload_app_fleet_b(BrokenRedis())
    client = pipshed.app.test_client()
    tok = pipshed.PUBLIC_GRIND_STATUS_TOKEN
    resp = client.get(f"/api/g/{tok}/ejection")
    if resp.status_code != 503:
        raise AssertionError(f"expected 503 with redis down, got {resp.status_code}")
    body = resp.get_json()
    if body.get("error") != "ejection view unavailable":
        raise AssertionError("expected ejection view unavailable error")
    if "days" in body:
        raise AssertionError("503 must not include days")
    return "redis down returns 503 without fabricated view"


def check_et21():
    app_path = os.path.join(ROOT, "app.py")
    ev_path = os.path.join(ROOT, "ejection_view.py")
    with open(app_path, encoding="utf-8") as f:
        app_src = f.read()
    with open(ev_path, encoding="utf-8") as f:
        ev_src = f.read()
    start = app_src.index("def public_ejection_telemetry")
    end = app_src.index("\ndef ", start + 1)
    route_block = app_src[start:end]
    forbidden = ("psycopg2", "DATABASE_URL")
    for token in forbidden:
        if token in route_block:
            raise AssertionError(f"public_ejection_telemetry must not reference {token}")
    if "psycopg2" in ev_src:
        raise AssertionError("ejection_view.py must not import or use psycopg2")
    if "DATABASE_URL" in ev_src:
        raise AssertionError("ejection_view.py must not reference DATABASE_URL")
    if "fetch_ejection_view" in ev_src:
        raise AssertionError("fetch_ejection_view must not remain on the web path")
    return "route and ejection_view web path have no postgres"


def check_et22():
    if os.environ.get("DATABASE_URL"):
        raise AssertionError("DATABASE_URL must not be set for this check")
    redis = FakeRedis()
    pipshed = _reload_app_fleet_b(redis)
    client = pipshed.app.test_client()
    tok = pipshed.PUBLIC_GRIND_STATUS_TOKEN
    resp = client.get(f"/api/g/{tok}/ejection")
    if resp.status_code != 503:
        raise AssertionError(f"expected 503 without view key, got {resp.status_code}")
    body = resp.get_json()
    if body.get("error") != "ejection view unavailable":
        raise AssertionError("missing error key")
    if "days" in body:
        raise AssertionError("503 body must not expose days")
    return "missing view key returns 503"


def check_et23():
    redis = FakeRedis()
    now = datetime.now(timezone.utc)
    stale_at = now - timedelta(seconds=600)
    snap = _worker_snapshot_from_fixture_kwargs(now=stale_at)
    _publish_ejection_snapshot(redis, snap)
    pipshed = _reload_app_fleet_b(redis)
    client = pipshed.app.test_client()
    tok = pipshed.PUBLIC_GRIND_STATUS_TOKEN
    resp = client.get(f"/api/g/{tok}/ejection")
    if resp.status_code != 503:
        raise AssertionError(f"expected 503 for stale view, got {resp.status_code}")
    body = resp.get_json()
    age = body.get("view_age_s")
    if age is None or abs(int(age) - 600) > 2:
        raise AssertionError(f"view_age_s expected ~600, got {age}")
    return "stale built_at returns 503 with view_age_s"


def check_et24():
    if not URL:
        raise AssertionError("VERIFY_DATABASE_URL not set")
    import archive_worker as aw

    redis = FakeRedis()
    conn = psycopg2.connect(URL)
    try:
        cur = conn.cursor()
        seed_full_fixture(cur)
        conn.commit()
        # The worker builds 168 h back from NOW and the web trims to 48 h, so a
        # fixed-date fixture expires. Shift it forward by WHOLE days (keeps each
        # row's time of day, hence its FTMO day relative to the 22:00Z boundary)
        # so the roll (D 10:17Z) lands within the last 24 h.
        roll_filled = datetime(2026, 9, 24, 10, 17, tzinfo=timezone.utc)
        shift_days = (datetime.now(timezone.utc) - roll_filled).days
        if shift_days > 0:
            shift_ms = shift_days * 86400 * 1000
            cur.execute("UPDATE ea_events SET ea_time_ms = ea_time_ms + %s,"
                        " received_at = received_at + make_interval(days => %s)",
                        (shift_ms, shift_days))
            cur.execute("UPDATE fill_logs SET ea_time_ms = ea_time_ms + %s,"
                        " received_at = received_at + make_interval(days => %s)",
                        (shift_ms, shift_days))
            cur.execute("UPDATE scalp_history SET"
                        " close_time_broker = close_time_broker + make_interval(days => %s),"
                        " received_at = received_at + make_interval(days => %s)",
                        (shift_days, shift_days))
            conn.commit()
        aw.try_ejection_build(conn, redis, force=True)
    finally:
        conn.close()
    shifted_day = FTMO_D + timedelta(days=max(shift_days, 0))
    raw = redis.get(ARCHIVE_EJECTION_KEY)
    if not raw:
        raise AssertionError("worker did not publish ejection view")
    snap = json.loads(raw)
    if not snap.get("built_at"):
        raise AssertionError("built_at missing")
    pipshed = _reload_app_fleet_b(redis)
    body = pipshed.app.test_client().get(
        f"/api/g/{pipshed.PUBLIC_GRIND_STATUS_TOKEN}/ejection"
    ).get_json()
    rolls = {r["ticket"]: r for r in body.get("rolls") or []}
    row = rolls.get(7001)
    # By hand for the DB fixture (seed_full_fixture), Q1 rule: the roll's
    # position set is {7001, 7002} via its exit order 9001, i.e. deals 5011,
    # 5012, 7001, 7002, 7003, 7004: commission 6 x -0.07 = -0.42, swap -0.20;
    # net = -3.50 - 0.42 - 0.20 = -4.12. (-3.84 belongs to the in-memory
    # fixture of ET8, which has two deals.)
    if not row or (row.get("realised") or {}).get("net") != -4.12:
        raise AssertionError(f"roll 7001 net expected -4.12 got {row}")
    days = body.get("days") or []
    side_l = None
    for block in days:
        if block.get("ftmo_day") != shifted_day.isoformat():
            continue
        for inst in block.get("instances") or []:
            if inst.get("instance_id") != FIXTURE_INSTANCE:
                continue
            for side in inst.get("sides") or []:
                if side.get("side") == "L":
                    side_l = side
    scalps = (side_l or {}).get("scalps") or {}
    if scalps.get("count") != 3:
        raise AssertionError(f"L scalps count expected 3 got {scalps.get('count')}")
    return "worker builder publishes fixture roll and day scalps"


def check_et25():
    now = datetime.now(timezone.utc)
    end_ms = int(now.timestamp() * 1000)
    start_ms = end_ms - 168 * 3600 * 1000
    roll_ms = end_ms - 60 * 3600 * 1000
    kwargs = _fixture_view_kwargs()
    kwargs["events"] = [
        e
        for e in kwargs["events"]
        if e.get("code") not in ("ROLL_ACCEPTED", "ROLL_FILLED")
    ]
    kwargs["events"].extend([
        {
            "instance_id": FIXTURE_INSTANCE,
            "code": "ROLL_ACCEPTED",
            "level": "INFO",
            "ea_time_ms": roll_ms - 60000,
            "ticket": 7501,
            "detail": {"side": "L", "layer_index": 0},
        },
        {
            "instance_id": FIXTURE_INSTANCE,
            "code": "ROLL_FILLED",
            "level": "INFO",
            "ea_time_ms": roll_ms,
            "ticket": 7501,
            "detail": {},
        },
        {
            "instance_id": OUTSIDER_INSTANCE,
            "code": "ROLL_ACCEPTED",
            "level": "INFO",
            "ea_time_ms": roll_ms,
            "ticket": 7601,
            "detail": {"side": "L"},
        },
    ])
    snap = __import__("ejection_view").build_worker_ejection_snapshot(
        built_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        window_start_ms=start_ms,
        window_end_ms=end_ms,
        events=kwargs["events"],
        scalps=kwargs["scalps"],
        fill_logs=kwargs["fill_logs"],
    )
    redis = FakeRedis()
    _publish_ejection_snapshot(redis, snap)
    pipshed = _reload_app_fleet_b(redis)
    client = pipshed.app.test_client()
    tok = pipshed.PUBLIC_GRIND_STATUS_TOKEN
    body48 = client.get(f"/api/g/{tok}/ejection?hours=48").get_json()
    tickets48 = {r.get("ticket") for r in body48.get("rolls") or []}
    if 7501 in tickets48:
        raise AssertionError("60h-old roll must be absent at hours=48")
    body72 = client.get(f"/api/g/{tok}/ejection?hours=72").get_json()
    tickets72 = {r.get("ticket") for r in body72.get("rolls") or []}
    if 7501 not in tickets72:
        raise AssertionError("60h-old roll must appear at hours=72")
    outsider = {r.get("instance_id") for r in body72.get("rolls") or []}
    if OUTSIDER_INSTANCE in outsider:
        raise AssertionError("outsider instance must be filtered on web")
    return "hours trim and fleet instance filter on web"


def check_et26():
    import ejection_view as ev

    redis = FakeRedis()
    _seed_fresh_ejection_view(redis)
    ea_state = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "layers": [
            {
                "layer_index": 0,
                "side": "L",
                "entry_price": 1.33000,
                "exit_target": 1.33050,
            },
            {
                "layer_index": 1,
                "side": "L",
                "entry_price": 1.32500,
                "exit_target": 1.32550,
                "virtual_level": 1.32100,
            },
            {
                "layer_index": 0,
                "side": "S",
                "entry_price": 1.34000,
                "exit_target": 1.33950,
            },
        ],
    }
    redis.set(f"fxmatrix:state:{FIXTURE_INSTANCE}", json.dumps(ea_state))
    pipshed = _reload_app_fleet_b(redis)
    body = pipshed.app.test_client().get(
        f"/api/g/{pipshed.PUBLIC_GRIND_STATUS_TOKEN}/ejection"
    ).get_json()
    now_l = body.get("now", {}).get(FIXTURE_INSTANCE, {}).get("L", {})
    now_s = body.get("now", {}).get(FIXTURE_INSTANCE, {}).get("S", {})
    if now_l.get("depth") != 2:
        raise AssertionError(f"L depth expected 2 got {now_l.get('depth')}")
    if now_l.get("rolled_by_state") != 1:
        raise AssertionError("L rolled_by_state expected 1")
    entries = [layer.get("entry") for layer in now_l.get("layers") or []]
    if entries != [1.33, 1.325]:
        raise AssertionError(f"L entries expected [1.33, 1.325] got {entries}")
    if now_l.get("lowest_effective") != 1.321:
        raise AssertionError("L lowest_effective")
    if now_s.get("depth") != 1:
        raise AssertionError("S depth")
    if now_s.get("rolled_by_state") != 0:
        raise AssertionError("S rolled_by_state")
    if now_s.get("lowest_effective") != 1.34:
        raise AssertionError("S lowest_effective")
    for side_block in (now_l, now_s):
        for layer in side_block.get("layers") or []:
            if layer.get("ticket") is not None:
                raise AssertionError("EA heartbeat has no position ticket on layers")
    return "now block uses EA-shaped heartbeat layers"


def _summary_base_records():
    records = []
    for gross in (0.50, 0.50, 0.50, 0.50):
        records.append({
            "instrument": "GBPUSD",
            "entry_price": 1.33,
            "exit_price": 1.3305,
            "gross_pnl": gross,
            "rolled": False,
            "ejected": False,
            "close_time": "2026-09-24 10:00:00",
        })
    records.append({
        "instrument": "GBPUSD",
        "entry_price": 1.33,
        "exit_price": 1.3265,
        "gross_pnl": -3.50,
        "rolled": True,
        "ejected": False,
        "close_time": "2026-09-24 10:20:00",
    })
    records.append({
        "instrument": "GBPUSD",
        "entry_price": 1.33,
        "exit_price": 1.329,
        "gross_pnl": -1.00,
        "rolled": False,
        "ejected": True,
        "close_time": "2026-09-24 11:10:00",
    })
    return records


def check_et20():
    pipshed = _reload_app_fleet_b(FakeRedis())

    records = _summary_base_records()
    original_collect = pipshed._collect_today_scalp_records
    original_between = pipshed._collect_scalp_records_between
    original_metrics = pipshed._read_global_account_metrics
    original_book = pipshed._collect_open_book_stats
    pipshed._collect_today_scalp_records = lambda selected_date=None: ("2026-09-24", records)
    pipshed._collect_scalp_records_between = lambda start, end: records
    pipshed._read_global_account_metrics = lambda: None
    pipshed._collect_open_book_stats = lambda: {
        "position_count": 0,
        "pair_count": 0,
        "deepest_stack": 0,
        "open_mtm": 0.0,
    }
    try:
        text = pipshed._build_daily_summary_text("2026-09-24")
    finally:
        pipshed._collect_today_scalp_records = original_collect
        pipshed._collect_scalp_records_between = original_between
        pipshed._read_global_account_metrics = original_metrics
        pipshed._collect_open_book_stats = original_book
    if "Scalps       4 closed" not in text:
        raise AssertionError("expected Scalps 4 closed")
    if "Rolls 1 -3.50 USD   Ejections 1 -1.00 USD" not in text:
        raise AssertionError("missing Rolls/Ejections line")
    if "-2.50 USD gross" not in text:
        raise AssertionError("expected gross -2.50")
    if "Commission -0.30 USD" not in text:
        raise AssertionError("expected commission -0.30")
    if "Net -2.80 USD" not in text:
        raise AssertionError("expected net -2.80")
    return "summary counts exclude roll/eject; money includes all"


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
            "ticket": 7001,
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
            "ticket": 7001,
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
            "ticket": 8001,
            "detail": {"source": "auto"},
        },
        {
            "instance_id": FIXTURE_INSTANCE,
            "code": "EJECT_FILLED",
            "level": "INFO",
            "ea_time_ms": _ms("2026-09-24T11:05:00Z"),
            "ticket": 8001,
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
        "entry_deal_ticket": 8001,
        "exit_deal_ticket": 8002,
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
            "deal_ticket": 8001,
            "order_ticket": 9003,
            "position_id": 8001,
            "commission": -0.07,
            "swap": 0,
            "instance_id": FIXTURE_INSTANCE,
        },
        {
            "deal_ticket": 8002,
            "order_ticket": 9003,
            "position_id": 8001,
            "commission": -0.07,
            "swap": 0,
            "instance_id": FIXTURE_INSTANCE,
        },
    ]
    for i, (entry_d, exit_d) in enumerate(deal_pairs):
        order_t = 5101 + i
        fill_logs.append({
            "deal_ticket": entry_d,
            "order_ticket": order_t,
            "position_id": entry_d,
            "commission": -0.07,
            "swap": 0,
            "instance_id": FIXTURE_INSTANCE,
        })
        fill_logs.append({
            "deal_ticket": exit_d,
            "order_ticket": order_t,
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
    ("ET16", check_et16),
    ("ET17", check_et17),
    ("ET18", check_et18),
    ("ET19", check_et19),
    ("ET20", check_et20),
    ("ET21", check_et21),
    ("ET22", check_et22),
    ("ET23", check_et23),
    ("ET24", check_et24),
    ("ET25", check_et25),
    ("ET26", check_et26),
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
