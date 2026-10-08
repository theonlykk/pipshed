"""Verification: C102, the ejection view off the slow path (fxmatrix backlog
C102; HANDOFF s66).

Measured 8 Oct ~00:00Z by C137's Server-Timing: a /fleets call took 8,830
ms, of which the ejection view 8,727 ms. Profiled on a production-sized
synthetic snapshot (34 instances, 7 days, 4,764 fill rows; 4 fleets' 24 h
views, 3.2 s locally): `closed_trades_from_fills` called
`_layer_from_ent(fill_rows, ...)` and `_sum_deals_for_positions(fill_rows,
...)` for EVERY close, each a scan of every fill row of every fleet for
seven days (quadratic: 90% of the time); most of the rest was
`ftmo_daily._cest_window_utc` recomputing the year's summer-time window on
every call.

Fix: build an index of fill rows by position once; each close reads only
its own positions' rows, in their ORIGINAL order (so the first IN/ENT row
and the first copy of a duplicated deal are the ones a full scan would
have taken). `_cest_window_utc(year)` and `ftmo_day_bounds_utc(day)` are
pure and cached. Nothing in any view changes.

Tests first. Predicted at the tests-only commit: EI1 and EI2 FAIL (the
rows are scanned 1 + 2 x closes times; no cache); EI3, EI4 and EI5 are
guards that pass in both states (the same closes and views as the
2385d24 code).
EI3's order fixture was changed with the code (71's ENT row first; see
order_cases) after two mutants that drop the original order survived.

    python scripts/verify_c102_ejection_index.py
"""
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
UTC = timezone.utc
END = datetime(2026, 10, 8, 0, 30, tzinfo=UTC)
END_MS = int(END.timestamp() * 1000)
BASE_COMMIT = "2385d24"


def synth(insts, days=7, per_day=5, seed=7):
    """A snapshot shaped like the worker's: per close an ENT and an EXT IN
    deal and a close-by pair; some rolls and ejections; scalp rows; one odd
    close-by per fleet; rows shuffled."""
    rnd = random.Random(seed)
    start_ms = END_MS - days * 86400000
    fills, scalps, events = [], [], []
    deal = order = pos = 10 ** 7
    for inst in insts:
        n = days * per_day
        for k in range(n):
            t_close = start_ms + int((k + rnd.random()) * (days * 86400000 / n))
            t_open = t_close - rnd.randint(60000, 3 * 3600000)
            side = rnd.choice("LS")
            idx = rnd.randint(0, 7)
            pos += 2
            order += 1
            ent, ext = pos, pos + 1
            for p, role, t in ((ent, "ENT", t_open), (ext, "EXT", t_close - 1000)):
                deal += 1
                fills.append({"instance_id": inst, "deal_ticket": deal, "order_ticket": deal + 5 * 10 ** 7,
                              "position_id": p, "entry_type": "IN", "deal_type": "IN", "side": side,
                              "layer_index": idx, "role": role, "profit": 0.0, "commission": -0.04,
                              "swap": None, "ea_time_ms": t})
            profit = round(rnd.uniform(-6, 1.2), 2)
            for p in (ent, ext):
                deal += 1
                fills.append({"instance_id": inst, "deal_ticket": deal, "order_ticket": order,
                              "position_id": p, "entry_type": "OUT_BY", "deal_type": "OUT_BY", "side": side,
                              "layer_index": idx, "role": None, "profit": profit if p == ent else 0.0,
                              "commission": 0.0, "swap": round(rnd.uniform(-0.3, 0.1), 2) if p == ent else 0.0,
                              "ea_time_ms": t_close + (0 if p == ent else 300)})
            r = rnd.random()
            code = "ROLL_FILLED" if r < 0.15 else ("EJECT_FILLED" if r < 0.18 else None)
            if code:
                events.append({"instance_id": inst, "code": code.replace("FILLED", "ACCEPTED"), "level": "INFO",
                               "ea_time_ms": t_open + 1000, "ticket": ent, "detail": {"side": side}})
                events.append({"instance_id": inst, "code": code, "level": "INFO", "ea_time_ms": t_close,
                               "ticket": ent, "detail": {"side": side}})
            ct = datetime.fromtimestamp(t_close / 1000, tz=UTC) + timedelta(hours=3)
            scalps.append({"instance_id": inst, "direction": "LONG" if side == "L" else "SHORT",
                           "gross_pnl": profit, "broker_utc_offset_s": 10800, "account_login": 1,
                           "close_time_broker": ct.replace(tzinfo=None).isoformat(),
                           "entry_deal_ticket": None, "exit_deal_ticket": None, "layer_depth": idx})
        deal += 1
        order += 1
        fills.append({"instance_id": inst, "deal_ticket": deal, "order_ticket": order, "position_id": 999,
                      "entry_type": "OUT_BY", "deal_type": "OUT_BY", "side": "L", "layer_index": 0,
                      "role": None, "profit": 1.0, "commission": 0.0, "swap": 0.0,
                      "ea_time_ms": END_MS - 3600000})
    rnd.shuffle(fills)
    events.sort(key=lambda e: e["ea_time_ms"])
    return {"events": events, "scalps": scalps, "fill_logs": fills}


