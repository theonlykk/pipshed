"""
PipShed — Flask app: regime filters + ICT-style signal tree, chart PNG + equity.
"""
from __future__ import annotations

import base64
import json as _json
import logging
import os
import re
import hashlib
import subprocess
from typing import NamedTuple

import numpy as np
import pandas as pd
from flask import Flask, jsonify, make_response, render_template, request

from data_fetcher import (
    DEFAULT_INSTRUMENT,
    DEFAULT_TIMEFRAME,
    INSTRUMENTS,
    backfill_all,
    run_database_rebuild_async,
    get_ohlc,
)
from indicators import apply_indicators, generate_indicator_signals
from patterns import PATTERN_REGISTRY, apply_patterns
from chart_renderer import render_chart, render_equity_chart
from window_scorer import (
    get_next_window,
    get_prev_window,
    get_shifted_window,
    get_window,
)
from cache import (
    cache_delete,
    cache_get,
    cache_has,
    cache_set,
    cache_key,
    flush_chart_cache_keys,
    get_redis,
)
import cache as _cache_backend

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

TP_ATR_MULT = 3.0
SL_ATR_MULT = 1.0
MAX_HOLD_BARS = 22
SIGNALS_RECENT_DAYS = 30
DEFAULT_LOOKBACK_DAYS = 180
CHART_CACHE_TTL_SEC = 120
IMAGE_CACHE_TTL_SEC = 300
DEFAULT_NOTIONAL_USD = 1000
_MIN_NOTIONAL_USD = 100
_MAX_NOTIONAL_USD = 1_000_000
SLIPPAGE = 0.0005

_VALID_FILTERS = {
    "bb", "rsi", "macd", "ema", "bb_width", "volume_spike",
    "ema9", "ema20", "ema50", "ema200",
    "sma10", "sma20", "sma50", "sma200",
    "stochastic", "cci", "williams_r", "atr_ind",
    "keltner", "donchian", "hist_vol", "squeeze",
}
_VALID_TIMEFRAMES = {"5m", "15m", "1h"}
_VALID_WINDOW_SIZES = {20, 30, 50, 75, 100}
_ALL_PATTERNS = set(PATTERN_REGISTRY.keys())

_LIT_PLACEHOLDER_KEYS = frozenset({"sweep", "fvg", "bos", "order_block", "smt"})

_REVERSAL_PATTERNS = [
    "shooting_star", "hammer", "hanging_man", "inverted_hammer",
    "engulfing", "morning_star", "evening_star", "piercing_dark_cloud",
]
_CONTINUATION_PATTERNS = ["three_soldiers_crows"]
_INDECISION_PATTERNS = ["doji", "harami"]

_UI_PILL_EXPAND: dict[str, list[str]] = {
    "ema_cross_9_20": ["ema9", "ema20"],
    "ema_cross_9_50": ["ema9", "ema50"],
    "ema_cross_50_200": ["ema50", "ema200"],
    "macd_cross": ["macd"],
    "macd_zero": ["macd"],
    "bb_squeeze": ["squeeze"],
    "atr_filter": ["atr_ind"],
    "reversal": list(_REVERSAL_PATTERNS),
    "continuation": list(_CONTINUATION_PATTERNS),
    "indecision": list(_INDECISION_PATTERNS),
}

_TRANSPARENT_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAwUBAIeisYoAAAAASUVORK5CYII="
)


def _get_asset_version(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:12]
    except Exception:
        return "v1"


CORE_JS_VERSION = _get_asset_version(os.path.join(os.path.dirname(__file__), "static", "core.js"))


def _get_git_commit() -> str:
    env_val = os.environ.get("GIT_COMMIT", "").strip()
    if env_val:
        return env_val
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            cwd=os.path.dirname(__file__),
        ).decode().strip()
    except Exception:
        return "dev"


GIT_COMMIT = _get_git_commit()


def _admin_authorized() -> bool:
    expected = os.environ.get("ADMIN_TOKEN", "pipShed2026").strip()
    if not expected:
        return False
    return request.headers.get("X-Admin-Token", "").strip() == expected


def _expand_pill_key(key: str) -> list[str]:
    if not key or not isinstance(key, str):
        return []
    k = key.strip()
    if k in _UI_PILL_EXPAND:
        out: list[str] = []
        for x in _UI_PILL_EXPAND[k]:
            out.extend(_expand_pill_key(x))
        return out
    if k in _VALID_FILTERS or k in _ALL_PATTERNS or k in _LIT_PLACEHOLDER_KEYS:
        return [k]
    if k.startswith("kz_"):
        return []
    return []


