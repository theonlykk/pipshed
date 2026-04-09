"""
indicators.py — All indicator calculations from scratch using numpy/pandas only.
No scipy, no QuantLib, no ta-lib.
Bloomberg defaults throughout.
Cython-friendly: hot loops use only scalars and plain arrays.
"""
import numpy as np
import pandas as pd


# ── EMA ───────────────────────────────────────────────────────────────────────
def ema(arr: np.ndarray, period: int) -> np.ndarray:
    """
    Exponential moving average.
    Seed: SMA of the first `period` values (Bloomberg / TradingView convention).
    Alpha = 2 / (period + 1).
    Returns array of same length padded with NaN until index period-1.
    Cython-friendly: inner loop operates on plain float scalars.
    """
    n = len(arr)
    out = np.full(n, np.nan)
    if n < period:
        return out
    alpha = 2.0 / (period + 1.0)
    one_minus = 1.0 - alpha
    seed = 0.0
    for i in range(period):
        seed += arr[i]
    seed /= period
    out[period - 1] = seed
    prev = seed
    for i in range(period, n):
        v = alpha * arr[i] + one_minus * prev
        out[i] = v
        prev = v
    return out


# ── SMA ───────────────────────────────────────────────────────────────────────
def sma(arr: np.ndarray, period: int) -> np.ndarray:
    """
    Simple moving average via convolution.
    Returns array of same length padded with NaN until index period-1.
    """
    n = len(arr)
    out = np.full(n, np.nan)
    if n < period:
        return out
    kernel = np.ones(period) / period
    valid = np.convolve(arr, kernel, mode="valid")
    out[period - 1:] = valid
    return out


# ── Bollinger Bands ───────────────────────────────────────────────────────────
def bollinger_bands(arr: np.ndarray, period: int = 20, nstd: float = 2.0):
    """
    Bollinger Bands: 20-period SMA ± 2 population std deviations.
    Bloomberg uses population std (ddof=0).
    Returns (upper, mid, lower) — three arrays of same length as arr.
    """
    n = len(arr)
    if n < period:
        empty = np.full(n, np.nan)
        return empty.copy(), empty.copy(), empty.copy()
    s_arr = pd.Series(arr).rolling(period).std(ddof=0).values
    m_arr = pd.Series(arr).rolling(period).mean().values
    upper = m_arr + nstd * s_arr
    lower = m_arr - nstd * s_arr
    return upper, m_arr, lower


# ── RSI ───────────────────────────────────────────────────────────────────────
def rsi(arr: np.ndarray, period: int = 14) -> np.ndarray:
    """
    RSI using Wilder's exponential smoothing (Bloomberg default).
    Seed: simple average of first `period` gains/losses.
    Returns array of same length padded with NaN until index `period`.
    Cython-friendly inner loop.
    """
    n = len(arr)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    delta = np.empty(n - 1)
    for i in range(n - 1):
        delta[i] = arr[i + 1] - arr[i]
    gains  = np.empty(n - 1)
    losses = np.empty(n - 1)
    for i in range(n - 1):
        d = delta[i]
        gains[i]  = d  if d > 0.0 else 0.0
        losses[i] = -d if d < 0.0 else 0.0

    # seed with simple average of first period values
    avg_gain = 0.0
    avg_loss = 0.0
    for i in range(period):
        avg_gain += gains[i]
        avg_loss += losses[i]
    avg_gain /= period
    avg_loss /= period

    if avg_loss == 0.0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    # Wilder's smoothing: (prev * (period-1) + current) / period
    for i in range(period, n - 1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0.0:
            out[i + 1] = 100.0
        else:
            out[i + 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


# ── MACD ──────────────────────────────────────────────────────────────────────
def macd(arr: np.ndarray, fast: int = 12, slow: int = 26, signal_period: int = 9):
    """
    MACD: EMA(fast) - EMA(slow), signal = EMA(macd_line, signal_period).
    Bloomberg defaults: 12/26/9.
    Returns (macd_line, signal_line, histogram) — three arrays of same length as arr.
    """
    fast_ema   = ema(arr, fast)
    slow_ema   = ema(arr, slow)
    macd_line  = fast_ema - slow_ema    # NaN until index slow-1
    # Signal EMA starts once macd_line has enough non-NaN values
    valid_start = slow - 1              # first valid macd_line index
    n = len(arr)
    sig_line  = np.full(n, np.nan)
    histogram = np.full(n, np.nan)

    if n - valid_start < signal_period:
        return macd_line, sig_line, histogram

    # Build signal EMA over the valid portion of macd_line
    sig_arr = macd_line[valid_start:]
    sig_ema = ema(sig_arr, signal_period)
    sig_line[valid_start:] = sig_ema

    for i in range(n):
        if not (np.isnan(macd_line[i]) or np.isnan(sig_line[i])):
            histogram[i] = macd_line[i] - sig_line[i]
    return macd_line, sig_line, histogram


# ── ATR ───────────────────────────────────────────────────────────────────────
def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """
    Average True Range using Wilder's smoothing.
    TR = max(high-low, |high-prev_close|, |low-prev_close|)
    Returns array of same length padded with NaN until index `period`.
    Cython-friendly inner loop.
    """
    n = len(high)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i]  - close[i - 1])
        tr[i] = hl if hl >= hc and hl >= lc else (hc if hc >= lc else lc)

    # Seed: simple average of first `period` TRs
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


