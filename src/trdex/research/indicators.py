"""Pure-function technical indicators over list[float].

Returns list[float | None] matching input length, with None for warmup
bars. Designed to be indexable bar-by-bar by the backtest engine — no
polars/pandas dependency here.

Wilder smoothing is the TradingView/Bloomberg/MetaTrader standard and
matches the formula in src/trdex/backtest/indicators.py (alpha = 1/period).
"""

from __future__ import annotations

from statistics import pstdev


def wilder_rsi(closes: list[float], period: int = 14) -> list[float | None]:
    n = len(closes)
    if n < period + 1:
        return [None] * n

    deltas = [0.0] + [closes[i] - closes[i - 1] for i in range(1, n)]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_gain: list[float | None] = [None] * n
    avg_loss: list[float | None] = [None] * n
    # Seed: simple mean of first `period` deltas (index 1..period inclusive)
    avg_gain[period] = sum(gains[1:period + 1]) / period
    avg_loss[period] = sum(losses[1:period + 1]) / period

    alpha = 1.0 / period
    for i in range(period + 1, n):
        avg_gain[i] = (1 - alpha) * avg_gain[i - 1] + alpha * gains[i]
        avg_loss[i] = (1 - alpha) * avg_loss[i - 1] + alpha * losses[i]

    out: list[float | None] = []
    for i in range(n):
        g, l = avg_gain[i], avg_loss[i]
        if g is None or l is None:
            out.append(None)
        elif l == 0:
            out.append(100.0)
        else:
            rs = g / l
            out.append(100 - (100 / (1 + rs)))
    return out


def sma(values: list[float], period: int) -> list[float | None]:
    n = len(values)
    out: list[float | None] = [None] * n
    if n < period:
        return out
    # Rolling window sum
    window_sum = sum(values[:period])
    out[period - 1] = window_sum / period
    for i in range(period, n):
        window_sum += values[i] - values[i - period]
        out[i] = window_sum / period
    return out


def bollinger_bands(
    closes: list[float],
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    n = len(closes)
    upper: list[float | None] = [None] * n
    mid: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    if n < period:
        return upper, mid, lower
    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        m = sum(window) / period
        s = pstdev(window)
        mid[i] = m
        upper[i] = m + std_dev * s
        lower[i] = m - std_dev * s
    return upper, mid, lower


def volume_ma(volumes: list[float], period: int = 24) -> list[float | None]:
    return sma(volumes, period)


def is_squeezing(
    closes: list[float],
    bb_period: int = 20,
    std_dev: float = 2.0,
    lookback: int = 100,
    pct: float = 0.3,
) -> list[bool]:
    """True when the current BB width is in the bottom `pct` of widths
    over the last `lookback` bars. Warmup bars (insufficient history) = False.
    """
    n = len(closes)
    upper, _, lower = bollinger_bands(closes, period=bb_period, std_dev=std_dev)
    widths: list[float | None] = [
        (u - l) if (u is not None and l is not None) else None
        for u, l in zip(upper, lower)
    ]
    out = [False] * n
    for i in range(n):
        if widths[i] is None or i < bb_period + lookback - 1:
            continue
        window = [w for w in widths[i - lookback + 1:i + 1] if w is not None]
        if not window:
            continue
        threshold = sorted(window)[int(len(window) * pct)]
        if widths[i] <= threshold:
            out[i] = True
    return out
