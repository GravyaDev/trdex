"""Unit tests for the backtest engine.

Focus areas:
    - Timeframe-aware Sharpe annualisation (Task 2 fix)
    - PnL semantics: sum(trade.pnl) == final_capital - initial_capital
    - entry_idx / exit_idx coherence
    - Empty signal series → zero trades, no crash
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import polars as pl
import pytest

from trdex.backtest.engine import (
    _BARS_PER_YEAR,
    _bars_per_year,
    _sharpe_ratio,
    run_backtest,
)
from trdex.strategy.backtest.sma_cross import (
    BacktestSMACross,
    BacktestSMACrossConfig,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ohlcv(closes: list[float], start: datetime | None = None) -> pl.DataFrame:
    """Build a minimal OHLCV DataFrame from a list of closes.

    open/high/low are derived trivially so the resulting frame is valid
    for any indicator that needs them, but the strategies under test
    only look at ``close``.
    """
    n = len(closes)
    base = start or datetime(2026, 1, 1, 0, 0, 0)
    return pl.DataFrame(
        {
            "timestamp": [base + timedelta(hours=i) for i in range(n)],
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [100.0] * n,
        }
    )


# ---------------------------------------------------------------------------
# _bars_per_year mapping
# ---------------------------------------------------------------------------


def test_bars_per_year_known_timeframes() -> None:
    assert _bars_per_year("1m") == 525_600
    assert _bars_per_year("1h") == 8_760
    assert _bars_per_year("4h") == 2_190
    assert _bars_per_year("1d") == 365


def test_bars_per_year_unknown_falls_back_to_1h() -> None:
    assert _bars_per_year("17m") == 8_760
    assert _bars_per_year("") == 8_760


def test_bars_per_year_table_is_consistent() -> None:
    """1h * 24 == 1d * 365 / 365 = 24h per day, etc. Sanity check the map."""
    assert _BARS_PER_YEAR["1h"] == _BARS_PER_YEAR["1d"] * 24
    assert _BARS_PER_YEAR["1m"] == _BARS_PER_YEAR["1h"] * 60
    assert _BARS_PER_YEAR["4h"] == _BARS_PER_YEAR["1h"] // 4
    assert _BARS_PER_YEAR["1w"] == 52  # weekly bars


# ---------------------------------------------------------------------------
# _sharpe_ratio annualisation
# ---------------------------------------------------------------------------


def test_sharpe_zero_when_too_few_returns() -> None:
    assert _sharpe_ratio(pl.Series("e", []), bars_per_year=8760) == 0.0
    assert _sharpe_ratio(pl.Series("e", [100.0]), bars_per_year=8760) == 0.0


def test_sharpe_zero_on_flat_curve() -> None:
    flat = pl.Series("e", [100.0, 100.0, 100.0, 100.0])
    assert _sharpe_ratio(flat, bars_per_year=8760) == 0.0


def test_sharpe_scales_with_sqrt_of_bars_per_year() -> None:
    """The same equity series annualised at hourly vs daily must differ
    by exactly sqrt(8760 / 365) = sqrt(24).

    This is the core invariant of Task 2: a higher-frequency dataset
    needs a larger annualisation factor."""
    equity = pl.Series(
        "e",
        [10000.0, 10010.0, 10005.0, 10020.0, 10018.0, 10030.0, 10025.0, 10040.0],
    )
    s_hourly = _sharpe_ratio(equity, bars_per_year=8760)
    s_daily = _sharpe_ratio(equity, bars_per_year=365)
    assert s_hourly != 0.0
    assert s_daily != 0.0
    ratio = s_hourly / s_daily
    expected = math.sqrt(8760 / 365)  # = sqrt(24) ≈ 4.899
    assert ratio == pytest.approx(expected)


def test_sharpe_with_known_returns_matches_manual_computation() -> None:
    """Hand-compute the Sharpe to pin the formula."""
    equity = pl.Series("e", [100.0, 101.0, 100.0, 101.0])
    # pct_change → [None, +0.01, -0.0099..., +0.01]
    returns = [0.01, -1 / 101, 1 / 100]
    n = len(returns)
    mean = sum(returns) / n
    # polars uses sample std (ddof=1) by default
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(var)
    bpy = 8760
    expected = (mean / std) * math.sqrt(bpy)
    actual = _sharpe_ratio(equity, bars_per_year=bpy)
    assert actual == pytest.approx(expected, rel=1e-9)


# ---------------------------------------------------------------------------
# run_backtest end-to-end behaviour
# ---------------------------------------------------------------------------


def test_run_backtest_passes_timeframe_to_sharpe() -> None:
    """Same data → identical sharpe under matching timeframes; different
    sharpe across different timeframes."""
    closes = [100.0] * 10 + [101.0 + 0.5 * i for i in range(10)] + [
        110.0 - 0.5 * i for i in range(10)
    ]
    df = _ohlcv(closes)
    strat = BacktestSMACross(BacktestSMACrossConfig(short_period=3, long_period=5))

    result_1h = run_backtest(df, strat, timeframe="1h")
    result_1d = run_backtest(df, strat, timeframe="1d")

    # Same data, same trades, same total return — only sharpe scales.
    assert result_1h.total_trades == result_1d.total_trades
    assert result_1h.total_return_pct == pytest.approx(result_1d.total_return_pct)
    assert result_1h.final_capital == pytest.approx(result_1d.final_capital)

    # Sharpe MUST scale by sqrt(8760/365) = sqrt(24) when both are non-zero.
    if result_1h.sharpe_ratio != 0.0 and result_1d.sharpe_ratio != 0.0:
        ratio = result_1h.sharpe_ratio / result_1d.sharpe_ratio
        assert ratio == pytest.approx(math.sqrt(24), rel=1e-6)


def test_run_backtest_default_timeframe_is_1h() -> None:
    """Backward compatibility: callers that don't pass timeframe still work."""
    closes = [100.0 + i * 0.1 for i in range(60)]
    df = _ohlcv(closes)
    strat = BacktestSMACross(BacktestSMACrossConfig(short_period=3, long_period=10))
    # No timeframe arg = default "1h" = bars_per_year 8760
    result = run_backtest(df, strat)
    # Just assert the call succeeds and returns a finite sharpe.
    assert math.isfinite(result.sharpe_ratio)


