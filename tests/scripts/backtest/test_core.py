"""Unit tests for the backtest core engine and helpers."""

from __future__ import annotations

from scripts.backtest.core import (
    BacktestResult,
    aggregate_1h_to_1d,
    max_drawdown,
    sharpe_ratio,
    split_trades_by_quarter,
)


def test_backtest_result_populated_with_defaults() -> None:
    r = BacktestResult(
        strategy_name="Test",
        final_equity=10_500.0,
        total_pnl=500.0,
        return_pct=5.0,
        trades_count=10,
        wins=6,
        win_rate=0.6,
        sharpe=1.2,
        max_drawdown_pct=3.0,
        exit_reasons={"TP": 6, "SL": 4},
        trades=[],
        per_symbol={},
        per_quarter={},
    )
    assert r.strategy_name == "Test"
    assert r.win_rate == 0.6


def test_max_drawdown_monotonic_up() -> None:
    # No drawdown on a monotone-increasing equity.
    assert max_drawdown([10_000.0, 10_100.0, 10_200.0]) == 0.0


def test_max_drawdown_peak_then_trough() -> None:
    # Peak at 11_000, trough at 9_900 → drawdown = (11_000 - 9_900) / 11_000 = 10%.
    dd = max_drawdown([10_000.0, 11_000.0, 9_900.0, 10_500.0])
    assert abs(dd - 10.0) < 1e-6


def test_sharpe_zero_on_flat_curve() -> None:
    assert sharpe_ratio([10_000.0] * 100, bars_per_year=8760) == 0.0


def test_sharpe_positive_on_uptrend() -> None:
    # Smooth uptrend 1% per bar — high positive Sharpe.
    curve = [10_000.0 * (1.01 ** i) for i in range(50)]
    s = sharpe_ratio(curve, bars_per_year=8760)
    assert s > 0


def test_aggregate_1h_to_1d_groups_24_bars() -> None:
    # Build 48 hours of synthetic 1h bars (ts_ms is the bar's open time in UTC).
    # First 24 bars = one day, next 24 = second day.
    hour_ms = 3_600_000
    day0_start = 0  # 1970-01-01 00:00 UTC
    bars = []
    for i in range(48):
        ts = day0_start + i * hour_ms
        # open=i, high=i+1, low=i-1, close=i+0.5, volume=i
        bars.append([ts, float(i), float(i + 1), float(i - 1), float(i) + 0.5, float(i)])

    daily = aggregate_1h_to_1d(bars)
    assert len(daily) == 2
    # Day 0: open=bar0.open=0, high=max(bar0..23.high)=24, low=min(bar0..23.low)=-1, close=bar23.close=23.5, vol=sum(0..23)=276
    assert daily[0][1] == 0.0        # open
    assert daily[0][2] == 24.0       # high
    assert daily[0][3] == -1.0       # low
    assert daily[0][4] == 23.5       # close
    assert daily[0][5] == sum(range(24))   # volume
    # Day 1: open=bar24.open=24, close=bar47.close=47.5
    assert daily[1][1] == 24.0
    assert daily[1][4] == 47.5


def test_split_trades_by_quarter_four_buckets() -> None:
    # 8 trades, 2 per quarter, spread over 365 days.
    day_ms = 24 * 3_600_000
    trades = []
    for q in range(4):
        for i in range(2):
            trades.append({"entry_ts": (q * 91 + i) * day_ms, "net_pnl": 1.0})

    buckets = split_trades_by_quarter(trades)
    assert set(buckets.keys()) == {"Q1", "Q2", "Q3", "Q4"}
    assert len(buckets["Q1"]) == 2
    assert len(buckets["Q4"]) == 2


def test_split_trades_empty_returns_empty() -> None:
    assert split_trades_by_quarter([]) == {}


from scripts.backtest.core import EngineParams, Strategy, run_backtest


class NoopStrategy:
    """Always returns HOLD. For engine-skeleton tests."""
    name = "Noop"
    timeframe = "1h"

    def generate_signal(self, bar_index, candles, indicators, position_state):
        return "HOLD"


def test_engine_returns_result_on_hold_only_strategy() -> None:
    # 100 bars of synthetic 1h OHLCV, flat price.
    bars = [[i * 3_600_000, 100.0, 100.1, 99.9, 100.0, 10.0] for i in range(100)]
    ohlcv = {"BTC/USDT": bars}

    result = run_backtest(
        strategy=NoopStrategy(),
        ohlcv_by_symbol=ohlcv,
        params=EngineParams(),
    )
    # No trades, equity unchanged.
    assert result.trades_count == 0
    assert result.total_pnl == 0.0
    assert result.final_equity == 10_000.0


def test_engine_params_defaults() -> None:
    p = EngineParams()
    assert p.initial_equity == 10_000.0
    assert p.position_size_pct == 0.05
    assert p.fee_pct == 0.001
    assert p.sl_pct == 0.02
    assert p.tp_pct == 0.04
    assert p.trail_pct == 0.015