# ── BB Width ──────────────────────────────────────────────────────────────────
def bb_width(upper: np.ndarray, mid: np.ndarray, lower: np.ndarray) -> np.ndarray:
    """
    Bollinger Band Width = (upper - lower) / mid.
    Returns NaN wherever mid is NaN or zero.
    """
    n = len(upper)
    out = np.full(n, np.nan)
    for i in range(n):
        m = mid[i]
        if not np.isnan(m) and m != 0.0:
            out[i] = (upper[i] - lower[i]) / m
    return out


# ── Volume Spike ──────────────────────────────────────────────────────────────
def volume_spike(volume: np.ndarray, period: int = 20, threshold: float = 2.0) -> np.ndarray:
    """
    Returns 1.0 where volume > threshold * SMA(volume, period), else 0.0.
    NaN until period-1.
    """
    n = len(volume)
    out = np.full(n, np.nan)
    if n < period:
        return out
    vol_sma = sma(volume, period)
    for i in range(period - 1, n):
        s = vol_sma[i]
        if not np.isnan(s) and s > 0.0:
            out[i] = 1.0 if volume[i] > threshold * s else 0.0
    return out


# ── Stochastic ────────────────────────────────────────────────────────────────
def stochastic(high: np.ndarray, low: np.ndarray, close: np.ndarray,
               k_period: int = 14, d_period: int = 3):
    """
    Fast Stochastic.
    %K = (C - lowest_low_k) / (highest_high_k - lowest_low_k) * 100
    %D = SMA(%K, d_period)
    Bloomberg default 14/3.
    Returns (k_arr, d_arr).
    """
    n = len(close)
    k_arr = np.full(n, np.nan)
    for i in range(k_period - 1, n):
        hh = np.max(high[i - k_period + 1: i + 1])
        ll = np.min(low[i - k_period + 1: i + 1])
        denom = hh - ll
        if denom == 0.0:
            k_arr[i] = 50.0
        else:
            k_arr[i] = (close[i] - ll) / denom * 100.0
    d_arr = sma(k_arr, d_period)
    return k_arr, d_arr


# ── CCI ───────────────────────────────────────────────────────────────────────
def cci(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 20) -> np.ndarray:
    """
    CCI = (typical_price - SMA(typical)) / (0.015 * mean_deviation)
    Typical price = (H + L + C) / 3.
    Bloomberg default period = 20.
    """
    n = len(close)
    out = np.full(n, np.nan)
    typical = (high + low + close) / 3.0
    for i in range(period - 1, n):
        window = typical[i - period + 1: i + 1]
        m = window.mean()
        mean_dev = np.mean(np.abs(window - m))
        if mean_dev == 0.0:
            out[i] = 0.0
        else:
            out[i] = (typical[i] - m) / (0.015 * mean_dev)
    return out


