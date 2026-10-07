"""Verification: C137 part 2, one-minute state snapshots (fxmatrix backlog
C137 (2); operator 7 Oct ~20:15Z: "snap these pipshed metrics every so
often and save to a db so we could create intraday history of equity,
balance, scalps, rolls ... and the daily values of add/exit width, layers";
once a MINUTE).

Migration 005 adds `state_snapshots`. The archive worker (not the EAs'
push path) reads every `fxmatrix:state:*` heartbeat once a minute and
writes one row per instance whose heartbeat is at most 120 s old:
balance, equity, the EA's net MTM and the book's MTM per side (positions
whose GRIND comment names side L or S: GRIND|<slot>|<side>|L<nn>|ENT/EXT),
open layers per side, api_count, halted, quarantined, entry_stopped, cap
and width / add / exit per side (the v2.0 per-side keys when a number > 0,
else the base key, as C129), the heartbeat's layer-removal count (closes
since init, C136) and fills. `snapped_at` is the minute; a second write in
the same minute adds nothing (UNIQUE (instance_id, snapped_at)). Until the
operator runs the migration the write is skipped (logged), never an error.
Rows are kept (no retention, operator ~23:04Z). The float-entry gate state
is not in the heartbeat and is not stored (ADR-160's flag lives in the EA
only); the roll gate is in config_events (LATTICE_CONFIG).

`scripts/archive_counts.py --export-snapshots --from <ISO> --to <ISO>
[--instance ID] [--csv]` prints them (JSON lines with a _meta line, or CSV).

C122 (same patch, test only): verify_c110 SR3 dated its fixture by UTC
while the endpoint reads the broker date, so it failed 21:00-24:00Z.

Tests first. Predicted at the tests-only commit: SN1-SN6 FAIL; SN7 (the
C122 change) passes at any hour once its fixture is dated by broker time.

    python scripts/verify_c137_snapshots.py   (SN1, SN3, SN5 need VERIFY_DATABASE_URL)
"""
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
URL = os.environ.get("VERIFY_DATABASE_URL")
UTC = timezone.utc
NOW = datetime(2026, 10, 8, 12, 0, 37, tzinfo=UTC)
MINUTE = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)

COLUMNS = [
    "id", "snapped_at", "instance_id", "account_login", "heartbeat_at", "balance", "equity",
    "net_mtm", "mtm_long", "mtm_short", "layers_long", "layers_short", "api_count",
    "halted", "quarantined", "entry_stopped", "max_layers",
    "width_long", "width_short", "add_long", "add_short", "exit_long", "exit_short",
    "closes_since_init", "fills",
]


def hb(seconds_old, **over):
    payload = {
        "_received_at": (NOW - timedelta(seconds=seconds_old)).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00"),
        "instance_id": "GRIND_GBPUSD_OPTB", "account_login": 53066709,
        "account_balance": 10184.45, "account_equity": 9993.91, "net_mtm": -190.54,
        "open_layers_long": 4, "open_layers_short": 6, "api_count": 193,
        "halted": False, "quarantined": True, "entry_stopped": False, "max_layers": 8,
        "width_pips": 2.5, "add_pips": 9.0, "exit_pips": 10.0,
        "width_pips_long": 2.5, "width_pips_short": 0.0,
        "add_pips_long": 9.0, "add_pips_short": 8.0,
        "exit_pips_long": 10.0, "exit_pips_short": -1,
        "scalps": 87, "fills": 140,
        "book": {"positions": [
            {"comment": "GRIND|OPTB|L|L00|ENT", "profit": -3.25},
            {"comment": "GRIND|OPTB|L|L00|EXT", "profit": 1.10},
            {"comment": "GRIND|OPTB|S|L01|ENT", "profit": 2.00},
            {"comment": "manual close", "profit": -9.99},
            {"comment": "GRIND|OPTB|S|L02|ENT", "profit": "x"},
            {"profit": 5.0},
        ], "orders": []},
    }
    payload.update(over)
    return json.dumps(payload)


def check_sn1():
    if not URL:
        raise AssertionError("VERIFY_DATABASE_URL is not set (scratch database only)")
    path = os.path.join(ROOT, "migrations", "005_c137_state_snapshots.sql")
    if not os.path.exists(path):
        raise AssertionError("migrations/005_c137_state_snapshots.sql is missing")
    sql = open(path, encoding="ascii").read()
    import psycopg2
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS state_snapshots")
        cur.execute(sql)
        cur.execute("SELECT column_name FROM information_schema.columns"
                    " WHERE table_name = 'state_snapshots' ORDER BY ordinal_position")
        cols = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT indexdef FROM pg_indexes WHERE tablename = 'state_snapshots'")
        idx = " ".join(r[0] for r in cur.fetchall())
    conn.close()
    if cols != COLUMNS:
        raise AssertionError(f"columns: expected {COLUMNS}, got {cols}")
    if "(instance_id, snapped_at)" not in idx or "(snapped_at)" not in idx:
        raise AssertionError(f"indexes: UNIQUE (instance_id, snapped_at) and (snapped_at); got {idx}")
    return "005 creates state_snapshots (25 columns, unique per instance and minute, indexed by time)"