def order_cases():
    """Rows where the ORDER of a full scan decides the answer:
    - close-by 900001 over positions 71 and 72, both with an IN/ENT row; 71's
      row comes first in the list, so the layer is 71 (side L, index 5). A
      set {71, 72} iterates 72 first, so rows gathered per position without
      restoring the list's order would give 72 (mutation round: two such
      mutants survived the first version of this fixture, where 72's row
      came first and the set order happened to agree);
    - position 81's exit deal 880 appears twice with different profit: the
      first copy (1.50) counts, the second (9.99) is a duplicate;
    - position 91: a single OUT with no ENT row (incomplete)."""
    I = "GRIND_GBPUSD_OPTB"
    return [
        {"instance_id": I, "deal_ticket": 702, "order_ticket": 2, "position_id": 71, "entry_type": "IN",
         "deal_type": "IN", "side": "L", "layer_index": 5, "role": "ENT", "profit": 0.0, "commission": -0.04,
         "swap": None, "ea_time_ms": 2},
        {"instance_id": I, "deal_ticket": 701, "order_ticket": 1, "position_id": 72, "entry_type": "IN",
         "deal_type": "IN", "side": "S", "layer_index": 3, "role": "ENT", "profit": 0.0, "commission": -0.04,
         "swap": None, "ea_time_ms": 1},
        {"instance_id": I, "deal_ticket": 703, "order_ticket": 900001, "position_id": 71, "entry_type": "OUT_BY",
         "deal_type": "OUT_BY", "side": "L", "layer_index": 5, "role": None, "profit": 2.0, "commission": 0.0,
         "swap": -0.1, "ea_time_ms": 10},
        {"instance_id": I, "deal_ticket": 704, "order_ticket": 900001, "position_id": 72, "entry_type": "OUT_BY",
         "deal_type": "OUT_BY", "side": "S", "layer_index": 3, "role": None, "profit": -1.0, "commission": 0.0,
         "swap": 0.0, "ea_time_ms": 11},
        {"instance_id": I, "deal_ticket": 801, "order_ticket": 3, "position_id": 81, "entry_type": "IN",
         "deal_type": "IN", "side": "L", "layer_index": 0, "role": "ENT", "profit": 0.0, "commission": -0.04,
         "swap": None, "ea_time_ms": 20},
        {"instance_id": I, "deal_ticket": 880, "order_ticket": 4, "position_id": 81, "entry_type": "OUT",
         "deal_type": "OUT", "side": "L", "layer_index": 0, "role": None, "profit": 1.50, "commission": -0.04,
         "swap": 0.0, "ea_time_ms": 30},
        {"instance_id": I, "deal_ticket": 880, "order_ticket": 4, "position_id": 81, "entry_type": "OUT",
         "deal_type": "OUT", "side": "L", "layer_index": 0, "role": None, "profit": 9.99, "commission": -0.04,
         "swap": 0.0, "ea_time_ms": 31},
        {"instance_id": I, "deal_ticket": 901, "order_ticket": 5, "position_id": 91, "entry_type": "OUT",
         "deal_type": "OUT", "side": "S", "layer_index": None, "role": None, "profit": -3.0, "commission": -0.04,
         "swap": 0.0, "ea_time_ms": 40},
    ]