# ── Williams %R ───────────────────────────────────────────────────────────────
def williams_r(high: np.ndarray, low: np.ndarray, close: np.ndarray,
               period: int = 14) -> np.ndarray:
    """
    Williams %R = (highest_high - C) / (highest_high - lowest_low) * -100
    Bloomberg default period = 14.
    """
    n = len(close)
    out = np.full(n, np.nan)
    for i in range(period - 1, n):
        hh = np.max(high[i - period + 1: i + 1])
        ll = np.min(low[i - period + 1: i + 1])
        denom = hh - ll
        if denom == 0.0:
            out[i] = -50.0
        else:
            out[i] = (hh - close[i]) / denom * -100.0
    return out


# ── Keltner Channels ──────────────────────────────────────────────────────────
def keltner_channels(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                     ema_period: int = 20, atr_period: int = 10,
                     multiplier: float = 2.0):
    """
    Keltner Channels.
    Center = EMA(close, ema_period)
    Upper  = Center + multiplier * ATR(atr_period)
    Lower  = Center - multiplier * ATR(atr_period)
    Bloomberg defaults: EMA 20, ATR 10, multiplier 2.
    Returns (upper, mid, lower).
    """
    mid   = ema(close, ema_period)
    atr_v = atr(high, low, close, atr_period)
    upper = mid + multiplier * atr_v
    lower = mid - multiplier * atr_v
    return upper, mid, lower


# ── Donchian Channels ─────────────────────────────────────────────────────────
def donchian_channels(high: np.ndarray, low: np.ndarray, period: int = 20):
    """
    Donchian Channels.
    Upper = rolling max high over period
    Lower = rolling min low over period
    Mid   = (upper + lower) / 2
    Bloomberg default period = 20.
    Returns (upper, mid, lower).
    """
    upper = pd.Series(high).rolling(period).max().values
    lower = pd.Series(low).rolling(period).min().values
    mid   = (upper + lower) / 2.0
    return upper, mid, lower


# ── Historical Volatility ─────────────────────────────────────────────────────
def historical_volatility(close: np.ndarray, period: int = 20) -> np.ndarray:
    """
    HV = std(log returns, period) * sqrt(252) * 100
    Returns annualized % volatility.
    Bloomberg default period = 20.
    """
    n = len(close)
    if n < 2:
        return np.full(n, np.nan)
    close_s = pd.Series(close, dtype=float)
    close_s[close_s <= 0] = np.nan
    log_ret = np.log(close_s / close_s.shift(1))
    hv = log_ret.rolling(period, min_periods=period).std(ddof=1) * np.sqrt(252.0) * 100.0
    return hv.values


# ── BB / Keltner Squeeze ──────────────────────────────────────────────────────
def bb_keltner_squeeze(bb_upper: np.ndarray, bb_lower: np.ndarray,
                       kc_upper: np.ndarray, kc_lower: np.ndarray) -> np.ndarray:
    """
    Squeeze = True where BB is INSIDE KC.
    Condition: bb_upper < kc_upper AND bb_lower > kc_lower.
    Returns bool array (True = squeeze on).
    """
    squeeze = (bb_upper < kc_upper) & (bb_lower > kc_lower)
    return squeeze


