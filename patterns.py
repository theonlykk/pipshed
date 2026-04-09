"""
patterns.py — Candlestick pattern detection.
Each detector returns a pd.Series of signals: +1 (bullish), -1 (bearish), 0 (none).
No third-party quant libraries. All logic is pure pandas/numpy.
"""
import numpy as np
import pandas as pd


# ── Internal helpers ──────────────────────────────────────────────────────────
def _body(df):    return (df["close"] - df["open"]).abs()
def _upper(df):   return df["high"] - df[["open", "close"]].max(axis=1)
def _lower(df):   return df[["open", "close"]].min(axis=1) - df["low"]
def _range(df):   return df["high"] - df["low"]
def _bull(df):    return df["close"] > df["open"]
def _bear(df):    return df["close"] < df["open"]
def _prior_trend(df, n=3): return df["close"].diff(n)


# ── 1. Doji ───────────────────────────────────────────────────────────────────
def doji(df: pd.DataFrame) -> pd.Series:
    """Body < 10% of total range. Direction from prior 3-bar trend."""
    b = _body(df)
    r = _range(df)
    is_doji = (r > 0) & (b / r.clip(lower=1e-10) < 0.10)
    trend = _prior_trend(df)
    sig = pd.Series(0, index=df.index)
    sig[is_doji & (trend < 0)] =  1   # bullish reversal after downtrend
    sig[is_doji & (trend > 0)] = -1   # bearish reversal after uptrend
    return sig


# ── 2. Hammer ─────────────────────────────────────────────────────────────────
def hammer(df: pd.DataFrame) -> pd.Series:
    """
    Lower wick >= 2x body, upper wick <= 30% of range, body > 0.
    Bullish only — appears after a downtrend.
    """
    b  = _body(df)
    lo = _lower(df)
    up = _upper(df)
    r  = _range(df)
    is_pattern = (r > 0) & (b > 0) & (lo >= 2.0 * b) & (up <= 0.3 * r)
    trend = _prior_trend(df)
    sig = pd.Series(0, index=df.index)
    sig[is_pattern & (trend < 0)] = 1
    return sig


# ── 3. Hanging Man ────────────────────────────────────────────────────────────
def hanging_man(df: pd.DataFrame) -> pd.Series:
    """
    Same shape as Hammer but bearish — appears after an uptrend.
    """
    b  = _body(df)
    lo = _lower(df)
    up = _upper(df)
    r  = _range(df)
    is_pattern = (r > 0) & (b > 0) & (lo >= 2.0 * b) & (up <= 0.3 * r)
    trend = _prior_trend(df)
    sig = pd.Series(0, index=df.index)
    sig[is_pattern & (trend > 0)] = -1
    return sig


# ── 4. Shooting Star ──────────────────────────────────────────────────────────
def shooting_star(df: pd.DataFrame) -> pd.Series:
    """
    Upper wick >= 2x body, lower wick <= 30% of range, body > 0.
    Bearish only — appears after an uptrend.
    """
    b  = _body(df)
    lo = _lower(df)
    up = _upper(df)
    r  = _range(df)
    is_pattern = (r > 0) & (b > 0) & (up >= 2.0 * b) & (lo <= 0.3 * r)
    trend = _prior_trend(df)
    sig = pd.Series(0, index=df.index)
    sig[is_pattern & (trend > 0)] = -1
    return sig


# ── 5. Inverted Hammer ────────────────────────────────────────────────────────
def inverted_hammer(df: pd.DataFrame) -> pd.Series:
    """
    Same shape as Shooting Star but bullish — appears after a downtrend.
    """
    b  = _body(df)
    lo = _lower(df)
    up = _upper(df)
    r  = _range(df)
    is_pattern = (r > 0) & (b > 0) & (up >= 2.0 * b) & (lo <= 0.3 * r)
    trend = _prior_trend(df)
    sig = pd.Series(0, index=df.index)
    sig[is_pattern & (trend < 0)] = 1
    return sig


# ── 6. Engulfing (bullish and bearish) ────────────────────────────────────────
def engulfing(df: pd.DataFrame) -> pd.Series:
    """
    Current body fully engulfs prior body.
    Bullish: prior bearish, current bullish, current open < prior close, current close > prior open.
    Bearish: mirror.
    """
    sig = pd.Series(0, index=df.index)
    o, c   = df["open"], df["close"]
    po, pc = o.shift(1), c.shift(1)
    bull = _bear(df.shift(1)) & _bull(df) & (c > po) & (o < pc)
    bear = _bull(df.shift(1)) & _bear(df) & (c < po) & (o > pc)
    sig[bull] =  1
    sig[bear] = -1
    return sig


# ── 7. Morning Star ───────────────────────────────────────────────────────────
def morning_star(df: pd.DataFrame) -> pd.Series:
    """
    3-candle bullish reversal:
    C-2: large bearish, C-1: small body (star), C-0: bullish closing into C-2 body.
    Signal placed on C-0 (the confirming candle).
    """
    sig = pd.Series(0, index=df.index)
    b0 = _body(df)
    b2 = _body(df.shift(2))
    star = _body(df.shift(1)) < 0.3 * b2
    pattern = (
        star &
        _bear(df.shift(2)) &
        _bull(df) &
        (df["close"] > (df["open"].shift(2) + df["close"].shift(2)) / 2.0)
    )
    sig[pattern] = 1
    return sig


