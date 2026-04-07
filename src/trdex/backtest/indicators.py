"""Technical indicators computed on polars DataFrames."""

from __future__ import annotations

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