# ── Apply indicators to DataFrame ─────────────────────────────────────────────
def apply_indicators(df: pd.DataFrame, active_filters: list) -> pd.DataFrame:
    """
    Compute and attach indicator columns to df in-place based on active_filters.
    Always computes ATR (used for backtesting stats).

    Callers must pass the full OHLC history DataFrame (not a pre-sliced chart
    window). EMA/SMA columns (including ema200 / sma200) are computed from the
    entire close series so values exist wherever sufficient lookback is
    available; running the same helpers on a short slice alone would leave
    long-period MAs all-NaN in that slice.

    Returns df with added columns.
    """
    close  = df["close"].to_numpy(dtype=float)
    high   = df["high"].to_numpy(dtype=float)
    low    = df["low"].to_numpy(dtype=float)

    # ATR always (needed for stats / backtest)
    df["atr"] = atr(high, low, close, 14)

    # ── Bollinger Bands (needed for bb, bb_width, squeeze) ──
    _bb_computed = False
    _bb_upper = _bb_mid = _bb_lower = None

    def _ensure_bb():
        nonlocal _bb_computed, _bb_upper, _bb_mid, _bb_lower
        if not _bb_computed:
            _bb_upper, _bb_mid, _bb_lower = bollinger_bands(close, 20, 2.0)
            df["bb_upper"] = _bb_upper
            df["bb_mid"]   = _bb_mid
            df["bb_lower"] = _bb_lower
            _bb_computed = True

    if "bb" in active_filters or "bb_width" in active_filters or "squeeze" in active_filters:
        _ensure_bb()
        if "bb_width" in active_filters:
            df["bb_width"] = bb_width(_bb_upper, _bb_mid, _bb_lower)

    if "rsi" in active_filters:
        df["rsi"] = rsi(close, 14)

    if "macd" in active_filters:
        ml, sl, hist = macd(close, 12, 26, 9)
        df["macd"]        = ml
        df["macd_signal"] = sl
        df["macd_hist"]   = hist

    # Legacy "ema" key → ema20 (backward compat)
    if "ema" in active_filters:
        df["ema20"] = ema(close, 20)

    # Individual EMA keys
    if "ema9" in active_filters:
        df["ema9"] = ema(close, 9)
    if "ema20" in active_filters:
        df["ema20"] = ema(close, 20)
    if "ema50" in active_filters:
        df["ema50"] = ema(close, 50)
    if "ema200" in active_filters:
        df["ema200"] = ema(close, 200)

    # SMA keys
    if "sma10" in active_filters:
        df["sma10"] = sma(close, 10)
    if "sma20" in active_filters:
        df["sma20"] = sma(close, 20)
    if "sma50" in active_filters:
        df["sma50"] = sma(close, 50)
    if "sma200" in active_filters:
        df["sma200"] = sma(close, 200)

    if "stochastic" in active_filters:
        k, d = stochastic(high, low, close)
        df["stoch_k"] = k
        df["stoch_d"] = d

    if "cci" in active_filters:
        df["cci"] = cci(high, low, close)

    if "williams_r" in active_filters:
        df["williams_r"] = williams_r(high, low, close)

    if "atr_ind" in active_filters:
        df["atr_ind"] = atr(high, low, close, 14)

    # Keltner Channels (needed for keltner and squeeze)
    _kc_computed = False
    _kc_upper = _kc_mid = _kc_lower = None

    def _ensure_kc():
        nonlocal _kc_computed, _kc_upper, _kc_mid, _kc_lower
        if not _kc_computed:
            _kc_upper, _kc_mid, _kc_lower = keltner_channels(high, low, close)
            df["kc_upper"] = _kc_upper
            df["kc_mid"]   = _kc_mid
            df["kc_lower"] = _kc_lower
            _kc_computed = True

    if "keltner" in active_filters or "squeeze" in active_filters:
        _ensure_kc()

    if "donchian" in active_filters:
        u, m, l = donchian_channels(high, low)
        df["dc_upper"] = u
        df["dc_mid"]   = m
        df["dc_lower"] = l

    if "hist_vol" in active_filters:
        df["hist_vol"] = historical_volatility(close)

    if "squeeze" in active_filters:
        _ensure_bb()
        _ensure_kc()
        df["squeeze"] = bb_keltner_squeeze(_bb_upper, _bb_lower, _kc_upper, _kc_lower)

    if "volume_spike" in active_filters and "volume" in df.columns:
        vol = df["volume"].to_numpy(dtype=float)
        df["volume_spike"] = volume_spike(vol, 20, 2.0)

    return df


# ── Indicator-based signals (equity curve when no candlestick patterns) ─────
# (filter_key, column_name, period) — period for sort order (fast → slow)
_MA_FILTER_META = (
    ("ema9", "ema9", 9),
    ("ema20", "ema20", 20),
    ("ema", "ema20", 20),
    ("ema50", "ema50", 50),
    ("ema200", "ema200", 200),
    ("sma10", "sma10", 10),
    ("sma20", "sma20", 20),
    ("sma50", "sma50", 50),
    ("sma200", "sma200", 200),
)


def _selected_ma_columns(df: pd.DataFrame, active_filters: list) -> list[tuple[str, int]]:
    """Unique MA columns among active filters, sorted by period ascending (fastest first)."""
    af = set(active_filters)
    by_col: dict[str, int] = {}
    for fk, col, per in _MA_FILTER_META:
        if fk in af and col in df.columns:
            by_col[col] = per
    return sorted(by_col.items(), key=lambda x: x[1])