class CountingList(list):
    """A list that counts how many times it is iterated from the start."""

    def __init__(self, *a):
        super().__init__(*a)
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        return super().__iter__()


def reference_closes(ev, fill_rows):
    """The pre-C102 rule: each close's layer and money from a scan of ALL rows
    (the module's own helpers, called on the full list)."""
    closes, odd = ev.closed_trades_from_fills(fill_rows)
    out = []
    for c in closes:
        positions = set(c["positions"])
        layer_pos, side, idx = ev._layer_from_ent(list(fill_rows), positions)
        gross, commission, swap, net = ev._sum_deals_for_positions(list(fill_rows), positions)
        out.append((layer_pos, idx, gross, None if layer_pos is None else commission,
                    None if layer_pos is None else swap, None if layer_pos is None else net))
    return out


def check_ei1():
    import ejection_view as ev
    rows = CountingList(synth(["GRIND_GBPUSD_OPTB", "GRIND_EURUSD_OPTB"])["fill_logs"])
    closes, _ = ev.closed_trades_from_fills(rows)
    if len(closes) != 70 or rows.iterations > 2:
        raise AssertionError(f"70 closes from {len(rows)} rows: the rows may be walked at most twice "
                             f"(group, index), got {len(closes)} closes and {rows.iterations} walks")
    return f"70 closes from {len(rows)} rows with {rows.iterations} walks of the rows (was 1 + 2 per close)"


def check_ei2():
    import ftmo_daily as fd
    missing = [f for f in ("_cest_window_utc", "ftmo_day_bounds_utc")
               if not hasattr(getattr(fd, f), "cache_info")]
    if missing:
        raise AssertionError(f"not cached: {missing}")
    from datetime import date
    fd.ftmo_day_bounds_utc.cache_clear()
    a = fd.ftmo_day_bounds_utc(date(2026, 10, 8))
    b = fd.ftmo_day_bounds_utc(date(2026, 10, 8))
    want = (datetime(2026, 10, 7, 22, 0, tzinfo=UTC), datetime(2026, 10, 8, 22, 0, tzinfo=UTC))
    winter = fd.ftmo_day_bounds_utc(date(2026, 11, 2))
    if a != want or b is not a or fd.ftmo_day_bounds_utc.cache_info().hits < 1 \
            or winter != (datetime(2026, 11, 1, 23, 0, tzinfo=UTC), datetime(2026, 11, 2, 23, 0, tzinfo=UTC)):
        raise AssertionError(f"bounds {a}, {winter}; cache {fd.ftmo_day_bounds_utc.cache_info()}")
    return "the summer-time window and the FTMO day bounds are cached (8 Oct 22:00Z-22:00Z; 2 Nov 23:00Z)"