def _expand_key_list(keys: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        for e in _expand_pill_key(k):
            if e not in seen:
                seen.add(e)
                out.append(e)
    return out


def _coerce_indicator_list(raw, valid: set) -> list:
    if raw is None:
        return []
    items: list[str] = []
    if isinstance(raw, str):
        items = [x.strip() for x in raw.split(",") if x.strip()]
    elif isinstance(raw, (list, tuple)):
        for el in raw:
            if not isinstance(el, str):
                continue
            el = el.strip()
            if not el:
                continue
            if "," in el:
                items.extend(x.strip() for x in el.split(",") if x.strip())
            else:
                items.append(el)
    else:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in valid or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _coerce_regime_or_signal_pills(raw) -> list[str]:
    """Accept UI pill keys: known filters, patterns, crosses, LIT, sessions (kz_), etc."""
    if raw is None:
        return []
    items: list[str] = []
    if isinstance(raw, str):
        items = [x.strip() for x in raw.split(",") if x.strip()]
    elif isinstance(raw, (list, tuple)):
        for el in raw:
            if not isinstance(el, str):
                continue
            el = el.strip()
            if not el:
                continue
            if "," in el:
                items.extend(x.strip() for x in el.split(",") if x.strip())
            else:
                items.append(el)
    else:
        return []
    known_ui = (
        _VALID_FILTERS
        | _ALL_PATTERNS
        | _LIT_PLACEHOLDER_KEYS
        | frozenset(_UI_PILL_EXPAND.keys())
    )
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x in seen:
            continue
        if x.startswith("kz_") or x in known_ui or bool(_expand_pill_key(x)):
            seen.add(x)
            out.append(x)
    return out


def _parse_notional(data: dict) -> int:
    raw = data.get("notional", DEFAULT_NOTIONAL_USD)
    try:
        v = float(raw) if raw is not None else float(DEFAULT_NOTIONAL_USD)
    except (TypeError, ValueError):
        v = float(DEFAULT_NOTIONAL_USD)
    v = int(round(v))
    return max(_MIN_NOTIONAL_USD, min(_MAX_NOTIONAL_USD, v))


def _merge_indicator_lists(
    filters: list,
    b1: list,
    b2: list,
    b3: list,
    tree: dict | None = None,
) -> list:
    """Stable de-dupe: filters, boxes, then pills from signal tree nodes."""
    seen: set[str] = set()
    out: list[str] = []
    all_pills: list[str] = list(filters) + list(b1) + list(b2) + list(b3)
    if tree:
        nodes = tree.get("nodes")
        if isinstance(nodes, dict):
            for node in nodes.values():
                if not isinstance(node, dict):
                    continue
                pl = node.get("pills", [])
                if isinstance(pl, list):
                    for k in pl:
                        if isinstance(k, str) and k:
                            all_pills.append(k)
    for k in all_pills:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _parse_request(data: dict) -> tuple:
    instrument = data.get("instrument", DEFAULT_INSTRUMENT)
    if instrument not in INSTRUMENTS:
        instrument = DEFAULT_INSTRUMENT
    timeframe = data.get("timeframe", DEFAULT_TIMEFRAME)
    if timeframe not in _VALID_TIMEFRAMES:
        timeframe = DEFAULT_TIMEFRAME
    regime = _coerce_regime_or_signal_pills(data.get("regime", []))
    window_size = int(data.get("window_size", 50))
    if window_size not in _VALID_WINDOW_SIZES:
        window_size = 50
    show_volume = bool(data.get("show_volume", False))
    notional = _parse_notional(data)
    raw_tree = data.get("signal_tree", data.get("tree", {}))
    tree = raw_tree if isinstance(raw_tree, dict) and raw_tree.get("nodes") else {}
    return (
        instrument,
        timeframe,
        regime,
        window_size,
        show_volume,
        notional,
        tree,
    )


def _equity_dollar_per_pip(instrument: str, notional: float, last_close: float) -> float:
    if "JPY" in instrument.upper().replace("/", ""):
        rate = last_close if last_close > 1e-12 else 150.0
        return float(notional) * 0.01 / rate
    return float(notional) * 0.0001


def compute_atr_wilder(
    high: np.ndarray | pd.Series,
    low: np.ndarray | pd.Series,
    close: np.ndarray | pd.Series,
    period: int = 14,
) -> np.ndarray:
    """
    Wilder ATR — same TR + RMA recipe as indicators.atr (logic duplicated here).
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    n = len(high)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = hl if hl >= hc and hl >= lc else (hc if hc >= lc else lc)
    seed = 0.0
    for i in range(period):
        seed += tr[i]
    seed /= period
    out[period - 1] = seed
    prev = seed
    for i in range(period, n):
        v = (prev * (period - 1) + tr[i]) / period
        out[i] = v
        prev = v
    return out


def h1_atr_aligned_to_df(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Resample to H1 OHLC, Wilder ATR(period) on H1, forward-fill to df.index.
    """
    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return pd.Series(np.nan, index=df.index, dtype=float)
    o = df["open"].resample("1h", label="left", closed="left").first()
    h = df["high"].resample("1h", label="left", closed="left").max()
    lo = df["low"].resample("1h", label="left", closed="left").min()
    c = df["close"].resample("1h", label="left", closed="left").last()
    h1 = pd.concat([o, h, lo, c], axis=1)
    h1.columns = ["open", "high", "low", "close"]
    h1 = h1.dropna(how="all")
    if len(h1) < period + 1:
        return pd.Series(np.nan, index=df.index, dtype=float)
    atr_h1 = compute_atr_wilder(h1["high"], h1["low"], h1["close"], period)
    s = pd.Series(atr_h1, index=h1.index)
    combined = s.reindex(s.index.union(df.index)).sort_index().ffill()
    return combined.reindex(df.index)


def _evaluate_tree_at_bar(
    tree: dict,
    df: pd.DataFrame,
    bar_idx: int,
    signals_np: np.ndarray,
    pill_arrays: dict[str, np.ndarray],
) -> bool:
    direction = int(signals_np[bar_idx])
    if direction == 0:
        return False
    nodes = tree.get("nodes")
    roots = tree.get("roots")
    if not isinstance(nodes, dict) or not isinstance(roots, list):
        return False
    root_ids: set[str] = set()
    for r in roots:
        if isinstance(r, str) and r:
            root_ids.add(r)
    n_df: int = len(df.index)
    n_sig: int = len(signals_np)
    n_bars: int = n_df if n_df < n_sig else n_sig

    def node_fires_at(node_id: str, search_from: int, search_to: int) -> int | None:
        node = nodes.get(node_id)
        if not isinstance(node, dict):
            return None
        pills_raw = node.get("pills", [])
        pills: list[str] = []
        if isinstance(pills_raw, list):
            for p in pills_raw:
                if isinstance(p, str) and p:
                    pills.append(p)
        if not pills:
            if search_from <= bar_idx:
                return search_from
            return None
        for p in pills:
            if p not in pill_arrays:
                return None
        lim = search_to + 1
        if lim > bar_idx + 1:
            lim = bar_idx + 1
        i = search_from
        while i < lim:
            if i < 0:
                i += 1
                continue
            if i >= n_bars + 1:
                break
            ok = True
            for p in pills:
                if int(pill_arrays[p][i]) != direction:
                    ok = False
                    break
            if ok:
                return i
            i += 1
        return None

    def path_fires(node_id: str, search_from: int) -> bool:
        node = nodes.get(node_id)
        if not isinstance(node, dict):
            return False
        w_raw = node.get("window")
        window = 0
        if isinstance(w_raw, int) and w_raw > 0:
            window = w_raw
        elif isinstance(w_raw, float) and w_raw > 0.0 and w_raw == int(w_raw):
            window = int(w_raw)
        rel = node.get("relationship")
        if rel is None or node_id in root_ids:
            search_to = bar_idx
        elif window:
            search_to = search_from + window
        else:
            search_to = bar_idx
        fired_at = node_fires_at(node_id, search_from, search_to)
        if fired_at is None:
            return False
        ch = node.get("children", [])
        children: list[str] = []
        if isinstance(ch, list):
            for c in ch:
                if isinstance(c, str) and c:
                    children.append(c)
        if not children:
            return True
        for cid in children:
            if path_fires(cid, fired_at):
                return True
        return False

    for rid in roots:
        if not isinstance(rid, str):
            continue
        if path_fires(rid, 0):
            return True
    return False


def _compute_stats(df: pd.DataFrame, active_patterns: list, instrument: str) -> dict:
    """Forward-bar backtest: TP/SL from TP_ATR_MULT / SL_ATR_MULT, MAX_HOLD_BARS."""
    empty = {
        "total_signals": 0,
        "win_rate": 0.0,
        "signals_30d": 0,
        "expectancy": 0.0,
        "avg_pip_pnl": 0.0,
    }
    if "atr" not in df.columns or "signal" not in df.columns:
        return empty

    n = len(df)
    atrs = df["atr"].to_numpy(dtype=float)
    opens = df["open"].to_numpy(dtype=float)
    atr_h1_full = h1_atr_aligned_to_df(df).to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    signals = df["signal"].to_numpy(dtype=np.int8)

    wins = 0
    total = 0
    pnl_sum_pips = 0.0
    now_cutoff = df.index[-1] - pd.Timedelta(days=SIGNALS_RECENT_DAYS) if len(df) > 0 else df.index[-1]
    signals_30d = 0
    pip = float(INSTRUMENTS[instrument]["pip"])

    for i in range(n - 1):
        sig = int(signals[i])
        if sig == 0:
            continue
        atr_tf = atrs[i]
        if np.isnan(atr_tf) or atr_tf == 0.0:
            continue
        ah = atr_h1_full[i]
        sl_tp_atr = float(ah) if np.isfinite(ah) and ah != 0.0 else float(atr_tf)
        base_open = float(opens[i + 1])
        entry = base_open + SLIPPAGE if sig == 1 else base_open - SLIPPAGE
        tp = entry + sig * TP_ATR_MULT * sl_tp_atr
        sl = entry - sig * SL_ATR_MULT * sl_tp_atr
        total += 1
        if df.index[i] >= now_cutoff:
            signals_30d += 1
        outcome_pips = 0.0
        hit = False
        for j in range(i + 2, min(i + MAX_HOLD_BARS, n)):
            if sig == 1:
                if highs[j] >= tp:
                    wins += 1
                    outcome_pips = TP_ATR_MULT * sl_tp_atr / pip
                    hit = True
                    break
                if lows[j] <= sl:
                    outcome_pips = -SL_ATR_MULT * sl_tp_atr / pip
                    hit = True
                    break
            else:
                if lows[j] <= tp:
                    wins += 1
                    outcome_pips = TP_ATR_MULT * sl_tp_atr / pip
                    hit = True
                    break
                if highs[j] >= sl:
                    outcome_pips = -SL_ATR_MULT * sl_tp_atr / pip
                    hit = True
                    break
        if hit:
            pnl_sum_pips += outcome_pips

    win_rate = wins / total if total > 0 else 0.0
    expectancy = win_rate * TP_ATR_MULT - (1.0 - win_rate) * SL_ATR_MULT
    avg_pip_pnl = pnl_sum_pips / total if total > 0 else 0.0

    return {
        "total_signals": total,
        "win_rate": round(win_rate, 3),
        "signals_30d": signals_30d,
        "expectancy": round(expectancy, 3),
        "avg_pip_pnl": round(avg_pip_pnl, 2),
    }


def _apply_lit_placeholders(df: pd.DataFrame, lit_keys: list[str]) -> None:
    for k in lit_keys:
        col = "pat_%s" % k
        if col not in df.columns:
            df[col] = np.zeros(len(df), dtype=np.int8)


def _signal_array_for_raw_pill(df: pd.DataFrame, raw_key: str) -> np.ndarray | None:
    """Per-bar directional signal (+1/-1/0) for a tree/regime UI pill key."""
    if raw_key in _LIT_PLACEHOLDER_KEYS or (isinstance(raw_key, str) and raw_key.startswith("kz_")):
        return np.zeros(len(df), dtype=np.int8)
    if raw_key in _ALL_PATTERNS:
        col = "pat_%s" % raw_key
        if col in df.columns:
            return df[col].to_numpy(dtype=np.int8)
        return None
    if raw_key in ("reversal", "continuation", "indecision"):
        pats = [p for p in _expand_pill_key(raw_key) if p in _ALL_PATTERNS]
        arrs = []
        for p in pats:
            c = "pat_%s" % p
            if c in df.columns:
                arrs.append(df[c].to_numpy(dtype=np.int8))
        if not arrs:
            return None
        stacked = np.stack(arrs, axis=0)
        s = np.sum(stacked, axis=0, dtype=np.int32)
        out = np.zeros(len(df), dtype=np.int8)
        out[s > 0] = 1
        out[s < 0] = -1
        return out
    if raw_key in _UI_PILL_EXPAND:
        inner = [x for x in _expand_pill_key(raw_key) if x in _VALID_FILTERS]
        if inner:
            return generate_indicator_signals(df, inner).to_numpy(dtype=np.int8)
        return None
    if raw_key in _VALID_FILTERS:
        col = "signal_%s" % raw_key
        if col in df.columns:
            return df[col].to_numpy(dtype=np.int8)
        return generate_indicator_signals(df, [raw_key]).to_numpy(dtype=np.int8)
    return None


def _compute_equity_curve(
    df: pd.DataFrame,
    active_patterns: list,
    instrument: str,
    notional: float = DEFAULT_NOTIONAL_USD,
    *,
    active_filters: list | None = None,
    regime_keys: list | None = None,
    tree: dict | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    empty = (np.array([]), np.array([]), np.array([]))
    reg = list(regime_keys or [])
    tr = tree if isinstance(tree, dict) else {}
    use_tree = bool(tr.get("nodes"))
    if "atr" not in df.columns:
        return empty
    if "signal" not in df.columns:
        return empty

    n = len(df)
    pip = INSTRUMENTS[instrument]["pip"]
    closes = df["close"].to_numpy(dtype=float)
    atrs = df["atr"].to_numpy(dtype=float)
    opens = df["open"].to_numpy(dtype=float)
    atr_h1_full = h1_atr_aligned_to_df(df).to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    signals = df["signal"].to_numpy(dtype=np.int8, copy=True)
    last_close = float(closes[-1]) if n else 1.0
    usd_per_pip = _equity_dollar_per_pip(instrument, notional, last_close)

    if use_tree:
        nodes = tr.get("nodes")
        pill_seen: set[str] = set()
        tree_pills: list[str] = []
        if isinstance(nodes, dict):
            for node in nodes.values():
                if not isinstance(node, dict):
                    continue
                pl = node.get("pills", [])
                if not isinstance(pl, list):
                    continue
                for pill in pl:
                    if not isinstance(pill, str) or not pill or pill in pill_seen:
                        continue
                    pill_seen.add(pill)
                    tree_pills.append(pill)
        pill_arrays: dict[str, np.ndarray] = {}
        for pill in tree_pills:
            arr = _signal_array_for_raw_pill(df, pill)
            if arr is not None:
                pill_arrays[pill] = arr
        for i in range(n):
            if signals[i] == 0:
                continue
            if not _evaluate_tree_at_bar(tr, df, i, signals, pill_arrays):
                signals[i] = 0
        if reg:
            for i in range(n):
                s = int(signals[i])
                if s == 0:
                    continue
                ok = True
                for rk in reg:
                    if isinstance(rk, str) and rk.startswith("kz_"):
                        continue
                    arr = _signal_array_for_raw_pill(df, rk)
                    if arr is None:
                        ok = False
                        break
                    if int(arr[i]) != s:
                        ok = False
                        break
                if not ok:
                    signals[i] = 0
    elif reg:
        for i in range(n):
            s = int(signals[i])
            if s == 0:
                continue
            ok = True
            for rk in reg:
                if isinstance(rk, str) and rk.startswith("kz_"):
                    continue
                arr = _signal_array_for_raw_pill(df, rk)
                if arr is None:
                    ok = False
                    break
                if int(arr[i]) != s:
                    ok = False
                    break
            if not ok:
                signals[i] = 0

    if not np.any(signals != 0):
        if active_patterns or (active_filters and len(active_filters) > 0) or reg or use_tree:
            x = np.arange(n)
            z = np.zeros(n, dtype=float)
            return x, z, z
        return empty

    pnl = np.zeros(n)
    for i in range(n - 1):
        sig = int(signals[i])
        if sig == 0:
            continue
        atr_tf = atrs[i]
        if np.isnan(atr_tf) or atr_tf == 0.0:
            continue
        ah = atr_h1_full[i]
        sl_tp_atr = float(ah) if np.isfinite(ah) and ah != 0.0 else float(atr_tf)
        base_open = float(opens[i + 1])
        entry = base_open + SLIPPAGE if sig == 1 else base_open - SLIPPAGE
        tp = entry + sig * TP_ATR_MULT * sl_tp_atr
        sl = entry - sig * SL_ATR_MULT * sl_tp_atr
        for j in range(i + 2, min(i + MAX_HOLD_BARS, n)):
            if sig == 1:
                if highs[j] >= tp:
                    pnl[i] = TP_ATR_MULT * sl_tp_atr / pip
                    break
                if lows[j] <= sl:
                    pnl[i] = -SL_ATR_MULT * sl_tp_atr / pip
                    break
            else:
                if lows[j] <= tp:
                    pnl[i] = TP_ATR_MULT * sl_tp_atr / pip
                    break
                if highs[j] >= sl:
                    pnl[i] = -SL_ATR_MULT * sl_tp_atr / pip
                    break

    x = np.arange(n)
    cum_pips = np.cumsum(pnl)
    cum_usd = cum_pips * usd_per_pip
    return x, cum_pips, cum_usd


def _tree_cache_segment(tree: dict) -> str:
    if not tree or not tree.get("nodes"):
        return "-"
    js = _json.dumps(tree, sort_keys=True, separators=(",", ":"))
    b = base64.urlsafe_b64encode(js.encode("utf-8")).decode("ascii")
    return b.rstrip("=")


class _ParsedChartKey(NamedTuple):
    instrument: str
    timeframe: str
    filters: list
    patterns: list
    window_size: int
    show_volume: bool
    kind: str
    window_index: int
    current_start: int
    current_end: int
    shift_direction: str
    notional: int
    box1: list
    box2: list
    box3: list
    tree: dict


def _decode_tree_cache_suffix(seg: str) -> dict | None:
    if seg == "-":
        return {}
    try:
        pad_len = (4 - len(seg) % 4) % 4
        raw = base64.urlsafe_b64decode(seg + ("=" * pad_len))
        obj = _json.loads(raw.decode("utf-8"))
        if not isinstance(obj, dict):
            return None
        return obj
    except Exception:
        return None


def _split_trailing_tree(parts: list[str]) -> tuple[list[str], dict]:
    if not parts:
        return parts, {}
    last = parts[-1]
    if last.isdigit():
        return parts, {}
    td = _decode_tree_cache_suffix(last)
    if td is None:
        return parts, {}
    return parts[:-1], td


def _parse_cache_key(ck: str) -> _ParsedChartKey | None:
    if ck.startswith("chart:"):
        kind = "chart"
        rest = ck[6:]
    elif ck.startswith("next_window:"):
        kind = "next_window"
        rest = ck[len("next_window:") :]
    elif ck.startswith("prev_window:"):
        kind = "prev_window"
        rest = ck[len("prev_window:") :]
    elif ck.startswith("shift_window:"):
        kind = "shift_window"
        rest = ck[len("shift_window:") :]
    else:
        return None

    instrument = None
    for inst in sorted(INSTRUMENTS.keys(), key=len, reverse=True):
        if rest.startswith(inst + ":"):
            instrument = inst
            rest2 = rest[len(inst) + 1 :]
            break
    if instrument is None:
        return None

    parts = rest2.split(":")
    parts, key_tree = _split_trailing_tree(parts)
    notional_i = 1000
    box1_k: list = []
    box2_k: list = []
    box3_k: list = []

    def _box_lists_from_key(b1s: str, b2s: str, b3s: str) -> tuple[list, list, list]:
        def one(seg: str) -> list:
            if not seg:
                return []
            return [x for x in seg.split(",") if x]

        return one(b1s), one(b2s), one(b3s)

    if kind == "chart":
        if len(parts) in (9, 10):
            try:
                window_size = int(parts[6])
                window_index = int(parts[7])
                vol_flag = int(parts[8])
                if len(parts) == 10:
                    notional_i = int(parts[9])
            except ValueError:
                return None
            timeframe, f_csv, p_csv = parts[0], parts[1], parts[2]
            box1_k, box2_k, box3_k = _box_lists_from_key(parts[3], parts[4], parts[5])
            current_start = current_end = 0
            shift_direction = ""
        elif len(parts) in (6, 7):
            try:
                window_size = int(parts[3])
                window_index = int(parts[4])
                vol_flag = int(parts[5])
                if len(parts) == 7:
                    notional_i = int(parts[6])
            except ValueError:
                return None
            timeframe, f_csv, p_csv = parts[0], parts[1], parts[2]
            current_start = current_end = 0
            shift_direction = ""
        else:
            return None
    elif kind in ("next_window", "prev_window"):
        if len(parts) in (10, 11):
            try:
                window_size = int(parts[6])
                current_start = int(parts[7])
                current_end = int(parts[8])
                vol_flag = int(parts[9])
                if len(parts) == 11:
                    notional_i = int(parts[10])
            except ValueError:
                return None
            timeframe, f_csv, p_csv = parts[0], parts[1], parts[2]
            box1_k, box2_k, box3_k = _box_lists_from_key(parts[3], parts[4], parts[5])
            window_index = 0
            shift_direction = ""
        elif len(parts) in (7, 8):
            try:
                window_size = int(parts[3])
                current_start = int(parts[4])
                current_end = int(parts[5])
                vol_flag = int(parts[6])
                if len(parts) == 8:
                    notional_i = int(parts[7])
            except ValueError:
                return None
            timeframe, f_csv, p_csv = parts[0], parts[1], parts[2]
            window_index = 0
            shift_direction = ""
        else:
            return None
    elif kind == "shift_window":
        if len(parts) in (11, 12):
            try:
                window_size = int(parts[6])
                shift_direction = str(parts[7])
                current_start = int(parts[8])
                current_end = int(parts[9])
                vol_flag = int(parts[10])
                if len(parts) == 12:
                    notional_i = int(parts[11])
            except ValueError:
                return None
            if shift_direction not in ("left", "right"):
                return None
            timeframe, f_csv, p_csv = parts[0], parts[1], parts[2]
            box1_k, box2_k, box3_k = _box_lists_from_key(parts[3], parts[4], parts[5])
            window_index = 0
        elif len(parts) in (8, 9):
            try:
                window_size = int(parts[3])
                shift_direction = str(parts[4])
                current_start = int(parts[5])
                current_end = int(parts[6])
                vol_flag = int(parts[7])
                if len(parts) == 9:
                    notional_i = int(parts[8])
            except ValueError:
                return None
            if shift_direction not in ("left", "right"):
                return None
            timeframe, f_csv, p_csv = parts[0], parts[1], parts[2]
            window_index = 0
        else:
            return None

    if timeframe not in _VALID_TIMEFRAMES or window_size not in _VALID_WINDOW_SIZES:
        return None
    if vol_flag not in (0, 1):
        return None

    filters = [f for f in f_csv.split(",") if f in _VALID_FILTERS]
    patterns = [p for p in p_csv.split(",") if p in _ALL_PATTERNS]

    return _ParsedChartKey(
        instrument,
        timeframe,
        filters,
        patterns,
        window_size,
        bool(vol_flag),
        kind,
        window_index,
        current_start,
        current_end,
        shift_direction,
        max(100, min(1_000_000, notional_i)),
        box1_k,
        box2_k,
        box3_k,
        key_tree,
    )


def _build_chart_response(window: dict, stats: dict, meta: dict,
                          instrument: str, timeframe: str) -> dict:
    return {
        "window_info": {
            "current": window["current"],
            "total": window["total"],
            "score": window["score"],
            "description": window.get("description", ""),
        },
        "current_start": window["start"],
        "current_end": window["end"],
        "stats": stats,
        "instrument": instrument,
        "timeframe": timeframe,
        "pip_name": meta["pip_name"],
        "decimals": meta["decimals"],
    }


def _stale_chart_cache_missing_indicator_equity(
    cached: dict, filters: list, patterns: list
) -> bool:
    if not isinstance(cached, dict) or not filters or patterns:
        return False
    if cached.get("equity_cache_key"):
        return False
    if cached.get("equity_image_base64"):
        return False
    return True


def _cache_chart_payload_images(
    ck: str,
    image_b64: str,
    candle_map: dict,
    equity_image_b64: str | None,
    payload: dict,
) -> None:
    cache_set(f"chart_img:{ck}", image_b64, ex=IMAGE_CACHE_TTL_SEC)
    cache_set(f"candle_map:{ck}", candle_map, ex=IMAGE_CACHE_TTL_SEC)
    if equity_image_b64 is not None:
        cache_set(f"equity_img:{ck}", equity_image_b64, ex=IMAGE_CACHE_TTL_SEC)
        payload["equity_cache_key"] = ck
    else:
        payload["equity_cache_key"] = None
    if get_redis() is None:
        payload["image_base64"] = image_b64
        if equity_image_b64 is not None:
            payload["equity_image_base64"] = equity_image_b64


def _normalize_cached_chart_payload(cached: dict, request_ck: str) -> dict:
    if not isinstance(cached, dict):
        return cached
    img_ck = cached.get("cache_key") or request_ck
    has_eq_img = bool(img_ck and cache_has(f"equity_img:{img_ck}"))
    if "equity_cache_key" not in cached:
        out = dict(cached)
        out["equity_cache_key"] = img_ck if has_eq_img else None
        return out
    if cached.get("equity_cache_key") is None and has_eq_img:
        out = dict(cached)
        out["equity_cache_key"] = img_ck
        return out
    return cached


class _NoDataError(Exception):
    pass


def _run_chart_pipeline(
    instrument: str,
    timeframe: str,
    regime: list,
    window_size: int,
    show_volume: bool,
    window_selector_fn,
    notional: float = DEFAULT_NOTIONAL_USD,
    tree: dict | None = None,
) -> tuple:
    df = get_ohlc(instrument, days=DEFAULT_LOOKBACK_DAYS, timeframe=timeframe)
    if df.empty:
        raise _NoDataError()
    tr = tree if isinstance(tree, dict) else {}
    raw_merged = _merge_indicator_lists([], regime, [], [], tr)
    expanded = _expand_key_list(raw_merged)
    filters_for_apply = [x for x in expanded if x in _VALID_FILTERS]
    patterns_from_pills = [x for x in expanded if x in _ALL_PATTERNS]
    lit_keys = [x for x in expanded if x in _LIT_PLACEHOLDER_KEYS]
    patterns_union = list(dict.fromkeys(patterns_from_pills))

    filters: list[str] = []
    if tr.get("nodes") and tr.get("roots"):
        root_pills: list[str] = []
        nodes = tr["nodes"]
        roots = tr["roots"]
        if isinstance(nodes, dict) and isinstance(roots, list):
            for root_id in roots:
                node = nodes.get(root_id, {})
                if isinstance(node, dict):
                    pl = node.get("pills", [])
                    if isinstance(pl, list):
                        root_pills.extend(p for p in pl if isinstance(p, str) and p)
        if root_pills:
            exp_root = _expand_key_list(root_pills)
            filters = [x for x in exp_root if x in _VALID_FILTERS]
    if not filters:
        filters = list(dict.fromkeys([x for x in filters_for_apply if x in _VALID_FILTERS]))

    df = apply_indicators(df.copy(), list(dict.fromkeys(filters_for_apply)))
    df = apply_patterns(df, patterns_union)
    _apply_lit_placeholders(df, lit_keys)

    if patterns_union and filters:
        ind_sig = generate_indicator_signals(df, filters).to_numpy(dtype=np.int8)
        pat_sig = df["signal"].to_numpy(dtype=np.int8)
        df["signal"] = np.where(
            (pat_sig != 0) & (ind_sig == pat_sig), pat_sig, 0
        ).astype(np.int8)
    elif filters and not patterns_union:
        df["signal"] = generate_indicator_signals(df, filters).astype(np.int8)
    elif not filters and patterns_union:
        pass
    else:
        df["signal"] = np.zeros(len(df), dtype=np.int8)

    all_filters = filters + patterns_union
    window = window_selector_fn(df, all_filters)
    window_df = df.iloc[window["start"] : window["end"]]
    eq_x, eq_pips, eq_usd = _compute_equity_curve(
        df,
        patterns_union,
        instrument,
        notional,
        active_filters=filters,
        regime_keys=regime,
        tree=tr,
    )
    _pip = float(INSTRUMENTS[instrument]["pip"])
    _sig_w = window_df["signal"].to_numpy(dtype=np.int8)
    _sig_full = df["signal"].to_numpy(dtype=np.int8)
    image_b64, candle_map = render_chart(
        window_df,
        filters,
        patterns_union,
        window_start=window["start"],
        window_end=window["end"],
        full_len=len(df),
        show_volume=show_volume,
        signals=_sig_w,
        pip=_pip,
    )
    equity_image_b64 = None
    if len(eq_x) > 0:
        equity_image_b64 = render_equity_chart(
            full_df=df,
            equity_x=eq_x,
            equity_y_pips=eq_pips,
            equity_y_usd=eq_usd,
            full_index=df.index,
            window_start=window["start"],
            window_end=window["end"],
            notional=float(notional),
            instrument=instrument,
            signals=_sig_full,
        )
    stats = _compute_stats(df, patterns_union, instrument)
    return window, image_b64, candle_map, stats, equity_image_b64


app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


@app.after_request
def add_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Admin-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=31536000"
    return response


@app.route("/", methods=["OPTIONS"])
@app.route("/chart", methods=["OPTIONS"])
def _cors_preflight():
    return "", 204


try:
    backfill_all()
except Exception:
    log.warning("backfill_all failed — continuing")


@app.route("/")
def index():
    try:
        resp = render_template(
            "index.html",
            instruments=list(INSTRUMENTS.keys()),
            default_instrument=DEFAULT_INSTRUMENT,
            core_js_version=CORE_JS_VERSION,
            git_commit=GIT_COMMIT,
        )
        r = make_response(resp)
        r.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        r.headers["Pragma"] = "no-cache"
        return r
    except Exception:
        log.exception("GET / failed")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/instruments")
def list_instruments():
    return jsonify(list(INSTRUMENTS.keys()))


@app.route("/admin/flush_cache", methods=["GET"])
def admin_flush_cache():
    if not _admin_authorized():
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    try:
        stats = flush_chart_cache_keys()
        eq_redis = 0
        r = get_redis()
        if r is not None:
            try:
                for key in r.scan_iter(match="equity_img:*", count=500):
                    try:
                        r.delete(key)
                        eq_redis += 1
                    except Exception as e:
                        log.warning("Redis delete %s failed: %s", key, e)
            except Exception as e:
                log.warning("Redis scan_iter equity_img:* failed: %s", e)
        eq_mem = 0
        with _cache_backend._mem_lock:
            for k in list(_cache_backend._mem.keys()):
                if k.startswith("equity_img:"):
                    _cache_backend._mem.pop(k, None)
                    eq_mem += 1
        stats["equity_redis_deleted"] = eq_redis
        stats["equity_memory_deleted"] = eq_mem
        return jsonify({"ok": True, **stats})
    except Exception:
        log.exception("flush_cache failed")
        return jsonify({"ok": False, "error": "flush failed"}), 500


@app.route("/admin/rebuild_db", methods=["GET"])
def admin_rebuild_db():
    if not _admin_authorized():
        return jsonify({"ok": False, "error": "Forbidden"}), 403
    try:
        run_database_rebuild_async(DEFAULT_TIMEFRAME)
        return jsonify({
            "ok": True,
            "message": f"Database rebuild started (all instruments @ {DEFAULT_TIMEFRAME})",
        })
    except Exception:
        log.exception("rebuild_db failed")
        return jsonify({"ok": False, "error": "rebuild failed"}), 500


@app.route("/chart", methods=["POST"])
def chart():
    data = request.get_json(force=True) or {}
    (
        instrument,
        timeframe,
        regime,
        window_size,
        show_volume,
        notional,
        tree,
    ) = _parse_request(data)
    try:
        window_index = int(data.get("window_index", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid window_index"}), 400

    raw_merged = _merge_indicator_lists([], regime, [], [], tree)
    expanded = _expand_key_list(raw_merged)
    filters_for_key = [x for x in expanded if x in _VALID_FILTERS]
    patterns_for_key = [x for x in expanded if x in _ALL_PATTERNS]
    regime_seg = ",".join(regime)

    ck = cache_key(
        "chart",
        instrument,
        timeframe,
        ",".join(sorted(filters_for_key)),
        ",".join(sorted(patterns_for_key)),
        regime_seg,
        "",
        "",
        window_size,
        window_index,
        int(show_volume),
        notional,
        _tree_cache_segment(tree),
    )
    cached = cache_get(ck)
    if cached:
        img_ck = cached.get("cache_key") or ck
        if not cached.get("image_base64") and not cache_has(f"chart_img:{img_ck}"):
            cache_delete(ck)
            cached = None
    if cached and _stale_chart_cache_missing_indicator_equity(
        cached, filters_for_key, patterns_for_key
    ):
        cache_delete(ck)
        cached = None
    if cached:
        return jsonify(_normalize_cached_chart_payload(cached, ck))

    selector = lambda df, af: get_window(
        df, window_size, af, window_index,
        instrument=instrument, timeframe=timeframe,
    )
    try:
        window, image_b64, candle_map, stats, equity_image_b64 = _run_chart_pipeline(
            instrument,
            timeframe,
            regime,
            window_size,
            show_volume,
            selector,
            notional=float(notional),
            tree=tree,
        )
        meta = INSTRUMENTS[instrument]
        payload = _build_chart_response(window, stats, meta, instrument, timeframe)
        payload["cache_key"] = ck
        _cache_chart_payload_images(ck, image_b64, candle_map, equity_image_b64, payload)
        cache_set(ck, payload, ex=CHART_CACHE_TTL_SEC)
        return jsonify(payload)
    except _NoDataError:
        return jsonify({"error": "No data available for this instrument"}), 503
    except Exception:
        log.exception("/chart failed")
        return jsonify({"error": "Chart generation failed"}), 500


@app.route("/next_window", methods=["POST"])
def next_window():
    data = request.get_json(force=True) or {}
    (
        instrument,
        timeframe,
        regime,
        window_size,
        show_volume,
        notional,
        tree,
    ) = _parse_request(data)
    try:
        current_start = int(data.get("current_start", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid current_start"}), 400
    try:
        current_end = int(data.get("current_end", window_size))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid current_end"}), 400

    raw_merged = _merge_indicator_lists([], regime, [], [], tree)
    expanded = _expand_key_list(raw_merged)
    filters_for_key = [x for x in expanded if x in _VALID_FILTERS]
    patterns_for_key = [x for x in expanded if x in _ALL_PATTERNS]
    regime_seg = ",".join(regime)

    ck = cache_key(
        "next_window",
        instrument,
        timeframe,
        ",".join(sorted(filters_for_key)),
        ",".join(sorted(patterns_for_key)),
        regime_seg,
        "",
        "",
        window_size,
        current_start,
        current_end,
        int(show_volume),
        notional,
        _tree_cache_segment(tree),
    )
    cached = cache_get(ck)
    if cached:
        img_ck = cached.get("cache_key") or ck
        if not cached.get("image_base64") and not cache_has(f"chart_img:{img_ck}"):
            cache_delete(ck)
            cached = None
    if cached and _stale_chart_cache_missing_indicator_equity(
        cached, filters_for_key, patterns_for_key
    ):
        cache_delete(ck)
        cached = None
    if cached:
        return jsonify(_normalize_cached_chart_payload(cached, ck))

    selector = lambda df, af: get_next_window(
        df, window_size, af, current_start, current_end,
        instrument=instrument, timeframe=timeframe,
    )
    try:
        window, image_b64, candle_map, stats, equity_image_b64 = _run_chart_pipeline(
            instrument,
            timeframe,
            regime,
            window_size,
            show_volume,
            selector,
            notional=float(notional),
            tree=tree,
        )
        meta = INSTRUMENTS[instrument]
        payload = _build_chart_response(window, stats, meta, instrument, timeframe)
        payload["cache_key"] = ck
        _cache_chart_payload_images(ck, image_b64, candle_map, equity_image_b64, payload)
        cache_set(ck, payload, ex=CHART_CACHE_TTL_SEC)
        return jsonify(payload)
    except _NoDataError:
        return jsonify({"error": "No data available"}), 503
    except Exception:
        log.exception("/next_window failed")
        return jsonify({"error": "Next window failed"}), 500


@app.route("/prev_window", methods=["POST"])
def prev_window():
    data = request.get_json(force=True) or {}
    (
        instrument,
        timeframe,
        regime,
        window_size,
        show_volume,
        notional,
        tree,
    ) = _parse_request(data)
    try:
        current_start = int(data.get("current_start", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid current_start"}), 400
    try:
        current_end = int(data.get("current_end", window_size))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid current_end"}), 400

    raw_merged = _merge_indicator_lists([], regime, [], [], tree)
    expanded = _expand_key_list(raw_merged)
    filters_for_key = [x for x in expanded if x in _VALID_FILTERS]
    patterns_for_key = [x for x in expanded if x in _ALL_PATTERNS]
    regime_seg = ",".join(regime)

    ck = cache_key(
        "prev_window",
        instrument,
        timeframe,
        ",".join(sorted(filters_for_key)),
        ",".join(sorted(patterns_for_key)),
        regime_seg,
        "",
        "",
        window_size,
        current_start,
        current_end,
        int(show_volume),
        notional,
        _tree_cache_segment(tree),
    )
    cached = cache_get(ck)
    if cached:
        img_ck = cached.get("cache_key") or ck
        if not cached.get("image_base64") and not cache_has(f"chart_img:{img_ck}"):
            cache_delete(ck)
            cached = None
    if cached and _stale_chart_cache_missing_indicator_equity(
        cached, filters_for_key, patterns_for_key
    ):
        cache_delete(ck)
        cached = None
    if cached:
        return jsonify(_normalize_cached_chart_payload(cached, ck))

    selector = lambda df, af: get_prev_window(
        df, window_size, af, current_start, current_end,
        instrument=instrument, timeframe=timeframe,
    )
    try:
        window, image_b64, candle_map, stats, equity_image_b64 = _run_chart_pipeline(
            instrument,
            timeframe,
            regime,
            window_size,
            show_volume,
            selector,
            notional=float(notional),
            tree=tree,
        )
        meta = INSTRUMENTS[instrument]
        payload = _build_chart_response(window, stats, meta, instrument, timeframe)
        payload["cache_key"] = ck
        _cache_chart_payload_images(ck, image_b64, candle_map, equity_image_b64, payload)
        cache_set(ck, payload, ex=CHART_CACHE_TTL_SEC)
        return jsonify(payload)
    except _NoDataError:
        return jsonify({"error": "No data available"}), 503
    except Exception:
        log.exception("/prev_window failed")
        return jsonify({"error": "Prev window failed"}), 500


@app.route("/shift_window", methods=["POST"])
def shift_window():
    data = request.get_json(force=True) or {}
    (
        instrument,
        timeframe,
        regime,
        window_size,
        show_volume,
        notional,
        tree,
    ) = _parse_request(data)
    direction = data.get("direction")
    if direction not in ("left", "right"):
        return jsonify({"error": 'direction must be "left" or "right"'}), 400
    try:
        current_start = int(data.get("current_start", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid current_start"}), 400
    try:
        current_end = int(data.get("current_end", window_size))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid current_end"}), 400

    raw_merged = _merge_indicator_lists([], regime, [], [], tree)
    expanded = _expand_key_list(raw_merged)
    filters_for_key = [x for x in expanded if x in _VALID_FILTERS]
    patterns_for_key = [x for x in expanded if x in _ALL_PATTERNS]
    regime_seg = ",".join(regime)

    ck = cache_key(
        "shift_window",
        instrument,
        timeframe,
        ",".join(sorted(filters_for_key)),
        ",".join(sorted(patterns_for_key)),
        regime_seg,
        "",
        "",
        window_size,
        direction,
        current_start,
        current_end,
        int(show_volume),
        notional,
        _tree_cache_segment(tree),
    )
    cached = cache_get(ck)
    if cached:
        img_ck = cached.get("cache_key") or ck
        if not cached.get("image_base64") and not cache_has(f"chart_img:{img_ck}"):
            cache_delete(ck)
            cached = None
    if cached and _stale_chart_cache_missing_indicator_equity(
        cached, filters_for_key, patterns_for_key
    ):
        cache_delete(ck)
        cached = None
    if cached:
        return jsonify(_normalize_cached_chart_payload(cached, ck))

    selector = lambda df, af: get_shifted_window(
        df, window_size, af, current_start, current_end, direction,
        instrument=instrument, timeframe=timeframe,
    )
    try:
        window, image_b64, candle_map, stats, equity_image_b64 = _run_chart_pipeline(
            instrument,
            timeframe,
            regime,
            window_size,
            show_volume,
            selector,
            notional=float(notional),
            tree=tree,
        )
        meta = INSTRUMENTS[instrument]
        payload = _build_chart_response(window, stats, meta, instrument, timeframe)
        payload["cache_key"] = ck
        _cache_chart_payload_images(ck, image_b64, candle_map, equity_image_b64, payload)
        cache_set(ck, payload, ex=CHART_CACHE_TTL_SEC)
        return jsonify(payload)
    except _NoDataError:
        return jsonify({"error": "No data available"}), 503
    except Exception:
        log.exception("/shift_window failed")
        return jsonify({"error": "Shift window failed"}), 500


@app.route("/chart_image/<path:ck>")
def chart_image(ck: str):
    img_key = f"chart_img:{ck}"
    image_b64 = cache_get(img_key)
    png_bytes = None
    if image_b64:
        try:
            png_bytes = base64.b64decode(image_b64)
            if not png_bytes:
                png_bytes = None
        except Exception:
            png_bytes = None

    if png_bytes is None:
        parsed = _parse_cache_key(ck)
        if parsed:
            inst, tf = parsed.instrument, parsed.timeframe
            regime = parsed.box1
            ws, sv = parsed.window_size, parsed.show_volume
            tr = parsed.tree if isinstance(parsed.tree, dict) else {}
            try:
                if parsed.kind == "chart":
                    selector = lambda df, af: get_window(
                        df, ws, af, parsed.window_index,
                        instrument=inst, timeframe=tf,
                    )
                elif parsed.kind == "next_window":
                    selector = lambda df, af: get_next_window(
                        df, ws, af, parsed.current_start, parsed.current_end,
                        instrument=inst, timeframe=tf,
                    )
                elif parsed.kind == "shift_window":
                    selector = lambda df, af: get_shifted_window(
                        df, ws, af, parsed.current_start, parsed.current_end,
                        parsed.shift_direction,
                        instrument=inst, timeframe=tf,
                    )
                else:
                    selector = lambda df, af: get_prev_window(
                        df, ws, af, parsed.current_start, parsed.current_end,
                        instrument=inst, timeframe=tf,
                    )
                _w, image_b64_new, candle_map, _stats, equity_image_b64 = _run_chart_pipeline(
                    inst,
                    tf,
                    regime,
                    ws,
                    sv,
                    selector,
                    notional=float(parsed.notional),
                    tree=tr,
                )
                cache_set(img_key, image_b64_new, ex=IMAGE_CACHE_TTL_SEC)
                cache_set(f"candle_map:{ck}", candle_map, ex=IMAGE_CACHE_TTL_SEC)
                if equity_image_b64 is not None:
                    cache_set(
                        f"equity_img:{ck}", equity_image_b64, ex=IMAGE_CACHE_TTL_SEC,
                    )
                png_bytes = base64.b64decode(image_b64_new)
            except _NoDataError:
                log.warning("chart_image recompute: no data for %s", ck)
            except Exception:
                log.exception("chart_image recompute failed for %s", ck)
        else:
            log.warning("Chart image not in cache (unparseable key): %s", img_key)

    if png_bytes is None:
        png_bytes = _TRANSPARENT_PNG_1X1

    response = make_response(png_bytes)
    response.headers["Content-Type"] = "image/png"
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@app.route("/equity_image/<path:ck>")
def equity_image(ck: str):
    eq_key = f"equity_img:{ck}"
    image_b64 = cache_get(eq_key)
    png_bytes = None
    if image_b64:
        try:
            png_bytes = base64.b64decode(image_b64)
            if not png_bytes:
                png_bytes = None
        except Exception:
            png_bytes = None

    if png_bytes is None:
        parsed = _parse_cache_key(ck)
        if parsed:
            inst, tf = parsed.instrument, parsed.timeframe
            regime = parsed.box1
            ws, sv = parsed.window_size, parsed.show_volume
            tr = parsed.tree if isinstance(parsed.tree, dict) else {}
            try:
                if parsed.kind == "chart":
                    selector = lambda df, af: get_window(
                        df, ws, af, parsed.window_index,
                        instrument=inst, timeframe=tf,
                    )
                elif parsed.kind == "next_window":
                    selector = lambda df, af: get_next_window(
                        df, ws, af, parsed.current_start, parsed.current_end,
                        instrument=inst, timeframe=tf,
                    )
                elif parsed.kind == "shift_window":
                    selector = lambda df, af: get_shifted_window(
                        df, ws, af, parsed.current_start, parsed.current_end,
                        parsed.shift_direction,
                        instrument=inst, timeframe=tf,
                    )
                else:
                    selector = lambda df, af: get_prev_window(
                        df, ws, af, parsed.current_start, parsed.current_end,
                        instrument=inst, timeframe=tf,
                    )
                _w, image_b64_new, candle_map, _stats, equity_image_b64 = _run_chart_pipeline(
                    inst,
                    tf,
                    regime,
                    ws,
                    sv,
                    selector,
                    notional=float(parsed.notional),
                    tree=tr,
                )
                cache_set(f"chart_img:{ck}", image_b64_new, ex=IMAGE_CACHE_TTL_SEC)
                cache_set(f"candle_map:{ck}", candle_map, ex=IMAGE_CACHE_TTL_SEC)
                if equity_image_b64 is not None:
                    cache_set(eq_key, equity_image_b64, ex=IMAGE_CACHE_TTL_SEC)
                    png_bytes = base64.b64decode(equity_image_b64)
            except _NoDataError:
                log.warning("equity_image recompute: no data for %s", ck)
            except Exception:
                log.exception("equity_image recompute failed for %s", ck)
        else:
            log.warning("Equity image not in cache (unparseable key): %s", eq_key)

    if png_bytes is None:
        png_bytes = _TRANSPARENT_PNG_1X1

    response = make_response(png_bytes)
    response.headers["Content-Type"] = "image/png"
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@app.route("/candle_map/<path:ck>")
def candle_map_endpoint(ck: str):
    cm = cache_get(f"candle_map:{ck}")
    if cm is None:
        return jsonify({}), 404
    return jsonify(cm)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