def _ma_cross_signals(df: pd.DataFrame, active_filters: list) -> np.ndarray:
    """MA bundle: 1 / 2 / 3 / 4+ MA rules. Returns int8 length n."""
    n = len(df)
    out = np.zeros(n, dtype=np.int8)
    cols = _selected_ma_columns(df, active_filters)
    if cols:
        close = df["close"].to_numpy(dtype=float)

        if len(cols) == 1:
            col, _ = cols[0]
            ma = df[col].to_numpy(dtype=float)
            for i in range(1, n):
                if not (
                    np.isfinite(close[i - 1])
                    and np.isfinite(close[i])
                    and np.isfinite(ma[i - 1])
                    and np.isfinite(ma[i])
                ):
                    continue
                if close[i - 1] <= ma[i - 1] and close[i] > ma[i]:
                    out[i] = 1
                elif close[i - 1] >= ma[i - 1] and close[i] < ma[i]:
                    out[i] = -1

        elif len(cols) == 2:
            fc, _ = cols[0]
            sc, _ = cols[1]
            f = df[fc].to_numpy(dtype=float)
            s = df[sc].to_numpy(dtype=float)
            for i in range(1, n):
                d0 = f[i - 1] - s[i - 1]
                d1 = f[i] - s[i]
                if not all(map(np.isfinite, (d0, d1))):
                    continue
                if d0 <= 0.0 and d1 > 0.0:
                    out[i] = 1
                elif d0 >= 0.0 and d1 < 0.0:
                    out[i] = -1

        elif len(cols) == 3:
            fc, _ = cols[0]
            mc, _ = cols[1]
            sc, _ = cols[2]
            f = df[fc].to_numpy(dtype=float)
            m = df[mc].to_numpy(dtype=float)
            s = df[sc].to_numpy(dtype=float)
            for i in range(1, n):
                d0 = f[i - 1] - s[i - 1]
                d1 = f[i] - s[i]
                if not all(map(np.isfinite, (d0, d1, close[i], m[i]))):
                    continue
                if d0 <= 0.0 and d1 > 0.0:
                    if close[i] > m[i]:
                        out[i] = 1
                elif d0 >= 0.0 and d1 < 0.0:
                    if close[i] < m[i]:
                        out[i] = -1

        else:
            # 4+ MAs: fastest vs slowest cross; majority of middle MAs confirm
            fc, _ = cols[0]
            sc, _ = cols[-1]
            mid_cols = [c for c, _ in cols[1:-1]]
            f = df[fc].to_numpy(dtype=float)
            s = df[sc].to_numpy(dtype=float)
            mid_arr = [df[c].to_numpy(dtype=float) for c in mid_cols]
            n_mid = len(mid_arr)
            need = n_mid // 2 + 1 if n_mid else 0
            for i in range(1, n):
                d0 = f[i - 1] - s[i - 1]
                d1 = f[i] - s[i]
                if not all(map(np.isfinite, (d0, d1, close[i]))):
                    continue
                if d0 <= 0.0 and d1 > 0.0:
                    if n_mid == 0:
                        out[i] = 1
                    else:
                        ok = sum(
                            1
                            for arr in mid_arr
                            if np.isfinite(arr[i]) and close[i] > arr[i]
                        )
                        if ok >= need:
                            out[i] = 1
                elif d0 >= 0.0 and d1 < 0.0:
                    if n_mid == 0:
                        out[i] = -1
                    else:
                        ok = sum(
                            1
                            for arr in mid_arr
                            if np.isfinite(arr[i]) and close[i] < arr[i]
                        )
                        if ok >= need:
                            out[i] = -1

    return out


def _and_combine_signals(arrs: list[np.ndarray]) -> np.ndarray:
    """Require every producer to agree (+1 or -1); any zero or mismatch → 0."""
    if not arrs:
        return np.array([], dtype=np.int8)
    n = len(arrs[0])
    ref = arrs[0].astype(np.int32, copy=True)
    for a in arrs[1:]:
        a = a.astype(np.int32, copy=False)
        ref = np.where((ref != 0) & (a != 0) & (ref == a), ref, 0)
    return ref.astype(np.int8)


