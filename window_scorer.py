"""
window_scorer.py — Window scoring and next-window selection.
Implements the exact algorithm from the spec.
No third-party quant libraries.
"""
import hashlib
import logging
import numpy as np
import pandas as pd
from cache import cache_get, cache_set

log = logging.getLogger(__name__)

# ── Named constants ───────────────────────────────────────────────────────────
WINDOW_SCORE_CACHE_TTL_SEC  = 300
SCORE_FIRST_HIT             = 10
SCORE_REPEAT                = 3
SCORE_DIVERSITY_PER_FILTER  = 5

# When "volume_spike" is active, boost windows that contain ≥1 spike bar so they
# rank above windows with zero spikes (other filters can otherwise dominate).
SPIKE_WINDOW_SCORE_MULT     = 2
SPIKE_COUNT_SCORE_BONUS     = 1  # per spike bar inside the window (after mult)

# Filter id → DataFrame column (must match indicators.py / chart_renderer)
_MA_FILTER_TO_COL = {
    "ema": "ema20",
    "ema9": "ema9",
    "ema20": "ema20",
    "ema50": "ema50",
    "ema200": "ema200",
    "sma10": "sma10",
    "sma20": "sma20",
    "sma50": "sma50",
    "sma200": "sma200",
}

# Filter id → indicator period (for skipping windows before all selected MAs are warm)
_MA_FILTER_WARMUP = {
    "ema9": 9,
    "sma9": 9,
    "ema20": 20,
    "sma20": 20,
    "ema": 20,
    "ema50": 50,
    "sma50": 50,
    "ema200": 200,
    "sma200": 200,
    "sma10": 10,
}


def _max_ma_warmup_bars(active_filters: list[str]) -> int:
    """Largest MA period among selected MA filters; 0 if none."""
    m = 0
    for f in active_filters:
        p = _MA_FILTER_WARMUP.get(f)
        if p is not None:
            m = max(m, p)
    return m


