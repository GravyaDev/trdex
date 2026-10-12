"""Technical indicators computed on polars DataFrames.

Also exposes lightweight list-based helpers (``sma_from_list``,
``classify_volatility``, ``volume_ratio``) used by agents and the
market-episode generator — no Polars dependency for those.
"""

from __future__ import annotations

import statistics

import polars as pl


def rsi(df: pl.DataFrame, period: int = 14, col: str = "close") -> pl.Series:
    """Relative Strength Index — Wilder smoothing (α = 1/period).

    Matches TradingView, Bloomberg, and all standard institutional platforms.
    Use this when comparing signals with external data or calibrating thresholds
    on historical datasets.

    Returns a Series of the same length as df (first `period` rows are null).
    """
    delta = df[col].diff()
    gain = delta.clip(lower_bound=0)
    loss = (-delta).clip(lower_bound=0)

    # Wilder smoothing: α = 1/period, equivalent to EWM with com=period-1
    avg_gain = gain.ewm_mean(com=period - 1, adjust=False)
    avg_loss = loss.ewm_mean(com=period - 1, adjust=False)

    rs = avg_gain / avg_loss
    return (100 - (100 / (1 + rs))).alias("rsi")


def rsi_from_list(closes: list[float], period: int = 14) -> float | None:
    """Compute the most recent RSI value from a list of closing prices.

    Uses the same Wilder EWM smoothing as :func:`rsi`.
    Returns ``None`` if there are fewer than ``period + 1`` data points.
    """
    if len(closes) < period + 1:
        return None
    series = pl.Series("close", closes)
    df = pl.DataFrame({"close": series})
    rsi_series = rsi(df, period=period)
    last = rsi_series[-1]
    return None if last is None else float(last)


def macd(
    df: pl.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    col: str = "close",
) -> pl.DataFrame:
    """MACD line, signal line, and histogram.

    Returns a DataFrame with columns: macd, macd_signal, macd_hist.
    """
    ema_fast = df[col].ewm_mean(span=fast, adjust=False).alias("ema_fast")
    ema_slow = df[col].ewm_mean(span=slow, adjust=False).alias("ema_slow")

    macd_line = (ema_fast - ema_slow).alias("macd")
    signal_line = macd_line.ewm_mean(span=signal, adjust=False).alias("macd_signal")
    hist = (macd_line - signal_line).alias("macd_hist")

    return pl.DataFrame([macd_line, signal_line, hist])


def bollinger_bands(
    df: pl.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
    col: str = "close",
) -> pl.DataFrame:
    """Bollinger Bands: upper, middle (SMA), lower.

    Returns a DataFrame with columns: bb_upper, bb_mid, bb_lower.
    """
    rolling_mean = (
        df[col]
        .rolling_mean(window_size=period)
        .alias("bb_mid")
    )
    rolling_std = (
        df[col]
        .rolling_std(window_size=period)
        .alias("_std")
    )
    upper = (rolling_mean + std_dev * rolling_std).alias("bb_upper")
    lower = (rolling_mean - std_dev * rolling_std).alias("bb_lower")

    return pl.DataFrame([upper, rolling_mean, lower])


# ---------------------------------------------------------------------------
# List-based helpers (no Polars needed — used by agents & episode generator)
# ---------------------------------------------------------------------------


def sma_from_list(closes: list[float], period: int) -> float | None:
    """Simple Moving Average over the last *period* values.

    Returns ``None`` if there are fewer than ``period`` data points.
    """
    if len(closes) < period:
        return None
    return statistics.mean(closes[-period:])


def classify_volatility(closes: list[float], window: int = 20) -> tuple[str, float | None]:
    """Classify recent volatility regime from close prices.

    Returns ``(label, cv)`` where *label* is one of ``"low"``, ``"medium"``,
    ``"high"``, ``"unknown"`` and *cv* is the coefficient of variation
    (``stdev / mean``) or ``None`` when data is insufficient.

    Thresholds: <1% low, 1–3% medium, >3% high.
    """
    segment = closes[-window:] if len(closes) >= window else closes
    if len(segment) < 3:
        return "unknown", None
    mean = statistics.mean(segment)
    if mean == 0:
        return "unknown", None
    cv = statistics.stdev(segment) / mean
    if cv < 0.01:
        return "low", cv
    if cv < 0.03:
        return "medium", cv
    return "high", cv


def volume_ratio(volumes: list[float], window: int = 20) -> float | None:
    """Ratio of most-recent volume to the trailing *window* average.

    Returns ``None`` when there are fewer than ``window + 1`` data points
    (the baseline needs at least *window* values and the current bar is
    compared against it).
    """
    if len(volumes) < window + 1:
        return None
    baseline = statistics.mean(volumes[-(window + 1):-1])
    if baseline == 0:
        return None
    return volumes[-1] / baseline


# ---------------------------------------------------------------------------
# DataFrame-level composite helper
# ---------------------------------------------------------------------------


def add_indicators(
    df: pl.DataFrame,
    rsi_period: int = 14,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    bb_period: int = 20,
    bb_std: float = 2.0,
) -> pl.DataFrame:
    """Add RSI, MACD, and Bollinger Bands columns to an OHLCV DataFrame.

    Input DataFrame must have a 'close' column.
    Returns the enriched DataFrame.
    """
    rsi_series = rsi(df, period=rsi_period)
    macd_df = macd(df, fast=macd_fast, slow=macd_slow, signal=macd_signal)
    bb_df = bollinger_bands(df, period=bb_period, std_dev=bb_std)

    return df.with_columns([
        rsi_series,
        macd_df["macd"],
        macd_df["macd_signal"],
        macd_df["macd_hist"],
        bb_df["bb_upper"],
        bb_df["bb_mid"],
        bb_df["bb_lower"],
    ])
