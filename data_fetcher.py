"""
data_fetcher.py — OANDA v20 API data fetcher with PostgreSQL persistence.
Credentials: DATABASE_URL, OANDA_ACCOUNT_ID, OANDA_API_TOKEN, OANDA_BASE_URL (.env / env).
No third-party quant libraries.
"""
import os
from dotenv import load_dotenv

load_dotenv()  # loads .env into os.environ; no-op if file absent
import logging
import threading
import time
from datetime import datetime, timezone, timedelta

import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from oandapyV20 import API
from oandapyV20.endpoints.instruments import InstrumentsCandles

log = logging.getLogger(__name__)

_client = None
_client_lock = threading.Lock()

_backfill_in_progress: set = set()
_backfill_lock = threading.Lock()

_fix_column_types_lock = threading.Lock()
_fix_column_types_done = False

# information_schema.data_type for legacy OHLC tables created with wrong types
_BAD_OPEN_PG_TYPES = frozenset({"text", "character varying", "character"})


# ── Instrument registry ───────────────────────────────────────────────────────
INSTRUMENTS = {
    "EUR/USD": {"symbol": "EUR_USD", "pip": 0.0001, "pip_name": "pips", "decimals": 5},
    "GBP/USD": {"symbol": "GBP_USD", "pip": 0.0001, "pip_name": "pips", "decimals": 5},
    "USD/JPY": {"symbol": "USD_JPY", "pip": 0.01,   "pip_name": "pips", "decimals": 3},
    "USD/CAD": {"symbol": "USD_CAD", "pip": 0.0001, "pip_name": "pips", "decimals": 5},
    "AUD/USD": {"symbol": "AUD_USD", "pip": 0.0001, "pip_name": "pips", "decimals": 5},
    "USD/CHF": {"symbol": "USD_CHF", "pip": 0.0001, "pip_name": "pips", "decimals": 5},
    "NZD/USD": {"symbol": "NZD_USD", "pip": 0.0001, "pip_name": "pips", "decimals": 5},
    "EUR/GBP": {"symbol": "EUR_GBP", "pip": 0.0001, "pip_name": "pips", "decimals": 5},
    "GBP/JPY": {"symbol": "GBP_JPY", "pip": 0.01,   "pip_name": "pips", "decimals": 3},
    "EUR/JPY": {"symbol": "EUR_JPY", "pip": 0.01,   "pip_name": "pips", "decimals": 3},
}

DEFAULT_INSTRUMENT = "EUR/USD"

GRANULARITY_MAP = {
    "5m":  "M5",
    "15m": "M15",
    "1h":  "H1",
}
DEFAULT_TIMEFRAME = "5m"

_INITIAL_BARS = {"5m": 5000, "15m": 2000, "1h": 2000}
_MINS_PER_BAR = {"5m": 5,    "15m": 15,   "1h": 60}
_MAX_PER_REQUEST = 500   # OANDA safe limit per call


def _get_client() -> API:
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            token    = os.environ.get("OANDA_API_TOKEN", "")
            base_url = os.environ.get("OANDA_BASE_URL", "https://api-fxpractice.oanda.com")
            environment = "practice" if "fxpractice" in base_url else "live"
            _client = API(access_token=token, environment=environment)
    return _client


# ── DB helpers (PostgreSQL) ───────────────────────────────────────────────────
def _table(instrument: str, timeframe: str) -> str:
    """ohlc_eur_usd_5m — slashes in instrument become underscores, lowercased."""
    left = instrument.replace("/", "_").lower()
    suffix = timeframe.replace("/", "").lower()
    return f"ohlc_{left}_{suffix}"


