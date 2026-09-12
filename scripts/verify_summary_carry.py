"""Verification for daily summary text and carry audit routes (mock Redis, no network)."""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockRedis:
    def __init__(self):
        self._data = {}
        self._lists = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value, ex=None):
        self._data[key] = value

    def lrange(self, key, start, end):
        items = self._lists.get(key, [])
        if end == -1:
            end = len(items) - 1
        if not items or start > end:
            return []
        return items[start : end + 1]


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _seed_heartbeat(mock, instance_id, orders=None, positions=None,
                    open_long=0, open_short=0, balance=100000.00, equity=100050.25):
    payload = {
        "instance_id": instance_id,
        "timestamp": _utc_now_iso(),
        "account_balance": balance,
        "account_equity": equity,
        "open_layers_long": open_long,
        "open_layers_short": open_short,
        "book": {
            "positions": positions or [],
            "orders": orders or [],
        },
    }
    mock.set(f"fxmatrix:state:{instance_id}", json.dumps(payload))


def _seed_scalp(mock, instance_id, instrument, entry, exit_price, gross_pnl, trade_date):
    record = {
        "close_time": f"{trade_date}T15:30:00+00:00",
        "trade_date": trade_date,
        "instrument": instrument,
        "direction": "LONG",
        "entry_price": entry,
        "exit_price": exit_price,
        "gross_pnl": gross_pnl,
    }
    key = f"fxmatrix:scalp_history:{instance_id}"
    mock._lists.setdefault(key, []).append(json.dumps(record))


def _carry_table(rows):
    return {"generated_at": _utc_now_iso(), "rows": rows}


def test_s1_summary_text():
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()
    broker_day = pipshed._broker_today()

    _seed_heartbeat(mock, "GRIND_EURGBP_OPT")
    _seed_scalp(mock, "GRIND_EURGBP_OPT", "EURGBP", 0.85000, 0.85020, 2.00, broker_day)
    _seed_scalp(mock, "GRIND_EURGBP_OPT", "EURGBP", 0.85100, 0.85110, 1.00, broker_day)
    _seed_scalp(mock, "GRIND_AUDCAD_OPT", "AUDCAD", 0.90000, 0.90020, 2.00, broker_day)

    resp = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/summary")
    assert resp.status_code == 200, resp.data
    assert resp.content_type.startswith("text/plain")
    text = resp.get_data(as_text=True)

    assert "FXGRIND --" in text
    assert "3 closed" in text
    assert "+5.0 pips" in text
    assert "+5.00 USD gross" in text
    assert "Commission -0.15 USD" in text
    assert "Net +4.85 USD" in text
    assert "Equity 100,050.25" in text
    assert "Balance 100,000.00 USD" in text

    eurgbp_pos = text.find("EURGBP")
    audcad_pos = text.find("AUDCAD")
    assert eurgbp_pos != -1 and audcad_pos != -1
    assert eurgbp_pos < audcad_pos, "EURGBP line should appear before AUDCAD (USD desc)"

    eurgbp_line = [ln for ln in text.splitlines() if "EURGBP" in ln][0]
    assert "2 scalps" in eurgbp_line
    assert "+3.0 pips" in eurgbp_line
    assert "+3.00 USD" in eurgbp_line

    audcad_line = [ln for ln in text.splitlines() if "AUDCAD" in ln][0]
    assert "1 scalp" in audcad_line
    assert "+2.0 pips" in audcad_line
    assert "+2.00 USD" in audcad_line

    print("S1 OK: summary text counts, pips, USD order, commission")


def test_s2_empty_day():
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()

    _seed_heartbeat(mock, "GRIND_GBPUSD_OPT")

    resp = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/summary")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "Scalps       none closed" in text
    assert "Equity 100,050.25" in text
    print("S2 OK: empty day message with equity")