# ── 8. Evening Star ───────────────────────────────────────────────────────────
def evening_star(df: pd.DataFrame) -> pd.Series:
    """
    3-candle bearish reversal:
    C-2: large bullish, C-1: small body (star), C-0: bearish closing into C-2 body.
    Signal placed on C-0 (the confirming candle).
    """
    sig = pd.Series(0, index=df.index)
    b2  = _body(df.shift(2))
    star = _body(df.shift(1)) < 0.3 * b2
    pattern = (
        star &
        _bull(df.shift(2)) &
        _bear(df) &
        (df["close"] < (df["open"].shift(2) + df["close"].shift(2)) / 2.0)
    )
    sig[pattern] = -1
    return sig


# ── 9. Harami ─────────────────────────────────────────────────────────────────
def harami(df: pd.DataFrame) -> pd.Series:
    """Current body contained within prior body."""
    sig = pd.Series(0, index=df.index)
    body_max  = df[["open", "close"]].max(axis=1)
    body_min  = df[["open", "close"]].min(axis=1)
    prior_max = df[["open", "close"]].shift(1).max(axis=1)
    prior_min = df[["open", "close"]].shift(1).min(axis=1)
    contained = (body_max < prior_max) & (body_min > prior_min)
    sig[contained & _bear(df.shift(1)) & _bull(df)] =  1
    sig[contained & _bull(df.shift(1)) & _bear(df)] = -1
    return sig


# ── 10. Piercing Line / Dark Cloud Cover ─────────────────────────────────────
def piercing_dark_cloud(df: pd.DataFrame) -> pd.Series:
    sig = pd.Series(0, index=df.index)
    o, c   = df["open"], df["close"]
    po, pc = o.shift(1), c.shift(1)
    mid1   = (po + pc) / 2.0
    piercing = (
        _bear(df.shift(1)) & _bull(df) &
        (o < df["low"].shift(1)) &
        (c > mid1) & (c < po)
    )
    dark_cloud = (
        _bull(df.shift(1)) & _bear(df) &
        (o > df["high"].shift(1)) &
        (c < mid1) & (c > po)
    )
    sig[piercing]   =  1
    sig[dark_cloud] = -1
    return sig


# ── 11. Three White Soldiers / Three Black Crows ──────────────────────────────
def three_soldiers_crows(df: pd.DataFrame) -> pd.Series:
    sig = pd.Series(0, index=df.index)
    o, c = df["open"], df["close"]
    soldiers = (
        _bull(df) & _bull(df.shift(1)) & _bull(df.shift(2)) &
        (o > df["open"].shift(1)) & (o < df["close"].shift(1)) &
        (c > df["close"].shift(1)) &
        (df["open"].shift(1) > df["open"].shift(2)) &
        (df["close"].shift(1) > df["close"].shift(2))
    )
    crows = (
        _bear(df) & _bear(df.shift(1)) & _bear(df.shift(2)) &
        (o < df["open"].shift(1)) & (o > df["close"].shift(1)) &
        (c < df["close"].shift(1)) &
        (df["open"].shift(1) < df["open"].shift(2)) &
        (df["close"].shift(1) < df["close"].shift(2))
    )
    sig[soldiers] =  1
    sig[crows]    = -1
    return sig


# ── Registry ──────────────────────────────────────────────────────────────────
# Keys must match the filter names sent by the UI.
PATTERN_REGISTRY = {
    "doji":            doji,
    "hammer":          hammer,
    "hanging_man":     hanging_man,
    "shooting_star":   shooting_star,
    "inverted_hammer": inverted_hammer,
    "engulfing":       engulfing,
    "morning_star":    morning_star,
    "evening_star":    evening_star,
    "harami":          harami,
    "piercing_dark_cloud":   piercing_dark_cloud,
    "three_soldiers_crows":  three_soldiers_crows,
}

# Human-readable labels for annotations
PATTERN_LABELS = {
    "doji":            "DJ",
    "hammer":          "HM",
    "hanging_man":     "HG",
    "shooting_star":   "SS",
    "inverted_hammer": "IH",
    "engulfing":       "EN",
    "morning_star":    "MS",
    "evening_star":    "ES",
    "harami":          "HR",
    "piercing_dark_cloud":  "PL/DC",
    "three_soldiers_crows": "3S/3C",
}



def apply_patterns(df: pd.DataFrame, active_patterns: list) -> pd.DataFrame:
    """
    Run each requested pattern detector and add 'pat_<name>' columns (+1/-1/0).
    Also adds combined 'signal' column (dominant: first non-zero wins).
    Returns df with added columns.
    """
    for name in active_patterns:
        fn = PATTERN_REGISTRY.get(name)
        if fn is not None:
            df[f"pat_{name}"] = fn(df)

    # Combined signal: first non-zero pattern wins per candle (vectorised)
    n = len(df)
    pat_arrays = [
        df[f"pat_{name}"].to_numpy(dtype=np.int8)
        for name in active_patterns
        if f"pat_{name}" in df.columns
    ]
    if pat_arrays:
        mat = np.stack(pat_arrays, axis=0)          # (num_patterns, n)
        has_signal = np.any(mat != 0, axis=0)        # (n,) bool
        first_idx  = np.argmax(mat != 0, axis=0)     # (n,) index of first non-zero row
        signals = np.where(has_signal,
                           mat[first_idx, np.arange(n)],
                           0).astype(np.int8)
    else:
        signals = np.zeros(n, dtype=np.int8)
    df["signal"] = signals
    return df