def _pg_connect(*, dict_rows: bool = False):
    """
    psycopg2 connection. Use dict_rows=True for app cursors (RealDictCursor).
    Use dict_rows=False for pandas read_sql — RealDictCursor breaks empty/small result handling.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        log.warning("DATABASE_URL not set — OHLC persistence disabled")
        return None
    try:
        if dict_rows:
            return psycopg2.connect(url, cursor_factory=RealDictCursor)
        return psycopg2.connect(url)
    except Exception:
        log.error("PostgreSQL connect failed", exc_info=True)
        return None


def get_conn():
    """Return a new psycopg2 connection (RealDictCursor), or None if unavailable."""
    return _pg_connect(dict_rows=True)


def _ohlc_table_columns_sql() -> str:
    return (
        '"time" TIMESTAMPTZ PRIMARY KEY,\n'
        '"open" DOUBLE PRECISION NOT NULL,\n'
        '"high" DOUBLE PRECISION NOT NULL,\n'
        '"low" DOUBLE PRECISION NOT NULL,\n'
        '"close" DOUBLE PRECISION NOT NULL,\n'
        '"volume" DOUBLE PRECISION NOT NULL'
    )


def _create_ohlc_ddl(tbl: str, *, if_not_exists: bool = False) -> str:
    prefix = "CREATE TABLE IF NOT EXISTS " if if_not_exists else "CREATE TABLE "
    return f"{prefix}{tbl} (\n{_ohlc_table_columns_sql()}\n)"


def _fix_column_types():
    """One-time startup migration: if ``open`` is text-like, drop and recreate that OHLC table."""
    global _fix_column_types_done
    with _fix_column_types_lock:
        if _fix_column_types_done:
            return
        conn = get_conn()
        if conn is None:
            return
        try:
            with conn.cursor() as cur:
                for inst in INSTRUMENTS:
                    for tf in GRANULARITY_MAP:
                        tbl = _table(inst, tf)
                        cur.execute(
                            """
                            SELECT data_type
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                              AND table_name = %s
                              AND column_name = 'open'
                            """,
                            (tbl,),
                        )
                        row = cur.fetchone()
                        if row is None:
                            continue
                        dt = row["data_type"]
                        if dt in _BAD_OPEN_PG_TYPES:
                            log.warning(
                                "OHLC table %s: column open has type %s — recreating with DOUBLE PRECISION",
                                tbl,
                                dt,
                            )
                            cur.execute(f"DROP TABLE IF EXISTS {tbl}")
                            cur.execute(_create_ohlc_ddl(tbl))
            conn.commit()
            _fix_column_types_done = True
        except Exception:
            conn.rollback()
            log.exception("_fix_column_types failed")
        finally:
            conn.close()


def _ensure_ohlc_tables():
    """Ensure each OHLC table exists with correct schema (runs type migration once, then CREATE IF NOT EXISTS)."""
    _fix_column_types()
    conn = get_conn()
    if conn is None:
        log.warning("_ensure_ohlc_tables: DB unavailable — skipping")
        return
    try:
        with conn.cursor() as cur:
            for inst in INSTRUMENTS:
                for tf in GRANULARITY_MAP:
                    tbl = _table(inst, tf)
                    cur.execute(_create_ohlc_ddl(tbl, if_not_exists=True))
        conn.commit()
    except Exception:
        conn.rollback()
        log.exception("_ensure_ohlc_tables failed")
    finally:
        conn.close()


def init_db():
    """Drop and recreate all OHLC tables (e.g. admin rebuild). Do not call on every request."""
    conn = get_conn()
    if conn is None:
        log.warning("init_db: DB unavailable — skipping table creation")
        return
    try:
        with conn.cursor() as cur:
            for inst in INSTRUMENTS:
                for tf in GRANULARITY_MAP:
                    tbl = _table(inst, tf)
                    cur.execute(f"DROP TABLE IF EXISTS {tbl}")
                    cur.execute(_create_ohlc_ddl(tbl))
        conn.commit()
    except Exception:
        conn.rollback()
        log.exception("init_db failed")
    finally:
        conn.close()


def _count_bars(instrument: str, timeframe: str) -> int:
    """Return row count in the OHLC table, or 0 if missing/unavailable."""
    conn = get_conn()
    if conn is None:
        return 0
    tbl = _table(instrument, timeframe)
    try:
        with conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) AS c FROM {tbl}')
            row = cur.fetchone()
        return int(row["c"]) if row and row["c"] is not None else 0
    except psycopg2.Error:
        return 0
    finally:
        conn.close()


def _earliest_ts(instrument: str, timeframe: str) -> datetime | None:
    """Oldest bar timestamp in the table, or None if empty / missing."""
    conn = get_conn()
    if conn is None:
        return None
    tbl = _table(instrument, timeframe)
    try:
        with conn.cursor() as cur:
            cur.execute(f'SELECT MIN("time") AS m FROM {tbl}')
            row = cur.fetchone()
        if row and row["m"] is not None:
            t = row["m"]
            if isinstance(t, datetime):
                return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
            return datetime.fromisoformat(str(t)).replace(tzinfo=timezone.utc)
    except psycopg2.Error:
        return None
    finally:
        conn.close()
    return None


def latest_ts(instrument: str, timeframe: str) -> datetime | None:
    tbl = _table(instrument, timeframe)
    conn = get_conn()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(f'SELECT MAX("time") AS m FROM {tbl}')
            row = cur.fetchone()
        if row and row["m"] is not None:
            t = row["m"]
            if isinstance(t, datetime):
                return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
            return datetime.fromisoformat(str(t)).replace(tzinfo=timezone.utc)
    except psycopg2.Error:
        return None
    finally:
        conn.close()
    return None


def _insert_bars(instrument: str, df: pd.DataFrame, timeframe: str):
    if df.empty:
        return
    tbl = _table(instrument, timeframe)
    idx = df.index
    if idx.tzinfo is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    vol_col = df["volume"].tolist() if "volume" in df.columns else [0.0] * len(df)
    rows = list(
        zip(
            list(idx),
            df["open"].tolist(),
            df["high"].tolist(),
            df["low"].tolist(),
            df["close"].tolist(),
            vol_col,
        )
    )
    conn = get_conn()
    if conn is None:
        log.warning("_insert_bars: DB unavailable — skipping insert for %s %s", instrument, timeframe)
        return
    try:
        with conn.cursor() as cur:
            execute_values(
                cur,
                f"""
                INSERT INTO {tbl} ("time", "open", "high", "low", "close", "volume") VALUES %s
                ON CONFLICT ("time") DO NOTHING
                """,
                rows,
                template="(%s, %s, %s, %s, %s, %s)",
            )
        conn.commit()
    except Exception:
        conn.rollback()
        log.exception("_insert_bars failed for %s %s", instrument, timeframe)
    finally:
        conn.close()


def _load_bars(instrument: str, days: int, timeframe: str) -> pd.DataFrame:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    # Plain connection (tuple rows). pd.read_sql + RealDictCursor can fabricate bogus rows
    # (e.g. column names as values) when the result set is empty.
    conn = _pg_connect(dict_rows=False)
    if conn is None:
        log.warning("_load_bars: DB unavailable — fetching from OANDA")
        meta = INSTRUMENTS.get(instrument)
        if meta is None:
            return pd.DataFrame()
        mins_bar = _MINS_PER_BAR.get(timeframe, 5)
        approx_bars = max(100, int((days * 24 * 60) / mins_bar) + 50)
        df = _fetch_oanda(
            meta["symbol"],
            GRANULARITY_MAP.get(timeframe, "M5"),
            approx_bars,
        )
        if df.empty:
            return df
        df = df.loc[df.index >= cutoff]
    else:
        tbl = _table(instrument, timeframe)
        _load_sql = f"""
            SELECT "time" AS ts,
                   "open" AS "open",
                   "high" AS "high",
                   "low" AS "low",
                   "close" AS "close",
                   "volume" AS "volume"
            FROM {tbl}
            WHERE "time" >= %s
            ORDER BY "time"
            """
        try:
            df = pd.read_sql(
                _load_sql,
                conn,
                params=(cutoff,),
                parse_dates=["ts"],
                index_col="ts",
            )
        finally:
            conn.close()
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    if df.empty:
        return df
    idx = pd.DatetimeIndex(df.index)
    df.index = idx.tz_convert("UTC") if idx.tzinfo else idx.tz_localize("UTC")
    return df


# ── OANDA fetch ───────────────────────────────────────────────────────────────
def _fetch_oanda(symbol: str, granularity: str, count: int,
                 from_ts: datetime | None = None,
                 to_before: datetime | None = None) -> pd.DataFrame:
    """
    Fetch up to `count` candles from OANDA. Paginates if count > _MAX_PER_REQUEST.
    Returns DataFrame with index=UTC datetime, columns=open/high/low/close/volume.

    - Default: most recent `count` candles (walk backward using `to`).
    - from_ts: forward from latest DB timestamp (incremental gap fill).
    - to_before: candles ending strictly before this time (historical top-up).
    """
    client = _get_client()
    account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
    all_frames = []
    remaining  = count

    # Backward pagination anchor: None = from “now”; else start before `to_before`
    to_dt: datetime | None = to_before

    while remaining > 0:
        batch = min(remaining, _MAX_PER_REQUEST)
        params: dict = {
            "granularity": granularity,
            "count":       batch,
            "price":       "M",    # midpoint candles
        }
        if from_ts is not None and not all_frames:
            # First incremental call: start from known timestamp
            params = {
                "granularity": granularity,
                "from":        from_ts.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
                "count":       batch,
                "price":       "M",
            }
        elif to_dt is not None:
            params["to"] = to_dt.strftime("%Y-%m-%dT%H:%M:%S.000000000Z")

        try:
            req = InstrumentsCandles(instrument=symbol, params=params)
            client.request(req)
            candles = req.response.get("candles", [])
        except Exception as e:
            log.error("OANDA fetch error for %s: %s", symbol, e)
            break

        if not candles:
            break

        rows = []
        for c in candles:
            if not c.get("complete", True):
                continue
            mid = c.get("mid", {})
            rows.append({
                "ts":     c["time"],
                "open":   float(mid.get("o", 0)),
                "high":   float(mid.get("h", 0)),
                "low":    float(mid.get("l", 0)),
                "close":  float(mid.get("c", 0)),
                "volume": float(c.get("volume", 0)),
            })

        if not rows:
            break

        frame = pd.DataFrame(rows)
        frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
        frame = frame.set_index("ts").sort_index()
        all_frames.append(frame)

        remaining -= len(frame)
        if len(frame) < batch:
            break

        # Next page: set `to` to the oldest timestamp in this batch for backward walk
        to_dt = frame.index[0]
        time.sleep(0.1)

    if not all_frames:
        return pd.DataFrame()

    combined = pd.concat(all_frames).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined


# ── Backfill logic ────────────────────────────────────────────────────────────
def _backfill_instrument(instrument: str, timeframe: str):
    key = (instrument, timeframe)
    with _backfill_lock:
        if key in _backfill_in_progress:
            return
        _backfill_in_progress.add(key)
    try:
        meta        = INSTRUMENTS[instrument]
        symbol      = meta["symbol"]
        granularity = GRANULARITY_MAP.get(timeframe, "M5")
        target      = _INITIAL_BARS.get(timeframe, 5000)
        bar_count   = _count_bars(instrument, timeframe)
        now         = datetime.now(timezone.utc)
        mins_bar    = _MINS_PER_BAR.get(timeframe, 5)

        if bar_count < target:
            if bar_count == 0:
                log.info("Initial backfill: %s @ %s", instrument, timeframe)
                df = _fetch_oanda(symbol, granularity, target)
                if not df.empty:
                    _insert_bars(instrument, df, timeframe)
                    log.info("%s @ %s: inserted %d bars", instrument, timeframe, len(df))
                return

            need = target - bar_count
            earliest = _earliest_ts(instrument, timeframe)
            if earliest is not None and need > 0:
                log.info(
                    "Top-up backfill: %s @ %s fetching %d older bars (have %d, target %d)",
                    instrument, timeframe, need, bar_count, target,
                )
                df = _fetch_oanda(symbol, granularity, need, to_before=earliest)
                if not df.empty:
                    _insert_bars(instrument, df, timeframe)
                    log.info("%s @ %s: top-up inserted %d bars", instrument, timeframe, len(df))

        since = latest_ts(instrument, timeframe)
        if since is None:
            return

        gap = (now - since).total_seconds() / 60
        if gap < mins_bar:
            return

        bars_needed = int(gap / mins_bar) + 10
        df = _fetch_oanda(symbol, granularity, bars_needed, from_ts=since)
        if not df.empty:
            new = df[df.index > since]
            _insert_bars(instrument, new, timeframe)
            log.info("%s @ %s: inserted %d new bars", instrument, timeframe, len(new))
    except Exception:
        log.exception("Backfill failed for %s @ %s", instrument, timeframe)
    finally:
        with _backfill_lock:
            _backfill_in_progress.discard(key)


def _backfill_all_worker():
    for inst in INSTRUMENTS:
        try:
            _backfill_instrument(inst, DEFAULT_TIMEFRAME)
        except Exception as e:
            log.warning("Backfill failed for %s: %s", inst, e)
        time.sleep(0.5)


def backfill_all():
    """Start background backfill for all instruments (called once at startup)."""
    _ensure_ohlc_tables()
    t = threading.Thread(target=_backfill_all_worker, daemon=True)
    t.start()
    log.info("Background backfill started")


def run_database_rebuild_async(timeframe: str = DEFAULT_TIMEFRAME) -> None:
    """
    Drop all OHLC tables, recreate schema, and backfill all instruments for the
    given timeframe (default 5m → _INITIAL_BARS e.g. 5000 bars each).
    Runs in a daemon thread so HTTP handlers can return immediately.
    """
    def worker():
        try:
            conn = get_conn()
            if conn is None:
                log.error("run_database_rebuild: no DATABASE_URL")
                return
            try:
                with conn.cursor() as cur:
                    for inst in INSTRUMENTS:
                        for tf in GRANULARITY_MAP:
                            tbl = _table(inst, tf)
                            cur.execute(f"DROP TABLE IF EXISTS {tbl}")
                conn.commit()
                log.info("Dropped all OHLC tables")
            except Exception:
                conn.rollback()
                log.exception("run_database_rebuild: drop tables failed")
            finally:
                conn.close()

            init_db()
            for inst in INSTRUMENTS:
                try:
                    _backfill_instrument(inst, timeframe)
                except Exception:
                    log.exception("Rebuild backfill failed for %s @ %s", inst, timeframe)
                time.sleep(0.2)
            log.info("Database rebuild + backfill finished for timeframe=%s", timeframe)
        except Exception:
            log.exception("Database rebuild worker failed")

    threading.Thread(target=worker, daemon=True, name="db-rebuild").start()


def get_ohlc(instrument: str = DEFAULT_INSTRUMENT, days: int = 180,
             timeframe: str = DEFAULT_TIMEFRAME) -> pd.DataFrame:
    """
    Public API: return OHLC DataFrame for the instrument/timeframe.
    Triggers _backfill_instrument: tops up toward _INITIAL_BARS[timeframe] if the
    table is short, then fills gaps when the latest bar is stale.
    """
    _ensure_ohlc_tables()
    _backfill_instrument(instrument, timeframe)
    return _load_bars(instrument, days=days, timeframe=timeframe)