def check_sn2():
    import archive_worker as aw
    row = aw.snapshot_row_from_state("GRIND_GBPUSD_OPTB", hb(30), NOW)
    want = {
        "snapped_at": MINUTE, "instance_id": "GRIND_GBPUSD_OPTB", "account_login": 53066709,
        "heartbeat_at": NOW - timedelta(seconds=30),
        "balance": 10184.45, "equity": 9993.91, "net_mtm": -190.54,
        "mtm_long": -2.15, "mtm_short": 2.0,            # -3.25 + 1.10; 2.00 ("x" and no comment skipped)
        "layers_long": 4, "layers_short": 6, "api_count": 193,
        "halted": False, "quarantined": True, "entry_stopped": False, "max_layers": 8,
        "width_long": 2.5, "width_short": 2.5,           # short 0.0 -> the base 2.5
        "add_long": 9.0, "add_short": 8.0,
        "exit_long": 10.0, "exit_short": 10.0,           # short -1 -> the base 10
        "closes_since_init": 87, "fills": 140,
    }
    if row != want:
        diff = {k: (want.get(k), row.get(k) if row else None) for k in set(want) | set(row or {})
                if (row or {}).get(k) != want.get(k)}
        raise AssertionError(f"row differs (want, got): {diff}")
    if aw.snapshot_row_from_state("X", hb(121), NOW) is not None:
        raise AssertionError("a heartbeat 121 s old must be skipped")
    if aw.snapshot_row_from_state("X", hb(120), NOW) is None:
        raise AssertionError("a heartbeat exactly 120 s old is still written")
    for bad in (None, "", "not json", json.dumps({"instance_id": "X"}), json.dumps([1])):
        if aw.snapshot_row_from_state("X", bad, NOW) is not None:
            raise AssertionError(f"unusable heartbeat {bad!r} must be skipped")
    nobook = aw.snapshot_row_from_state("X", hb(5, book=None, halted="yes", api_count=True), NOW)
    if nobook["mtm_long"] is not None or nobook["mtm_short"] is not None \
            or nobook["halted"] is not None or nobook["api_count"] is not None:
        raise AssertionError(f"no book: MTM per side None; non-bool halted and bool api_count None: {nobook}")
    return "one row from a heartbeat: MTM per side from the book's comments, per-side geometry with fallback, <= 120 s"


class FakeRedis:
    def __init__(self, kv):
        self.kv = dict(kv)

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value, ex=None):
        self.kv[key] = value

    def scan_iter(self, match=None, count=None):
        prefix = (match or "*").rstrip("*")
        return iter(sorted(k for k in self.kv if k.startswith(prefix)))

    def mget(self, keys):
        return [self.kv.get(k) for k in keys]


def _fresh_pg(with_005=True):
    import psycopg2
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS state_snapshots")
        if with_005:
            with open(os.path.join(ROOT, "migrations", "005_c137_state_snapshots.sql")) as f:
                cur.execute(f.read())
    return conn


def check_sn3():
    if not URL:
        raise AssertionError("VERIFY_DATABASE_URL is not set (scratch database only)")
    import archive_worker as aw
    rc = FakeRedis({
        "fxmatrix:state:GRIND_GBPUSD_OPTB": hb(10),
        "fxmatrix:state:GRIND_EURUSD_OPTB": hb(40, instance_id="GRIND_EURUSD_OPTB"),
        "fxmatrix:state:GRIND_NZDCHF_OPTB": hb(600, instance_id="GRIND_NZDCHF_OPTB"),   # stale
        "fxmatrix:state:GRIND_AUDCAD_OPT": "garbage",
        "fxmatrix:scalp_history:GRIND_GBPUSD_OPTB": "[]",                              # not a state key
    })
    conn = _fresh_pg()
    n1 = aw.write_state_snapshots(conn, rc, now=NOW)
    n2 = aw.write_state_snapshots(conn, rc, now=NOW + timedelta(seconds=10))   # same minute
    n3 = aw.write_state_snapshots(conn, rc, now=NOW + timedelta(seconds=30))   # next minute 12:01
    with conn.cursor() as cur:
        cur.execute("SELECT instance_id, snapped_at, mtm_long, add_short FROM state_snapshots"
                    " ORDER BY snapped_at, instance_id")
        rows = cur.fetchall()
    conn.close()
    if (n1, n2, n3) != (2, 0, 2):
        raise AssertionError(f"rows written: expected (2, 0, 2), got {(n1, n2, n3)}")
    got = [(r[0], r[1].astimezone(UTC), float(r[2]), r[3]) for r in rows]
    want = [("GRIND_EURUSD_OPTB", MINUTE, -2.15, 8.0), ("GRIND_GBPUSD_OPTB", MINUTE, -2.15, 8.0),
            ("GRIND_EURUSD_OPTB", MINUTE + timedelta(minutes=1), -2.15, 8.0),
            ("GRIND_GBPUSD_OPTB", MINUTE + timedelta(minutes=1), -2.15, 8.0)]
    if got != want:
        raise AssertionError(f"rows: expected {want}, got {got}")
    conn = _fresh_pg(with_005=False)
    try:
        n = aw.write_state_snapshots(conn, rc, now=NOW)
        with conn.cursor() as cur:
            cur.execute("SELECT 1")          # the connection is usable after the skip
    finally:
        conn.close()
    if n is not None:
        raise AssertionError(f"without migration 005 the write is skipped (None), got {n}")
    return "fresh heartbeats only, one row per instance and minute; skipped quietly before migration 005"