def test_s3_cycle_start_default():
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()
    old_cycle = pipshed.CYCLE_START_DATE
    pipshed.CYCLE_START_DATE = pipshed.DEFAULT_CYCLE_START_DATE
    try:
        _seed_heartbeat(mock, "GRIND_GBPUSD_OPT")
        resp = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/summary")
        text = resp.get_data(as_text=True)
        assert "since Thu 10 Sep 2026" in text
        print("S3 OK: default cycle start date used when env unset")
    finally:
        pipshed.CYCLE_START_DATE = old_cycle


def _ext_order(comment, price, order_type="ORDER_TYPE_SELL_LIMIT"):
    return {
        "ticket": 1001,
        "type": order_type,
        "price": price,
        "open_time": "2026-09-12T10:00:00",
        "comment": comment,
    }


def test_c1_long_ext_carry():
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()

    carry = _carry_table([{
        "symbol": "EURGBP",
        "long_pips": -0.706,
        "short_pips": -0.500,
        "mult": 1,
        "digits": 4,
    }])
    mock.set(pipshed.ARCHIVE_CARRY_KEY, json.dumps(carry))
    _seed_heartbeat(
        mock,
        "GRIND_EURGBP_OPT",
        orders=[_ext_order("GRIND|OPT|L|L00|EXT", 0.85908)],
    )

    resp = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/carry_audit")
    assert resp.status_code == 200
    rows = resp.get_json()["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["changed"] is True
    assert row["why"] == "carry applied"
    assert abs(row["price_tonight"] - 0.85979) < 0.000005
    print("C1 OK: long EXT carry moves exit to 0.85979")


def test_c2_short_ext_carry():
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()

    carry = _carry_table([{
        "symbol": "AUDCAD",
        "long_pips": -0.500,
        "short_pips": -1.067,
        "mult": 1,
        "digits": 4,
    }])
    mock.set(pipshed.ARCHIVE_CARRY_KEY, json.dumps(carry))
    _seed_heartbeat(
        mock,
        "GRIND_AUDCAD_OPT",
        orders=[_ext_order("GRIND|OPT|S|L01|EXT", 0.58290, "ORDER_TYPE_BUY_LIMIT")],
    )

    resp = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/carry_audit")
    rows = resp.get_json()["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["changed"] is True
    assert abs(row["price_tonight"] - 0.58183) < 0.000005
    print("C2 OK: short EXT carry moves exit to 0.58183")


def test_c3_ent_unchanged():
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()

    carry = _carry_table([{
        "symbol": "EURGBP",
        "long_pips": -0.706,
        "short_pips": -0.500,
        "mult": 1,
        "digits": 4,
    }])
    mock.set(pipshed.ARCHIVE_CARRY_KEY, json.dumps(carry))
    _seed_heartbeat(
        mock,
        "GRIND_EURGBP_OPT",
        orders=[_ext_order("GRIND|OPT|L|L00|ENT", 0.85000, "ORDER_TYPE_BUY_LIMIT")],
    )

    resp = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/carry_audit")
    row = resp.get_json()["rows"][0]
    assert row["changed"] is False
    assert row["price_tonight"] == row["price_now"]
    assert row["why"] == "entry order -- carry applies to inventory, not unfilled quotes"
    print("C3 OK: ENT order unchanged with entry reason")


def test_c4_unparsed_comment():
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()

    carry = _carry_table([{
        "symbol": "EURGBP",
        "long_pips": -0.706,
        "short_pips": -0.500,
        "mult": 1,
        "digits": 4,
    }])
    mock.set(pipshed.ARCHIVE_CARRY_KEY, json.dumps(carry))
    _seed_heartbeat(
        mock,
        "GRIND_EURGBP_OPT",
        orders=[_ext_order("manual-order", 0.86000)],
    )

    resp = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/carry_audit")
    row = resp.get_json()["rows"][0]
    assert row["changed"] is False
    assert row["why"] == "unparsed comment"
    print("C4 OK: unparsed comment listed unchanged")


def test_c5_no_carry_data():
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()

    mock.set(pipshed.ARCHIVE_CARRY_KEY, json.dumps(_carry_table([])))
    _seed_heartbeat(
        mock,
        "GRIND_EURGBP_OPT",
        orders=[_ext_order("GRIND|OPT|L|L00|EXT", 0.85908)],
    )

    resp = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/carry_audit")
    row = resp.get_json()["rows"][0]
    assert row["changed"] is False
    assert row["why"] == "no carry data"
    print("C5 OK: missing symbol carry yields no carry data")


def test_s4_layout_order():
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()
    broker_day = pipshed._broker_today()

    _seed_heartbeat(mock, "GRIND_EURGBP_OPT")
    _seed_scalp(mock, "GRIND_EURGBP_OPT", "EURGBP", 0.85000, 0.85020, 2.00, broker_day)

    resp = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/summary")
    text = resp.get_data(as_text=True)

    account_pos = text.find("Account")
    open_mtm_pos = text.find("Open MTM")
    scalps_pos = text.find("Scalps")
    symbol_pos = text.find("EURGBP")
    assert account_pos != -1 and open_mtm_pos != -1
    assert account_pos < open_mtm_pos, "Account must appear before Open MTM"
    assert scalps_pos != -1 and symbol_pos != -1
    assert scalps_pos < symbol_pos, "Scalps block must appear before per-symbol lines"
    print("S4 OK: layout order account before MTM, scalps before symbols")


def test_s5_financing_accrued():
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()

    _seed_heartbeat(
        mock,
        "GRIND_GBPUSD_OPT",
        balance=10036.66,
        equity=10007.24,
        positions=[{"ticket": 1, "profit": -27.20}],
    )

    resp = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/summary")
    text = resp.get_data(as_text=True)
    assert "Financing accrued -2.22 USD" in text
    print("S5 OK: financing accrued derived from equity, balance, MTM")


def test_s6_cycle_day_count():
    import app as pipshed
    from unittest.mock import patch

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()
    old_cycle = pipshed.CYCLE_START_DATE
    pipshed.CYCLE_START_DATE = "2026-09-10"
    try:
        _seed_heartbeat(mock, "GRIND_GBPUSD_OPT")
        with patch.object(pipshed, "_broker_today", return_value="2026-09-12"):
            resp = client.get(
                "/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/summary?date=2026-09-12"
            )
            text = resp.get_data(as_text=True)
            assert "day 2" in text
        print("S6 OK: cycle weekday count for Sat 2026-09-12 is day 2")
    finally:
        pipshed.CYCLE_START_DATE = old_cycle


def test_s7_cycle_totals_multi_day():
    import app as pipshed
    from unittest.mock import patch

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()
    old_cycle = pipshed.CYCLE_START_DATE
    pipshed.CYCLE_START_DATE = "2026-09-10"
    try:
        _seed_heartbeat(mock, "GRIND_GBPUSD_OPT")
        _seed_scalp(mock, "GRIND_EURGBP_OPT", "EURGBP", 0.85, 0.85020, 2.00, "2026-09-10")
        _seed_scalp(mock, "GRIND_EURGBP_OPT", "EURGBP", 0.86, 0.86020, 3.00, "2026-09-11")
        _seed_scalp(mock, "GRIND_AUDCAD_OPT", "AUDCAD", 0.90, 0.90020, 4.00, "2026-09-12")
        with patch.object(pipshed, "_broker_today", return_value="2026-09-12"):
            resp = client.get(
                "/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/summary?date=2026-09-12"
            )
            text = resp.get_data(as_text=True)
            assert "1 closed" in text
            totals_line = [
                ln for ln in text.splitlines()
                if ln.startswith("             ") and "USD gross" in ln
            ]
            assert totals_line, "missing cycle totals line"
            assert "3 scalps, +9.00 USD gross" in totals_line[0]
        print("S7 OK: cycle totals aggregate scalps across broker days")
    finally:
        pipshed.CYCLE_START_DATE = old_cycle


def test_s8_historical_date_markers():
    import app as pipshed
    from unittest.mock import patch

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()

    _seed_heartbeat(mock, "GRIND_GBPUSD_OPT")
    with patch.object(pipshed, "_broker_today", return_value="2026-09-12"):
        resp = client.get(
            "/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/summary?date=2026-09-11"
        )
        text = resp.get_data(as_text=True)
        assert "(historical)" in text
        assert "(live, not historical)" in text
    print("S8 OK: historical date marks header and live account suffix")


def test_s9_invalid_date():
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()

    resp = client.get("/api/g/" + pipshed.PUBLIC_GRIND_STATUS_TOKEN + "/summary?date=not-a-date")
    assert resp.status_code == 400
    assert resp.content_type.startswith("text/plain")
    print("S9 OK: invalid date returns 400 plain text")


def test_s10_collect_scalp_records_between():
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock

    _seed_scalp(mock, "GRIND_EURGBP_OPT", "EURGBP", 0.85, 0.85020, 1.00, "2026-09-10")
    _seed_scalp(mock, "GRIND_EURGBP_OPT", "EURGBP", 0.86, 0.86020, 2.00, "2026-09-11")
    _seed_scalp(mock, "GRIND_EURGBP_OPT", "EURGBP", 0.87, 0.87020, 3.00, "2026-09-12")

    records = pipshed._collect_scalp_records_between("2026-09-10", "2026-09-11")
    dates = {pipshed._closed_record_date(rec) for rec in records}
    assert dates == {"2026-09-10", "2026-09-11"}
    assert len(records) == 2
    print("S10 OK: range helper returns inclusive broker dates only")


def test_c7_mult_tomorrow_carry_build():
    from datetime import datetime as dt, timezone as tz
    import archive_worker as aw
    from verify_carry_table import FakeConnection

    conn = FakeConnection()
    conn.carry_rows = [
        (
            "EURGBP", "-7.06", "0.37", "0", "0", "0", "1", "3", "1", "5",
            "true", dt(2026, 9, 12, 22, 34, tzinfo=tz.utc),
        ),
    ]
    table = aw.build_carry_table(conn)
    row = table["rows"][0]
    assert row["long_pips"] == -0.706
    assert row["mult_used"] == 1
    print("C7 OK: mult_tomorrow drives published long_pips and mult_used")


def test_c8_mult_tomorrow_fallback():
    from datetime import datetime as dt, timezone as tz
    import archive_worker as aw
    from verify_carry_table import FakeConnection

    conn = FakeConnection()
    conn.carry_rows = [
        (
            "EURGBP", "-7.06", "0.37", "-0.706", "0.037", "1", None, "3", "1", "5",
            "true", dt(2026, 9, 11, 22, 34, tzinfo=tz.utc),
        ),
    ]
    table = aw.build_carry_table(conn)
    row = table["rows"][0]
    assert row["long_pips"] == -0.706
    assert row["mult_used"] == 1
    assert row["mult_snapshot"] == 1
    print("C8 OK: absent mult_tomorrow falls back to multiplier")


def test_c6_wrong_token():
    import app as pipshed

    mock = MockRedis()
    pipshed.r = mock
    client = pipshed.app.test_client()

    resp = client.get("/api/g/wrong-token/summary")
    assert resp.status_code == 404
    resp = client.get("/api/g/wrong-token/carry_audit")
    assert resp.status_code == 404
    print("C6 OK: both routes 404 on wrong token")


def main():
    test_s1_summary_text()
    test_s2_empty_day()
    test_s3_cycle_start_default()
    test_s4_layout_order()
    test_s5_financing_accrued()
    test_s6_cycle_day_count()
    test_s7_cycle_totals_multi_day()
    test_s8_historical_date_markers()
    test_s9_invalid_date()
    test_s10_collect_scalp_records_between()
    test_c1_long_ext_carry()
    test_c2_short_ext_carry()
    test_c3_ent_unchanged()
    test_c4_unparsed_comment()
    test_c5_no_carry_data()
    test_c6_wrong_token()
    test_c7_mult_tomorrow_carry_build()
    test_c8_mult_tomorrow_fallback()
    print("All summary and carry audit checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