def _confirmation_mask(df: pd.DataFrame, active_filters: list, n: int) -> np.ndarray:
    """
    Bars where non-directional filters pass (all selected confirmations must pass).
    If a confirmation column is missing, that check is skipped (pass).
    """
    ok = np.ones(n, dtype=bool)
    af = set(active_filters)
    if "volume_spike" in af and "volume_spike" in df.columns:
        vs = df["volume_spike"].to_numpy(dtype=float)
        ok &= np.isfinite(vs) & (vs == 1.0)
    if "bb_width" in af and "bb_width" in df.columns:
        bw = df["bb_width"].to_numpy(dtype=float)
        ok &= np.isfinite(bw) & (bw > 0.0)
    if "hist_vol" in af and "hist_vol" in df.columns:
        hv = df["hist_vol"].to_numpy(dtype=float)
        ok &= np.isfinite(hv)
    return ok


def generate_indicator_signals(df: pd.DataFrame, active_filters: list) -> pd.Series:
    """
    Build per-bar directional signals (+1 / -1 / 0) from selected indicators.

    MA: 1 MA = close×MA cross; 2 = fast×slow cross; 3 = fast×slow + middle filter;
        4+ = fast×slow + majority of middle MAs confirm.
    Momentum / volatility: per spec (RSI, MACD, Stoch, Williams, CCI, BB bands,
    Keltner, Donchian, squeeze breakout).
    bb_width, hist_vol, volume_spike: confirmations only (AND on the signal bar).

    Multiple directional indicators use AND logic (all must agree on direction).
    Returns a Series aligned to df.index (int8).
    """
    n = len(df)
    if n == 0:
        return pd.Series([], dtype=np.int8)

    af = list(active_filters)
    producers: list[np.ndarray] = []

    af_set = set(af)
    if any(fk in af_set for fk, _, _ in _MA_FILTER_META):
        producers.append(_ma_cross_signals(df, af))

    if "rsi" in af and "rsi" in df.columns:
        r = df["rsi"].to_numpy(dtype=float)
        s = np.zeros(n, dtype=np.int8)
        for i in range(1, n):
            if not (np.isfinite(r[i - 1]) and np.isfinite(r[i])):
                continue
            if r[i - 1] <= 30.0 and r[i] > 30.0:
                s[i] = 1
            elif r[i - 1] >= 70.0 and r[i] < 70.0:
                s[i] = -1
        producers.append(s)

    if "macd" in af and "macd" in df.columns and "macd_signal" in df.columns:
        m = df["macd"].to_numpy(dtype=float)
        sig = df["macd_signal"].to_numpy(dtype=float)
        s = np.zeros(n, dtype=np.int8)
        for i in range(1, n):
            if not all(map(np.isfinite, (m[i - 1], m[i], sig[i - 1], sig[i]))):
                continue
            if m[i - 1] <= sig[i - 1] and m[i] > sig[i]:
                s[i] = 1
            elif m[i - 1] >= sig[i - 1] and m[i] < sig[i]:
                s[i] = -1
        producers.append(s)

    if "stochastic" in af and "stoch_k" in df.columns and "stoch_d" in df.columns:
        k = df["stoch_k"].to_numpy(dtype=float)
        d = df["stoch_d"].to_numpy(dtype=float)
        s = np.zeros(n, dtype=np.int8)
        for i in range(1, n):
            if not all(map(np.isfinite, (k[i - 1], k[i], d[i - 1], d[i]))):
                continue
            if k[i - 1] <= d[i - 1] and k[i] > d[i]:
                if k[i] < 20.0 and d[i] < 20.0:
                    s[i] = 1
            elif k[i - 1] >= d[i - 1] and k[i] < d[i]:
                if k[i] > 80.0 and d[i] > 80.0:
                    s[i] = -1
        producers.append(s)

    if "williams_r" in af and "williams_r" in df.columns:
        w = df["williams_r"].to_numpy(dtype=float)
        s = np.zeros(n, dtype=np.int8)
        for i in range(1, n):
            if not (np.isfinite(w[i - 1]) and np.isfinite(w[i])):
                continue
            if w[i - 1] < -80.0 and w[i] >= -80.0:
                s[i] = 1
            elif w[i - 1] > -20.0 and w[i] <= -20.0:
                s[i] = -1
        producers.append(s)

    if "cci" in af and "cci" in df.columns:
        c = df["cci"].to_numpy(dtype=float)
        s = np.zeros(n, dtype=np.int8)
        for i in range(1, n):
            if not (np.isfinite(c[i - 1]) and np.isfinite(c[i])):
                continue
            if c[i - 1] <= -100.0 and c[i] > -100.0:
                s[i] = 1
            elif c[i - 1] >= 100.0 and c[i] < 100.0:
                s[i] = -1
        producers.append(s)

    if "bb" in af and "bb_upper" in df.columns and "bb_lower" in df.columns:
        c = df["close"].to_numpy(dtype=float)
        u = df["bb_upper"].to_numpy(dtype=float)
        lo = df["bb_lower"].to_numpy(dtype=float)
        s = np.zeros(n, dtype=np.int8)
        for i in range(1, n):
            if not all(map(np.isfinite, (c[i - 1], c[i], u[i - 1], u[i], lo[i - 1], lo[i]))):
                continue
            if c[i - 1] <= lo[i - 1] and c[i] > lo[i]:
                s[i] = 1
            elif c[i - 1] >= u[i - 1] and c[i] < u[i]:
                s[i] = -1
        producers.append(s)

    if "keltner" in af and "kc_upper" in df.columns and "kc_lower" in df.columns:
        c = df["close"].to_numpy(dtype=float)
        u = df["kc_upper"].to_numpy(dtype=float)
        lo = df["kc_lower"].to_numpy(dtype=float)
        s = np.zeros(n, dtype=np.int8)
        for i in range(1, n):
            if not all(map(np.isfinite, (c[i - 1], c[i], u[i - 1], u[i], lo[i - 1], lo[i]))):
                continue
            if c[i - 1] <= u[i - 1] and c[i] > u[i]:
                s[i] = 1
            elif c[i - 1] >= lo[i - 1] and c[i] < lo[i]:
                s[i] = -1
        producers.append(s)

    if "donchian" in af and "dc_upper" in df.columns and "dc_lower" in df.columns:
        c = df["close"].to_numpy(dtype=float)
        u = df["dc_upper"].to_numpy(dtype=float)
        lo = df["dc_lower"].to_numpy(dtype=float)
        s = np.zeros(n, dtype=np.int8)
        for i in range(1, n):
            if not all(map(np.isfinite, (c[i - 1], c[i], u[i - 1], u[i], lo[i - 1], lo[i]))):
                continue
            if c[i - 1] <= u[i - 1] and c[i] > u[i]:
                s[i] = 1
            elif c[i - 1] >= lo[i - 1] and c[i] < lo[i]:
                s[i] = -1
        producers.append(s)

    if "squeeze" in af and "squeeze" in df.columns:
        sq = df["squeeze"].to_numpy()
        c = df["close"].to_numpy(dtype=float)
        mid = None
        if "kc_mid" in df.columns:
            mid = df["kc_mid"].to_numpy(dtype=float)
        elif "bb_mid" in df.columns:
            mid = df["bb_mid"].to_numpy(dtype=float)
        s = np.zeros(n, dtype=np.int8)
        if mid is not None:
            for i in range(1, n):
                sp, sn = sq[i - 1], sq[i]
                on_prev = bool(sp) if pd.notna(sp) else False
                on_now = bool(sn) if pd.notna(sn) else False
                if on_prev and not on_now and np.isfinite(c[i]) and np.isfinite(mid[i]):
                    if c[i] > mid[i]:
                        s[i] = 1
                    elif c[i] < mid[i]:
                        s[i] = -1
        producers.append(s)

    if not producers:
        return pd.Series(np.zeros(n, dtype=np.int8), index=df.index, dtype=np.int8)

    combined = _and_combine_signals(producers)
    conf = _confirmation_mask(df, af, n)
    combined = np.where(conf, combined, 0).astype(np.int8)
    return pd.Series(combined, index=df.index, dtype=np.int8)