def check_sn4():
    import archive_worker as aw
    calls = []
    orig = aw.write_state_snapshots
    aw.write_state_snapshots = lambda conn, rc, now=None: calls.append(now) or 3
    try:
        rc = FakeRedis({})
        a = aw.try_snapshot_write(None, rc, force=False)
        b = aw.try_snapshot_write(None, rc, force=False)
        c = aw.try_snapshot_write(None, rc, force=True)
    finally:
        aw.write_state_snapshots = orig
    if (a, b, c) != (3, None, 3) or len(calls) != 2:
        raise AssertionError(f"once a minute (then forced): expected (3, None, 3), got {(a, b, c)}")
    src = open(os.path.join(ROOT, "archive_worker.py")).read()
    loop = src[src.index("def worker_loop"):]
    if loop.count("try_snapshot_write(") < 2:
        raise AssertionError("worker_loop must call try_snapshot_write at start and in the loop")
    return "written at most once a minute by the worker loop"


def check_sn5():
    if not URL:
        raise AssertionError("VERIFY_DATABASE_URL is not set (scratch database only)")
    import archive_worker as aw
    rc = FakeRedis({
        "fxmatrix:state:GRIND_GBPUSD_OPTB": hb(10),
        "fxmatrix:state:GRIND_EURUSD_OPTB": hb(10, instance_id="GRIND_EURUSD_OPTB"),
    })
    conn = _fresh_pg()
    for m in range(3):                                   # 12:00, 12:01, 12:02
        aw.write_state_snapshots(conn, rc, now=NOW + timedelta(minutes=m))
    conn.close()
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import archive_counts as ac
    os.environ["DATABASE_URL"] = URL
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc_code = ac.main(["--export-snapshots", "--from", "2026-10-08T12:01:00Z",
                           "--to", "2026-10-08T12:03:00Z", "--instance", "GRIND_GBPUSD_OPTB"])
    lines = buf.getvalue().splitlines()
    recs = [json.loads(ln) for ln in lines]
    if rc_code != 0 or recs[0].get("table") != "_meta" or len(recs) != 3 \
            or [r["snapped_at"][:16] for r in recs[1:]] != ["2026-10-08 12:01", "2026-10-08 12:02"] \
            or any(r["instance_id"] != "GRIND_GBPUSD_OPTB" for r in recs[1:]):
        raise AssertionError(f"JSON lines export: {lines[:4]}")
    buf = io.StringIO()
    with redirect_stdout(buf):
        ac.main(["--export-snapshots", "--from", "2026-10-08T12:00:00Z", "--to", "2026-10-08T12:01:00Z",
                 "--csv"])
    csv_lines = buf.getvalue().splitlines()
    if csv_lines[0] != ",".join(COLUMNS[1:]) or len(csv_lines) != 3:
        raise AssertionError(f"CSV export (from inclusive, to exclusive; two instances at 12:00): {csv_lines[:3]}")
    return "--export-snapshots prints JSON lines or CSV for [from, to), optionally one instance"


def check_sn6():
    if not URL:
        raise AssertionError("VERIFY_DATABASE_URL is not set (scratch database only)")
    # db_migrate applies 005 after 001-004 on an empty database
    import psycopg2
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    conn.close()
    res = subprocess.run([sys.executable, "-B", os.path.join(ROOT, "db_migrate.py")],
                         capture_output=True, text=True, cwd=ROOT,
                         env={**os.environ, "DATABASE_URL": URL})
    if res.returncode != 0 or "Applied 005_c137_state_snapshots" not in res.stdout:
        raise AssertionError(f"db_migrate: {res.stdout[-400:]} {res.stderr[-400:]}")
    return "db_migrate applies 005_c137_state_snapshots after 001-004"


def check_sn7():
    res = subprocess.run([sys.executable, "-B", os.path.join(ROOT, "scripts", "verify_c110_scalp_reads.py")],
                         capture_output=True, text=True, cwd=ROOT)
    if res.returncode != 0:
        raise AssertionError(f"verify_c110 fails: {res.stdout[-600:]}")
    return "C122: verify_c110 passes at this hour (its fixture is dated by broker time)"


CHECKS = [("SN1", check_sn1), ("SN2", check_sn2), ("SN3", check_sn3), ("SN4", check_sn4),
          ("SN5", check_sn5), ("SN6", check_sn6), ("SN7", check_sn7)]


def main():
    passed = failed = 0
    for name, fn in CHECKS:
        try:
            print(f"{name} OK: {fn()}")
            passed += 1
        except Exception as exc:
            print(f"{name} FAIL: {type(exc).__name__}: {exc}")
            failed += 1
    print(f"verify_c137_snapshots {passed}/{passed + failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
