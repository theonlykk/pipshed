"""Verification for the fleet cards' slot and API lines (backlog C7, 30 Sep 2026).

Rules under test (EA source, fxmatrix ea/grind_exitq.mqh 114-185 and
ea/grind_api_counter.mqh 11-14, grind_config.mqh 9-11):
- the account's book = positions + pending orders, against the broker's
  200 (ACCOUNT_LIMIT_ORDERS);
- the EA's entry guard counts positions + orders + every resting non-EXT
  order AGAIN (Grind_SlotRestingEnt) and allows an entry while that total
  is <= 200 - (2 + GRIND_SLOT_MARGIN 4) = 194;
- the daily API counter is ONE shared count per terminal (max, not sum),
  soft warning 1800, entries stop 1900, limit 2000.
A fleet's book is known only when EVERY instance is live with a book;
otherwise the card shows unknown (null), never a partial count.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TOKEN = "k7m9p2x4q"
TEMPLATE = os.path.join(ROOT, "templates", "dashboard.html")
now = datetime.now(timezone.utc)

GRIND_B_INSTANCES = [
    "GRIND_GBPUSD_OPTB", "GRIND_EURUSD_OPTB", "GRIND_EURGBP_OPTB", "GRIND_AUDCAD_OPTB",
    "GRIND_AUDCHF_OPTB", "GRIND_CADCHF_OPTB", "GRIND_NZDCHF_OPTB", "GRIND_NZDCAD_OPTB",
    "GRIND_AUDNZD_OPTB", "GRIND_AUDNZD_ALTB", "GRIND_NZDCAD_ALTB",
]


class FakeRedis:
    def __init__(self):
        self._kv = {}

    def get(self, key):
        return self._kv.get(key)

    def set(self, key, value, ex=None):
        self._kv[key] = value

    def lrange(self, key, start, end):
        return []


def book(n_pos, ent_orders, ext_orders):
    positions = [{"ticket": i, "type": "BUY", "price": 1.0, "profit": -0.1,
                  "comment": "GRIND|OPT|L|L%02d|ENT" % i} for i in range(n_pos)]
    orders = ([{"ticket": 100 + i, "type": "BUY_LIMIT", "price": 0.9,
                "comment": "GRIND|OPT|L|L%02d|ENT" % (n_pos + i)} for i in range(ent_orders)] +
              [{"ticket": 200 + i, "type": "SELL_LIMIT", "price": 1.1,
                "comment": "GRIND|OPT|L|L%02d|EXT" % i} for i in range(ext_orders)])
    return {"positions": positions, "orders": orders}


def HB(api_count, bk=None, **over):
    payload = {
        "_received_at": (now - timedelta(seconds=20)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "net_mtm": -1.0, "open_layers_long": 3, "open_layers_short": 0, "halted": False,
        "api_count": api_count,
        "account_login": 53066709, "account_balance": 10000.0, "account_equity": 9990.0,
    }
    if bk is not None:
        payload["book"] = bk
    payload.update(over)
    return json.dumps(payload)


def strip(fake):
    import app as pipshed
    pipshed.r = fake
    return pipshed.app.test_client().get(f"/api/g/{TOKEN}/fleets").get_json()


def fleet(payload, letter):
    for card in payload.get("fleets") or []:
        if card.get("letter") == letter:
            return card
    raise AssertionError(f"fleet {letter} missing")


def full_fixture(api_of=lambda i: 500 + 40 * i, bk=lambda i: book(3, 2, 2)):
    fake = FakeRedis()
    for i, inst in enumerate(GRIND_B_INSTANCES):
        fake.set(f"fxmatrix:state:{inst}", HB(api_of(i), bk(i)))
    return fake


def check_sl1():
    # 11 instances x (3 positions + 4 orders) = 77; resting non-EXT = 11 x 2 = 22;
    # guard total = 77 + 22 = 99
    b = fleet(strip(full_fixture()), "B").get("book") or {}
    want = {"orders": 44, "slots": 77, "slot_limit": 200, "guard_total": 99, "guard_limit": 194}
    got = {k: b.get(k) for k in want}
    if got != want:
        raise AssertionError(f"book {got} != {want}")
    return "book 77/200 and guard 99/194 from the heartbeat books"


def check_sl2():
    # guard: one instance with no heartbeat -> unknown, not a partial count
    fake = full_fixture()
    fake._kv.pop("fxmatrix:state:GRIND_NZDCHF_OPTB")
    b = fleet(strip(fake), "B").get("book") or {}
    if b.get("slots") is not None or b.get("guard_total") is not None:
        raise AssertionError(f"partial fleet must be unknown: {b}")
    return "an instance missing -> slots and guard unknown (guard)"


def check_sl3():
    # guard: a live instance without a book -> unknown
    fake = full_fixture(bk=lambda i: None if i == 4 else book(3, 2, 2))
    b = fleet(strip(fake), "B").get("book") or {}
    if b.get("slots") is not None or b.get("guard_total") is not None:
        raise AssertionError(f"missing book must be unknown: {b}")
    return "a live instance without a book -> unknown (guard)"


def check_sl4():
    # api_count 500, 540, ..., 900: one shared counter -> the max, 900
    api = fleet(strip(full_fixture()), "B").get("api")
    want = {"count": 900, "limit": 2000, "soft_warn": 1800, "entry_stop": 1900}
    if api != want:
        raise AssertionError(f"api {api} != {want}")
    return "API = max of the shared counter (900) with limit 2000, warn 1800, stop 1900"


def check_sl5():
    fake = FakeRedis()
    api = fleet(strip(fake), "B").get("api")
    if not isinstance(api, dict) or api.get("count") is not None or api.get("limit") != 2000:
        raise AssertionError(f"no live instance -> count None, got {api}")
    return "no live instance -> API count unknown"


# --- the rendered line (the template's own JS in node) ----------------------

def extract_function(src, name):
    m = re.search(r"function " + re.escape(name) + r"\(", src)
    if not m:
        return None
    i = src.index("{", m.end())
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
    return None


def render(cards):
    src = open(TEMPLATE, encoding="utf-8").read()
    names = sorted(set(re.findall(r"function (fleetStrip\w+|fleetSum\w+)\(", src))) + ["renderFleetStrip"]
    js = "\n".join(extract_function(src, n) for n in names)
    js = ("var el = {className: '', innerHTML: ''};\n"
          "var document = {getElementById: function() { return el; }};\n" + js +
          "\nrenderFleetStrip(" + json.dumps({"fleets": cards, "generated_at": None}) + ");\n"
          "console.log(JSON.stringify(el.innerHTML));")
    res = subprocess.run(["node", "-e", js], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr)
    return json.loads(res.stdout.strip().splitlines()[-1])


def card(slots, guard, api):
    return {"letter": "B", "name": "Fleet B (IC)", "badge": "LIVE", "status": "live",
            "health": {"instances_live": 11, "instances_total": 11},
            "account": {}, "risk": {}, "money": {}, "alerts": [], "summary": None,
            "book": {"positions": 33, "pairs": 9, "orders": 44, "slots": slots, "slot_limit": 200,
                     "guard_total": guard, "guard_limit": 194},
            "api": {"count": api, "limit": 2000, "soft_warn": 1800, "entry_stop": 1900}}


def slot_line(html):
    for m in re.finditer(r'<div class="fleet-strip-line">(.*?)</div>', html):
        text = re.sub(r"<[^>]+>", "", m.group(1))
        if text.startswith("Book "):
            return text, m.group(1)
    return None, None


def check_sl6():
    text, _ = slot_line(render([card(77, 99, 900)]))
    want = "Book 77/200 · guard 99/194 · API 900/2000"
    if text != want:
        raise AssertionError(f"line {text!r} != {want!r}")
    return "card line 'Book 77/200 . guard 99/194 . API 900/2000'"


def check_sl7():
    # amber from 180 on the guard (14 slots before entries stop) and from the
    # soft warning on the API; red at the guard limit / the entry stop
    cases = [
        (card(150, 185, 1850), "fleet-num-amber", "fleet-num-amber"),
        (card(190, 194, 1900), "fleet-num-red", "fleet-num-red"),
        (card(77, 99, 900), None, None),
    ]
    for c, gcls, acls in cases:
        _, raw = slot_line(render([c]))
        spans = re.findall(r'<span class="([^"]*)">([^<]*)</span>', raw or "")
        got = {txt: cls for cls, txt in spans}
        g = got.get(str(c["book"]["guard_total"]))
        a = got.get(str(c["api"]["count"]))
        for want, have in ((gcls, g), (acls, a)):
            if have is None:
                ok = False
            elif want:
                ok = want in have
            else:
                ok = "amber" not in have and "red" not in have
            if not ok:
                raise AssertionError(f"classes guard={g!r} api={a!r} for {c['book']['guard_total']}/{c['api']['count']}")
    return "guard amber >= 180, red >= 194; API amber >= 1800, red >= 1900"


def check_sl8():
    # unknown values render as dashes, never as 0
    text, _ = slot_line(render([card(None, None, None)]))
    want = "Book --/200 · guard --/194 · API --/2000"
    if text != want:
        raise AssertionError(f"line {text!r} != {want!r}")
    return "unknowns render as '--'"


CHECKS = [
    ("SL1", check_sl1), ("SL2", check_sl2), ("SL3", check_sl3), ("SL4", check_sl4),
    ("SL5", check_sl5), ("SL6", check_sl6), ("SL7", check_sl7), ("SL8", check_sl8),
]


def main():
    passed = failed = 0
    for name, fn in CHECKS:
        try:
            print(f"{name} OK: {fn()}")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"{name} FAIL: {exc}")
            failed += 1
    print(f"SUMMARY passed={passed} failed={failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