def check_ei3():
    import ejection_view as ev
    rows = order_cases() + synth(["GRIND_AUDCHF_OPTC"], per_day=3)["fill_logs"]
    closes, odd = ev.closed_trades_from_fills(rows)
    got = [(c["layer_position"], c["layer_index"], c["gross"], c["commission"], c["swap"], c["net"])
           for c in closes]
    want = reference_closes(ev, rows)
    by = {c["order_ticket"]: c for c in closes}
    cb = by.get(900001) or {}
    dup = next((c for c in closes if c["positions"] == [81]), {})
    lone = next((c for c in closes if c["positions"] == [91]), {})
    if got != want:
        raise AssertionError(f"closes differ from a full scan: {sum(1 for a, b in zip(got, want) if a != b)} of {len(got)}")
    if list({71, 72}) != [72, 71]:
        raise AssertionError("this check needs a set {71, 72} to iterate 72 first (CPython small-int hashing)")
    if (cb.get("layer_position"), cb.get("side"), cb.get("layer_index"), cb.get("gross")) != (71, "L", 5, 1.0):
        raise AssertionError(f"close-by 900001: the first ENT row in the list (71, L, 5) and gross 1.0; got {cb}")
    if (dup.get("gross"), dup.get("commission")) != (1.5, -0.08) or lone.get("incomplete") is not True:
        raise AssertionError(f"duplicate deal counted once (1.5, -0.08), lone OUT incomplete; got {dup}, {lone}")
    return "every close's layer and money equal a full scan's (first ENT, first copy of a deal)"


def _load_base():
    res = subprocess.run(["git", "-C", ROOT, "show", f"{BASE_COMMIT}:ejection_view.py"],
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise AssertionError(f"git show {BASE_COMMIT}:ejection_view.py failed: {res.stderr[-200:]}")
    d = tempfile.mkdtemp()
    path = os.path.join(d, "ejection_view_base.py")
    with open(path, "w") as f:
        f.write(res.stdout)
    spec = importlib.util.spec_from_file_location("ejection_view_base_c102", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_ei4():
    import app
    import ejection_view as ev
    base = _load_base()
    fleets = [(e["letter"], list(e["instances"])) for e in app.FLEET_STRIP if not e.get("placeholder")]
    snap = synth([i for _, insts in fleets for i in insts])
    snap["fill_logs"] = order_cases() + snap["fill_logs"]
    timings = {}
    views = {}
    for name, mod in (("base", base), ("now", ev)):
        t = time.perf_counter()
        views[name] = {}
        for letter, insts in fleets:
            for hours in (24, 168):
                views[name][(letter, hours)] = mod.build_ejection_view(
                    generated_at="x", fleet=letter, fleet_label="", hours=hours, grind_instances=insts,
                    events=snap["events"], scalps=snap["scalps"], fill_logs=snap["fill_logs"],
                    state_by_instance={}, now_dt=END, window_start_ms=END_MS - hours * 3600000,
                    window_end_ms=END_MS)
        timings[name] = time.perf_counter() - t
    a = json.dumps({str(k): v for k, v in views["base"].items()}, sort_keys=True, default=str)
    b = json.dumps({str(k): v for k, v in views["now"].items()}, sort_keys=True, default=str)
    if a != b:
        raise AssertionError("the views differ from the 2385d24 code's")
    return (f"4 fleets x (24 h, 168 h) views identical to {BASE_COMMIT}'s "
            f"({len(snap['fill_logs'])} fill rows; {timings['base']:.2f} s then, {timings['now']:.2f} s now)")


def check_ei5():
    scripts = ["verify_ejection_telemetry.py", "verify_fleet_strip.py", "verify_daily_snapshots.py",
               "verify_critical_resolved.py", "verify_c137_sr_table.py"]
    bad = []
    for s in scripts:
        res = subprocess.run([sys.executable, "-B", os.path.join(ROOT, "scripts", s)],
                             capture_output=True, text=True, cwd=ROOT)
        if res.returncode != 0:
            bad.append(s)
    if bad:
        raise AssertionError(f"failing: {bad}")
    return "the ejection, strip, daily, critical and C137 suites still pass"


CHECKS = [("EI1", check_ei1), ("EI2", check_ei2), ("EI3", check_ei3), ("EI4", check_ei4), ("EI5", check_ei5)]


def main():
    passed = failed = 0
    for name, fn in CHECKS:
        try:
            print(f"{name} OK: {fn()}")
            passed += 1
        except Exception as exc:
            print(f"{name} FAIL: {type(exc).__name__}: {exc}")
            failed += 1
    print(f"verify_c102_ejection_index {passed}/{passed + failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
