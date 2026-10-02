"""Verification: C110, scalp-list reads cost what changed, not the whole list.

pipshed.com 2 Oct 2026 (~16:18Z onwards): CPU pinned at ~4-4.5 vCPU (all four
gunicorn workers busy), memory 0.6 -> 1.6 GB, EA pushes answered 499 (client
gone) and page calls taking 19 s - 2 min, with ONE dashboard tab polling.
Cause: every read of a scalp list parsed ALL of it (`lrange 0 -1` +
`json.loads` per row). Each list holds up to 3,000 rows
(SCALP_HISTORY_LIST_MAX). Per open page and per 30 s, the fleet strip parsed
every instance of all four fleets twice (today + cycle), `today_scalps` and
`scalps` parsed A's ids again, and the daily summary (every 5 s) parsed A's
ids once more. In process, with full lists: one strip call = 81 MB read from
Redis and ~1.2 s CPU; the 5-s daily summary 18 MB. The lists only grow (the
lattice scalps hard), so the cost grew every day until one page was enough.

Rule (C110):
1. Server: one reader, `_scalp_history_records(instance_id)`, used by every
   path that reads a scalp list. It keeps the parsed list per process and
   re-reads only what changed. Its premise is the list's only writer,
   `telemetry_scalp_closed`: LPUSH a row, then LTRIM to
   SCALP_HISTORY_LIST_MAX + 1 rows (newest first). A read checks the cached
   head (index 0); new rows are found by locating the cached head further
   down; the length follows from the cap; the tail (index -1) must match, or
   the whole list is read again. Unchanged list = two one-row reads.
2. Page: every poller runs through `pollNoOverlap(fn, ms)`: a tick is
   skipped while that poller's previous call is still running, so slow
   answers can no longer pile up behind one tab.

Tests first. Predicted at the tests-only commit: SR1, SR2, SR4 and SR5 FAIL
(no reader, full reads every time, bare setInterval); SR3 and SR6 are
guards that pass in both states.

    python scripts/verify_c110_scalp_reads.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["GRIND_FLEET"] = "A"
os.environ.pop("GRIND_FLEET_LABEL", None)

import app as pipshed  # noqa: E402

SCALP_PREFIX = "fxmatrix:scalp_history:"
TOKEN = pipshed.PUBLIC_GRIND_STATUS_TOKEN


class FakeRedis:
    """Lists behave like Redis lists (LPUSH, LTRIM, LRANGE with negative
    indexes); bytes and calls on scalp lists are counted."""

    def __init__(self):
        self.kv = {}
        self.lists = {}
        self.scalp_bytes = 0
        self.scalp_calls = 0

    # strings
    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value, ex=None):
        self.kv[key] = value

    def mget(self, keys):
        return [self.kv.get(k) for k in keys]

    def delete(self, *keys):
        for k in keys:
            self.kv.pop(k, None)
            self.lists.pop(k, None)

    # lists
    def lpush(self, key, *values):
        lst = self.lists.setdefault(key, [])
        for v in values:
            lst.insert(0, v)
        return len(lst)

    def ltrim(self, key, start, end):
        lst = self.lists.get(key, [])
        n = len(lst)
        s = start + n if start < 0 else start
        e = end + n if end < 0 else end
        self.lists[key] = lst[max(s, 0):e + 1] if e >= s else []

    def llen(self, key):
        return len(self.lists.get(key, []))

    def lrange(self, key, start, end):
        lst = self.lists.get(key, [])
        n = len(lst)
        s = start + n if start < 0 else start
        e = end + n if end < 0 else end
        out = lst[max(s, 0):e + 1] if e >= max(s, 0) else []
        if key.startswith(SCALP_PREFIX):
            self.scalp_calls += 1
            self.scalp_bytes += sum(len(x) for x in out)
        return out

    def lindex(self, key, index):
        out = self.lrange(key, index, index)
        return out[0] if out else None

    def expire(self, key, seconds):
        return True

    def hgetall(self, key):
        return {}

    def hget(self, key, field):
        return None

    def hset(self, *a, **kw):
        return 1

    def rpush(self, key, *values):
        self.lists.setdefault(key, []).extend(values)

    def pipeline(self):
        return _Pipe(self)


class _Pipe:
    def __init__(self, fake):
        self.fake = fake
        self.ops = []

    def __getattr__(self, name):
        def queue(*a, **kw):
            self.ops.append((name, a, kw))
            return self
        return queue

    def execute(self):
        return [getattr(self.fake, n)(*a, **kw) for n, a, kw in self.ops]


now = datetime.now(timezone.utc)
CAP = pipshed.SCALP_HISTORY_LIST_MAX + 1


def scalp_row(inst, i, minutes_ago, **over):
    ct = now - timedelta(minutes=minutes_ago)
    row = {
        "close_time": ct.strftime("%Y-%m-%d %H:%M:%S"),
        "trade_date": ct.strftime("%Y-%m-%d"),
        "instrument": inst.split("_")[1],
        "direction": "LONG" if i % 2 else "SHORT",
        "entry_price": 1.32206,
        "exit_price": 1.32306,
        "layer_depth": i % 8,
        "stack_depth": 1 + i % 8,
        "gross_pnl": round(0.5 + (i % 7) * 0.1, 2),
        "instance_id": inst,
        "ejected": i % 97 == 0,
        "rolled": i % 89 == 0,
        "broker_utc_offset_s": 10800,
        "account_login": 53066709,
        "seq": i,
    }
    row.update(over)
    return json.dumps(row)


def push(fake, inst, raw):
    """The production write, exactly: LPUSH then LTRIM 0..LIST_MAX."""
    key = SCALP_PREFIX + inst
    fake.lpush(key, raw)
    fake.ltrim(key, 0, pipshed.SCALP_HISTORY_LIST_MAX)


def full_parse(fake, inst):
    return [json.loads(x) for x in fake.lists.get(SCALP_PREFIX + inst, [])]


def all_instances():
    ids = []
    for lst in pipshed.GRIND_FLEET_INSTANCES.values():
        for i in lst:
            if i not in ids:
                ids.append(i)
    return ids


results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")


def reader():
    return getattr(pipshed, "_scalp_history_records", None)


# ---------------------------------------------------------------- SR1
def sr1_reader_matches_full_parse():
    """After every kind of change the production writer can make (and a list
    that expired and came back, and a new Redis client), the reader returns
    exactly the parsed list."""
    read = reader()
    if read is None:
        check("SR1", False, "_scalp_history_records missing")
        return
    fake = FakeRedis()
    pipshed.r = fake
    inst = "GRIND_GBPUSD_OPTB"
    bad = []
    seq = 0

    def step(label, n_push, dup=False):
        nonlocal seq
        for _ in range(n_push):
            seq += 1
            raw = scalp_row(inst, seq, 0) if not dup else fake.lists[SCALP_PREFIX + inst][0]
            push(fake, inst, raw)
        got = read(inst)
        want = full_parse(fake, inst)
        if got != want:
            bad.append(f"{label}: got {len(got)} rows, want {len(want)}")

    step("empty", 0)
    step("one row", 1)
    step("unchanged", 0)
    step("+5", 5)
    step("+63 (one chunk)", 63)
    step("+64", 64)
    step("+1500 (several chunks)", 1500)
    step("to the cap", CAP)
    step("at cap +1", 1)
    step("at cap +700", 700)
    step("at cap, unchanged", 0)
    step("identical payload pushed on top", 1, dup=True)
    step("identical again", 2, dup=True)
    step("at cap +2999", CAP - 1)
    step("at cap +3000 (all new)", CAP)
    step("at cap +4500 (more than the list)", 4500)
    # the list expired (TTL) and came back with new rows
    fake.delete(SCALP_PREFIX + inst)
    step("expired, read", 0)
    step("recreated +3", 3)
    # a different Redis client (another worker, a test's new fake)
    fake2 = FakeRedis()
    fake2.lists[SCALP_PREFIX + inst] = [scalp_row(inst, 9000 + k, k) for k in range(10)]
    pipshed.r = fake2
    if read(inst) != full_parse(fake2, inst):
        bad.append("new client: stale rows")
    check("SR1", not bad, "; ".join(bad) if bad else "every step equals the full parse")


# ---------------------------------------------------------------- fixture
def full_fixture():
    fake = FakeRedis()
    for inst in all_instances():
        key = SCALP_PREFIX + inst
        # newest first: index 0 is the most recent close
        fake.lists[key] = [scalp_row(inst, k, 4 * k) for k in range(CAP)]
        fake.kv[f"fxmatrix:state:{inst}"] = json.dumps({
            "_received_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "open_layers_long": 2, "open_layers_short": 0, "halted": False,
        })
    return fake


def fleets_summaries(client):
    data = client.get(f"/api/g/{TOKEN}/fleets/1").get_json()
    return {f["letter"]: f.get("summary") for f in data["fleets"]}


# ---------------------------------------------------------------- SR2
def sr2_steady_state_reads_little():
    """Strip polls on unchanged lists read almost nothing; one new scalp per
    instance reads almost nothing; the summaries are still computed."""
    fake = full_fixture()
    pipshed.r = fake
    c = pipshed.app.test_client()
    if hasattr(pipshed, "_SCALP_CACHE"):
        pipshed._SCALP_CACHE.clear()
    fake.scalp_bytes = 0
    s1 = fleets_summaries(c)
    first = fake.scalp_bytes
    fake.scalp_bytes = 0
    s2 = fleets_summaries(c)
    second = fake.scalp_bytes
    for inst in pipshed.GRIND_FLEET_INSTANCES["B"]:
        push(fake, inst, scalp_row(inst, 99999, 0))
    fake.scalp_bytes = 0
    s3 = fleets_summaries(c)
    third = fake.scalp_bytes
    missing = [k for k, v in s3.items() if v is None and k != "D"] if s3 else ["all"]
    ok = (first > 0 and second <= first * 0.01 and third <= first * 0.02
          and not missing and s1 == s2)
    check("SR2", ok,
          f"bytes first {first/1e6:.1f} MB, unchanged {second/1e3:.0f} kB, "
          f"+1 row x11 {third/1e3:.0f} kB; summaries missing {missing}")


# ---------------------------------------------------------------- SR3
def sr3_outputs_unchanged():
    """Guard: the scalp endpoints answer the same JSON whether the reader's
    cache is warm (after pushes) or cold (a fresh client, full reads)."""
    urls = [
        "/api/telemetry/today_scalps",
        "/api/telemetry/scalps?instance=GRIND_GBPUSD_OPT&per_page=50",
        f"/api/g/{TOKEN}/scalps/1",
    ]
    fake = full_fixture()
    pipshed.r = fake
    c = pipshed.app.test_client()
    for u in urls:
        c.get(u)
    fleets_summaries(c)
    for inst in all_instances()[:20]:
        for k in range(3):
            push(fake, inst, scalp_row(inst, 50000 + k, 0))
    warm = [c.get(u).get_json() for u in urls] + [fleets_summaries(c)]
    cold_fake = FakeRedis()
    cold_fake.lists = {k: list(v) for k, v in fake.lists.items()}
    cold_fake.kv = dict(fake.kv)
    pipshed.r = cold_fake
    if hasattr(pipshed, "_SCALP_CACHE"):
        pipshed._SCALP_CACHE.clear()
    cold = [c.get(u).get_json() for u in urls] + [fleets_summaries(c)]
    diffs = [u for u, a, b in zip(urls + ["fleets"], warm, cold) if a != b]
    nonempty = warm[0] and warm[0].get("total", 0) > 0
    check("SR3", not diffs and nonempty, f"differences: {diffs or 'none'}")


# ---------------------------------------------------------------- SR4
def _template():
    with open(os.path.join(ROOT, "templates", "dashboard.html"), encoding="utf-8") as f:
        return f.read()


def sr4_template_pollers_do_not_overlap():
    t = _template()
    bare = re.findall(r"setInterval\(\s*fetch\w+", t)
    defined = len(re.findall(r"function pollNoOverlap\(", t))
    first_def = t.find("function pollNoOverlap(")
    first_use = t.find("pollNoOverlap(fetch")
    uses = len(re.findall(r"pollNoOverlap\(\s*fetch\w+\s*,\s*\d+\s*\)", t))
    ok = (not bare and defined == 1 and uses == 13
          and 0 <= first_def < first_use)
    check("SR4", ok, f"bare setInterval(fetch...) {len(bare)}, helper defined {defined}, "
                     f"pollers wrapped {uses}")


# ---------------------------------------------------------------- SR5
NODE_HARNESS = r"""
const src = require('fs').readFileSync(process.argv[2], 'utf8');
let ticks = [];
global.setInterval = function (fn, ms) { ticks.push(fn); return ticks.length; };
eval(src + '\n;global.pollNoOverlap = pollNoOverlap;');
let calls = 0, release;
async function slow() { calls++; await new Promise(r => { release = r; }); }
pollNoOverlap(slow, 30000);
(async () => {
  const tick = ticks[0];
  tick(); tick(); tick();               // three ticks while the first call runs
  await new Promise(r => setImmediate(r));
  const during = calls;
  release(); await new Promise(r => setImmediate(r));
  tick(); await new Promise(r => setImmediate(r));
  const after = calls;
  let threw = 0;
  async function bad() { threw++; throw new Error('x'); }
  ticks = [];
  pollNoOverlap(bad, 5000);
  ticks[0](); await new Promise(r => setImmediate(r));
  ticks[0](); await new Promise(r => setImmediate(r));
  console.log(JSON.stringify({during, after, threw}));
})();
"""


def sr5_helper_behaviour():
    """The helper (run in node): ticks while a call is in flight are skipped;
    the next tick after it finishes runs; a throwing poller does not wedge it."""
    t = _template()
    m = re.search(r"function pollNoOverlap\(.*?\n\s*\}\n", t, re.S)
    if not m:
        check("SR5", False, "pollNoOverlap not found")
        return
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(m.group(0))
        helper = f.name
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(NODE_HARNESS)
        harness = f.name
    try:
        out = subprocess.run(["node", harness, helper], capture_output=True, text=True, timeout=30)
        res = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception as exc:  # noqa: BLE001
        check("SR5", False, f"node run failed: {exc}")
        return
    ok = res == {"during": 1, "after": 2, "threw": 2}
    check("SR5", ok, f"{res} (want during 1, after 2, threw 2)")


# ---------------------------------------------------------------- SR6
def sr6_writer_premise():
    """Guard: the reader's premise. The only write to a scalp list is LPUSH
    then LTRIM 0..SCALP_HISTORY_LIST_MAX in telemetry_scalp_closed."""
    with open(os.path.join(ROOT, "app.py"), encoding="utf-8") as f:
        src = f.read()
    write_re = re.compile(r"\.(lpush|rpush|lset|lrem|linsert|ltrim|delete|unlink|rename|lpop|rpop)\(")
    funcs = re.split(r"\n(?=def |@app\.route)", src)
    writers = []
    ordered = False
    for chunk in funcs:
        if "scalp_history:" not in chunk or not write_re.search(chunk):
            continue
        name = re.search(r"def (\w+)", chunk)
        name = name.group(1) if name else "?"
        if name == "telemetry_scalp_closed":
            ordered = re.search(
                r"redis_key = f\"fxmatrix:scalp_history:\{instance_id\}\".*?"
                r"pipe\.lpush\(redis_key,.*?\n\s*pipe\.ltrim\(redis_key, 0, SCALP_HISTORY_LIST_MAX\)",
                chunk, re.S) is not None
            other = [w for w in write_re.findall(chunk) if w not in ("lpush", "ltrim", "rpush")]
            if other:
                writers.append(f"{name}:{other}")
        else:
            writers.append(name)
    ok = ordered and not writers
    check("SR6", ok, f"LPUSH+LTRIM in telemetry_scalp_closed {ordered}; other writers {writers or 'none'}")


def main():
    sr1_reader_matches_full_parse()
    sr2_steady_state_reads_little()
    sr3_outputs_unchanged()
    sr4_template_pollers_do_not_overlap()
    sr5_helper_behaviour()
    sr6_writer_premise()
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"verify_c110_scalp_reads {passed}/{len(results)}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
