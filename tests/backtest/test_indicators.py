"""Tests for technical indicators and backtest engine."""

from __future__ import annotations

import polars as pl
import pytest

from trdex.backtest.engine import BacktestResult, run_backtest
from trdex.backtest.indicators import add_indicators, bollinger_bands, macd, rsi


def _make_ohlcv(n: int = 60, start_price: float = 100.0, trend: float = 0.5) -> pl.DataFrame:
    """Generate synthetic OHLCV data with a gentle trend."""
    closes = [start_price + i * trend for i in range(n)]
    return pl.DataFrame({
        "timestamp": list(range(n)),
        "open": [c - 0.5 for c in closes],
        "high": [c + 1.0 for c in closes],
        "low": [c - 1.0 for c in closes],
        "close": closes,
        "volume": [1000.0] * n,
    })


# ── Indicator tests ───────────────────────────────────────────────────────────

def test_rsi_length_matches_input() -> None:
    df = _make_ohlcv(50)
    result = rsi(df, period=14)
    assert len(result) == len(df)


def test_rsi_range() -> None:
    df = _make_ohlcv(50)
    result = rsi(df, period=14).drop_nulls()
    assert result.min() >= 0.0
    assert result.max() <= 100.0


def test_macd_columns() -> None:
    df = _make_ohlcv(60)
    result = macd(df)
    assert "macd" in result.columns
    assert "macd_signal" in result.columns
    assert "macd_hist" in result.columns
    assert len(result) == len(df)


def test_bollinger_bands_upper_above_lower() -> None:
    df = _make_ohlcv(60)
    result = bollinger_bands(df)
    valid = result.drop_nulls()
    assert (valid["bb_upper"] >= valid["bb_lower"]).all()


def test_add_indicators_columns() -> None:
    df = _make_ohlcv(60)
    enriched = add_indicators(df)
    for col in ["rsi", "macd", "macd_signal", "macd_hist", "bb_upper", "bb_mid", "bb_lower"]:
        assert col in enriched.columns


# ── Backtest engine tests ─────────────────────────────────────────────────────

class _AlwaysBuyStrategy:
    def generate_signals(self, df: pl.DataFrame) -> pl.Series:
        return pl.Series("signal", [1] + [0] * (len(df) - 1))


class _SmaCrossStrategy:
    """Buy when SMA9 > SMA21, sell otherwise."""
    def generate_signals(self, df: pl.DataFrame) -> pl.Series:
        sma_fast = df["close"].rolling_mean(9)
        sma_slow = df["close"].rolling_mean(21)
        sigs = []
        prev = 0
        for f, s in zip(sma_fast.to_list(), sma_slow.to_list()):
            if f is None or s is None:
                sigs.append(0)
            elif f > s and prev != 1:
                sigs.append(1)
                prev = 1
            elif f <= s and prev != -1:
                sigs.append(-1)
                prev = -1
            else:
                sigs.append(0)
        return pl.Series("signal", sigs)


def test_backtest_returns_result() -> None:
    df = _make_ohlcv(60)
    result = run_backtest(df, _AlwaysBuyStrategy(), symbol="TEST/USDT")
    assert isinstance(result, BacktestResult)
    assert result.symbol == "TEST/USDT"
    assert result.initial_capital == 10_000.0
    assert len(result.equity_curve) == len(df)


def test_backtest_uptrend_positive_return() -> None:
    df = _make_ohlcv(100, trend=1.0)  # strong uptrend
    result = run_backtest(df, _SmaCrossStrategy(), symbol="UP/USDT")
    assert result.total_return_pct >= 0


def test_backtest_equity_curve_length() -> None:
    df = _make_ohlcv(60)
    result = run_backtest(df, _SmaCrossStrategy())
    assert len(result.equity_curve) == len(df)


def test_backtest_max_drawdown_non_negative() -> None:
    df = _make_ohlcv(60)
    result = run_backtest(df, _SmaCrossStrategy())
    assert result.max_drawdown_pct >= 0