def _ma_columns_for_filters(active_filters: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for f in active_filters:
        col = _MA_FILTER_TO_COL.get(f)
        if col and col not in seen:
            seen.add(col)
            out.append(col)
    return out


def _window_has_finite_ma_values(
    df: pd.DataFrame, start: int, end: int, ma_cols: list[str],
) -> bool:
    """
    True iff the last bar of the window (index end - 1) has a finite value for
    every selected MA column — matches the right edge of the chart where the line must show.

    Windows use a half-open slice [start, end): the last included row is iloc[end - 1]
    (same as df.iloc[start:end]). E.g. start=0, window_size=50 → end=50 → last bar index 49.
    """
    if not ma_cols:
        return True
    if end <= start:
        return False
    row = df.iloc[end - 1]
    for col in ma_cols:
        if col not in df.columns:
            return False
        v = row.get(col, np.nan)
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return False
        if not np.isfinite(fv):
            return False
    return True


def _volume_spike_bar_count(df: pd.DataFrame, start: int, end: int) -> int:
    """Bars in [start, end) where volume_spike == 1.0 (column from apply_indicators)."""
    if "volume_spike" not in df.columns or end <= start:
        return 0
    sub = df["volume_spike"].iloc[start:end]
    return int((sub == 1.0).sum())


def _adjust_score_for_volume_spike_window(
    df: pd.DataFrame,
    start: int,
    end: int,
    active_filters: list[str],
    base_score: int,
) -> int:
    """
    If volume_spike is selected and the window has at least one spike bar, scale the
    base score and add a small per-spike bonus. Windows with zero spikes keep base_score.
    """
    if "volume_spike" not in active_filters:
        return base_score
    n_spike = _volume_spike_bar_count(df, start, end)
    if n_spike <= 0:
        return base_score
    return base_score * SPIKE_WINDOW_SCORE_MULT + n_spike * SPIKE_COUNT_SCORE_BONUS


def _filter_hit(row: pd.Series, filter_name: str) -> bool:
    """
    Return True if the given filter fires on this candle row.
    Checks indicator columns added by apply_indicators / apply_patterns.
    Cython-friendly: pure boolean logic on scalars.
    """
    if filter_name == "bb":
        u = row.get("bb_upper", np.nan)
        l = row.get("bb_lower", np.nan)
        c = row.get("close", np.nan)
        if np.isnan(u) or np.isnan(l):
            return False
        return bool(c > u or c < l)

    if filter_name == "rsi":
        r = row.get("rsi", np.nan)
        if np.isnan(r):
            return False
        return bool(r > 70.0 or r < 30.0)

    if filter_name == "macd":
        # MACD crossover: histogram changes sign
        h = row.get("macd_hist", np.nan)
        if np.isnan(h):
            return False
        return bool(h != 0.0)

    if filter_name == "ema":
        e = row.get("ema20", np.nan)
        c = row.get("close", np.nan)
        if np.isnan(e) or np.isnan(c):
            return False
        return True   # EMA present = filter active on every bar; score it as always firing

    if filter_name == "bb_width":
        w = row.get("bb_width", np.nan)
        if np.isnan(w):
            return False
        return bool(w > 0.0)

    if filter_name == "volume_spike":
        v = row.get("volume_spike", np.nan)
        if np.isnan(v):
            return False
        return bool(v == 1.0)

    # Pattern filters: col name is pat_<name>
    col = f"pat_{filter_name}"
    val = row.get(col, 0)
    return bool(val != 0)


def score_window(candle_rows: list[pd.Series], active_filters: list[str]) -> int:
    """
    Score a list of candle rows against active filters.
    Exact algorithm from spec:
      - First hit per filter name: +10
      - Repeat hit of same filter: +3
      - Diversity bonus: +5 per unique filter that fired
    Returns integer score.
    """
    score = 0
    filters_hit: set = set()
    filter_counts: dict[str, int] = {}

    for row in candle_rows:
        for f in active_filters:
            if _filter_hit(row, f):
                if f not in filters_hit:
                    score += SCORE_FIRST_HIT
                    filters_hit.add(f)
                    filter_counts[f] = 1
                else:
                    score += SCORE_REPEAT
                    filter_counts[f] = filter_counts.get(f, 0) + 1

    # Diversity bonus
    score += len(filters_hit) * SCORE_DIVERSITY_PER_FILTER
    candle_rows_df = pd.DataFrame(candle_rows)
    if "signal" in candle_rows_df.columns:
        trade_count = int((candle_rows_df["signal"] != 0).sum())
        score += trade_count * 10
    return score


def score_all_windows(df: pd.DataFrame, window_size: int,
                      active_filters: list[str],
                      instrument: str = "", timeframe: str = "") -> list[dict]:
    """
    Score every possible window of `window_size` candles in df.
    Skips windows with start < max MA warmup among selected MA filters.
    Returns list of dicts: {start, end, score} sorted by score descending (best
    first). Navigation walks this list by index via _window_index_by_start_end.
    Results are cached in Redis for 5 minutes when instrument/timeframe are provided.
    """
    n = len(df)
    if n < window_size:
        return [{"start": 0, "end": n, "score": 0}]

    # Cache lookup
    filters_hash = hashlib.md5(",".join(sorted(active_filters)).encode()).hexdigest()[:8]
    ck = f"score_windows:{instrument}:{timeframe}:{window_size}:{filters_hash}"
    cached = cache_get(ck)
    if cached is not None:
        return cached

    ma_cols = _ma_columns_for_filters(active_filters)
    max_warmup_bars = _max_ma_warmup_bars(active_filters)
    results = []
    # Pre-convert rows to a list of Series for fast iteration
    rows = [df.iloc[i] for i in range(n)]

    for start in range(max_warmup_bars, n - window_size + 1):
        end = start + window_size
        ma_ok = (not ma_cols) or _window_has_finite_ma_values(df, start, end, ma_cols)
        if ma_cols and not ma_ok:
            continue
        window_rows = rows[start:end]
        base = score_window(window_rows, active_filters)
        s = _adjust_score_for_volume_spike_window(df, start, end, active_filters, base)
        results.append({"start": start, "end": end, "score": s})

    if not results:
        start = max(0, n - window_size)
        end = n
        base = score_window(rows[start:end], active_filters)
        s = _adjust_score_for_volume_spike_window(df, start, end, active_filters, base)
        results.append({
            "start": start,
            "end": end,
            "score": s,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    cache_set(ck, results, ex=WINDOW_SCORE_CACHE_TTL_SEC)
    return results


def _window_index_by_start_end(
    all_windows: list[dict], current_start: int, current_end: int,
) -> int:
    """Index in the score-ranked list for the window matching (start, end); 0 if unknown."""
    for i, w in enumerate(all_windows):
        if w["start"] == current_start and w["end"] == current_end:
            return i
    return 0


def get_window(df: pd.DataFrame, window_size: int,
               active_filters: list[str], window_index: int = 0,
               instrument: str = "", timeframe: str = "") -> dict:
    """
    Return the window at `window_index` in score-ranked order (0 = highest score).
    Falls back to last entry in the list if index out of range.
    """
    all_windows = score_all_windows(df, window_size, active_filters,
                                    instrument=instrument, timeframe=timeframe)
    if not all_windows:
        return {"start": max(0, len(df) - window_size), "end": len(df), "score": 0,
                "current": 1, "total": 1}
    idx = min(window_index, len(all_windows) - 1)
    w = all_windows[idx]
    w["current"] = idx + 1
    w["total"]   = len(all_windows)

    # Build description
    sub = df.iloc[w["start"]:w["end"]]
    pat_cols = [c for c in sub.columns if c.startswith("pat_")]
    n_signals = int((sub[pat_cols].abs().sum(axis=1) > 0).sum()) if pat_cols else 0
    filters_desc = ", ".join(f.upper() for f in active_filters[:3])
    w["description"] = f"{n_signals} signal(s) — {filters_desc or 'no filters'}"
    return w


def get_next_window(df: pd.DataFrame, window_size: int,
                    active_filters: list[str],
                    current_start: int, current_end: int,
                    instrument: str = "", timeframe: str = "") -> dict:
    """
    Next window in score-ranked order: locate current (start, end), then index + 1
    (clamped to last).
    """
    all_windows = score_all_windows(df, window_size, active_filters,
                                    instrument=instrument, timeframe=timeframe)
    if not all_windows:
        return {"start": max(0, len(df) - window_size), "end": len(df), "score": 0,
                "current": 1, "total": 1, "description": ""}
    i = _window_index_by_start_end(all_windows, current_start, current_end)
    j = min(i + 1, len(all_windows) - 1)
    w = all_windows[j]
    w["current"] = j + 1
    w["total"]   = len(all_windows)
    sub = df.iloc[w["start"]:w["end"]]
    pat_cols = [c for c in sub.columns if c.startswith("pat_")]
    n_signals = int((sub[pat_cols].abs().sum(axis=1) > 0).sum()) if pat_cols else 0
    filters_desc = ", ".join(f.upper() for f in active_filters[:3])
    w["description"] = f"{n_signals} signal(s) — {filters_desc or 'no filters'}"
    return w


def get_prev_window(df: pd.DataFrame, window_size: int,
                    active_filters: list[str],
                    current_start: int, current_end: int,
                    instrument: str = "", timeframe: str = "") -> dict:
    """
    Previous window in score-ranked order; index = current match - 1 (clamped to 0).
    """
    all_windows = score_all_windows(df, window_size, active_filters,
                                    instrument=instrument, timeframe=timeframe)
    if not all_windows:
        return {"start": max(0, len(df) - window_size), "end": len(df), "score": 0,
                "current": 1, "total": 1, "description": ""}
    i = _window_index_by_start_end(all_windows, current_start, current_end)
    j = max(i - 1, 0)
    w = all_windows[j]
    w["current"] = j + 1
    w["total"]   = len(all_windows)
    sub = df.iloc[w["start"]:w["end"]]
    pat_cols = [c for c in sub.columns if c.startswith("pat_")]
    n_signals = int((sub[pat_cols].abs().sum(axis=1) > 0).sum()) if pat_cols else 0
    filters_desc = ", ".join(f.upper() for f in active_filters[:3])
    w["description"] = f"{n_signals} signal(s) — {filters_desc or 'no filters'}"
    return w


def get_shifted_window(
    df: pd.DataFrame,
    window_size: int,
    active_filters: list[str],
    current_start: int,
    current_end: int,
    direction: str,
    instrument: str = "",
    timeframe: str = "",
) -> dict:
    """
    Move the view by one full window along the series: ``left`` → earlier bars,
    ``right`` → later bars. Clamps so the slice stays within ``df`` (length n).
    """
    n = len(df)
    all_windows = score_all_windows(df, window_size, active_filters,
                                    instrument=instrument, timeframe=timeframe)
    if n == 0:
        return {"start": 0, "end": 0, "score": 0, "current": 1, "total": 1, "description": ""}

    if n < window_size:
        start, end = 0, n
    else:
        step = window_size if direction == "right" else -window_size
        max_start = n - window_size
        new_start = current_start + step
        new_start = max(0, min(new_start, max_start))
        start, end = new_start, new_start + window_size

    window_rows = [df.iloc[i] for i in range(start, end)]
    base = score_window(window_rows, active_filters) if window_rows else 0
    s = _adjust_score_for_volume_spike_window(df, start, end, active_filters, base)

    idx_in_rank = None
    for i, w in enumerate(all_windows):
        if w["start"] == start and w["end"] == end:
            idx_in_rank = i
            break
    cur = (idx_in_rank + 1) if idx_in_rank is not None else 1
    total = len(all_windows) if all_windows else 1

    sub = df.iloc[start:end]
    pat_cols = [c for c in sub.columns if c.startswith("pat_")]
    n_signals = int((sub[pat_cols].abs().sum(axis=1) > 0).sum()) if pat_cols else 0
    filters_desc = ", ".join(f.upper() for f in active_filters[:3])
    desc = f"{n_signals} signal(s) — {filters_desc or 'no filters'}"
    return {
        "start": start,
        "end": end,
        "score": s,
        "current": cur,
        "total": total,
        "description": desc,
    }