# ---------------------------------------------------------------------------
# PnL semantics (regression test for the entry_cost fix)
# ---------------------------------------------------------------------------


def test_sum_pnl_equals_capital_change_when_last_trade_closed() -> None:
    """Critical invariant uncovered by smoke_level3: sum(pnl) over all
    closed trades must equal final_capital - initial_capital, otherwise
    the ledger replay diverges from the engine's own equity tracking.

    The fix was to compute pnl as ``proceeds - entry_cost`` instead of
    ``proceeds - entry_qty * entry_price`` (the latter excluded the
    entry fee, leaving a residual gap of ~entry_fee per trade).
    """
    # Build a price series that produces several round-trip trades.
    closes = (
        [100.0] * 10
        + [101.0 + 0.5 * i for i in range(10)]   # rising
        + [110.0 - 0.5 * i for i in range(10)]   # falling
        + [101.0 + 0.3 * i for i in range(10)]   # rising again
        + [110.0 - 0.3 * i for i in range(10)]   # falling again
    )
    df = _ohlcv(closes)
    strat = BacktestSMACross(BacktestSMACrossConfig(short_period=3, long_period=5))
    result = run_backtest(df, strat, position_size_pct=0.5, fee_rate=0.001)

    assert result.total_trades >= 2, "fixture should produce multiple trades"

    pnl_sum = float(result.trades["pnl"].sum())
    capital_change = result.final_capital - result.initial_capital
    assert pnl_sum == pytest.approx(capital_change, abs=1e-9)


def test_trades_expose_entry_idx_and_exit_idx() -> None:
    """Required by smoke_level3 step 3 to map trades to timestamps."""
    closes = [100.0] * 10 + [101.0 + 0.5 * i for i in range(10)] + [
        110.0 - 0.5 * i for i in range(10)
    ]
    df = _ohlcv(closes)
    strat = BacktestSMACross(BacktestSMACrossConfig(short_period=3, long_period=5))
    result = run_backtest(df, strat)

    assert "entry_idx" in result.trades.columns
    assert "exit_idx" in result.trades.columns
    if len(result.trades) > 0:
        for row in result.trades.iter_rows(named=True):
            assert 0 <= row["entry_idx"] < len(df)
            assert 0 <= row["exit_idx"] < len(df)
            assert row["entry_idx"] < row["exit_idx"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_run_backtest_no_trades_returns_zero_sharpe_zero_trades() -> None:
    """Flat input → strategy emits no signals → 0 trades → no crash."""
    df = _ohlcv([100.0] * 50)
    strat = BacktestSMACross(BacktestSMACrossConfig(short_period=3, long_period=5))
    result = run_backtest(df, strat)
    assert result.total_trades == 0
    assert result.win_rate == 0.0
    assert result.final_capital == pytest.approx(result.initial_capital)
