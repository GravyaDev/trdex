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


class OpenLongOnceStrategy:
    """Issues BUY on bar 5, then HOLD forever."""
    name = "OpenLongOnce"
    timeframe = "1h"

    def generate_signal(self, bar_index, candles, indicators, position_state):
        if bar_index == 5 and position_state == "flat":
            return "BUY"
        return "HOLD"


class BuyOnceSellOnceStrategy:
    """BUY at bar 5, CLOSE_LONG at bar 20."""
    name = "BuyOnceSellOnce"
    timeframe = "1h"

    def generate_signal(self, bar_index, candles, indicators, position_state):
        if bar_index == 5 and position_state == "flat":
            return "BUY"
        if bar_index == 20 and position_state == "long":
            return "CLOSE_LONG"
        return "HOLD"


def _flat_bars(n: int = 50, price: float = 100.0) -> list[list]:
    return [[i * 3_600_000, price, price, price, price, 10.0] for i in range(n)]


def test_long_opens_at_signal_bar_and_stays_open() -> None:
    bars = _flat_bars(30)
    result = run_backtest(OpenLongOnceStrategy(), {"BTC/USDT": bars}, EngineParams())
    # No exit trigger (price is flat, no SL/TP/trail hit, no CLOSE signal) → 0 closed trades.
    assert result.trades_count == 0


def test_long_tp_hit_registers_trade() -> None:
    # Flat until bar 10, then a bar that hits +4% high.
    bars = _flat_bars(30)
    bars[15] = [15 * 3_600_000, 100.0, 104.5, 99.9, 100.0, 10.0]  # TP hit on high
    result = run_backtest(
        OpenLongOnceStrategy(), {"BTC/USDT": bars}, EngineParams()
    )
    assert result.trades_count == 1
    t = result.trades[0]
    assert t["reason"] == "TP"
    # TP at entry*1.04 = 100*1.04 = 104. Net pnl: (104-100)*qty - fees
    assert t["exit_price"] == 104.0
    assert t["net_pnl"] > 0


def test_long_sl_hit_registers_trade() -> None:
    # Bar 10 triggers SL at low = 97 (entry 100, SL 2% → 98).
    bars = _flat_bars(30)
    bars[10] = [10 * 3_600_000, 100.0, 100.1, 97.0, 100.0, 10.0]
    result = run_backtest(
        OpenLongOnceStrategy(), {"BTC/USDT": bars}, EngineParams()
    )
    assert result.trades_count == 1
    t = result.trades[0]
    assert t["reason"] == "SL"
    assert t["exit_price"] == 98.0  # SL at entry * (1 - 0.02)
    assert t["net_pnl"] < 0


def test_long_close_signal_exits_at_next_open() -> None:
    bars = _flat_bars(30)
    # Bar 20 has a distinct open so we can verify exit price is bar 20's open.
    # Strategy generates CLOSE_LONG at bar_index=20; the engine acts on it
    # immediately at bar 20's open (same bar, step 4 of the state machine).
    bars[20] = [20 * 3_600_000, 101.0, 101.5, 100.9, 101.2, 10.0]
    result = run_backtest(
        BuyOnceSellOnceStrategy(), {"BTC/USDT": bars}, EngineParams()
    )
    assert result.trades_count == 1
    t = result.trades[0]
    assert t["reason"] == "SIGNAL"
    assert t["exit_price"] == 101.0  # bar 20 open


def test_long_trail_raises_with_new_highs() -> None:
    # Bar 6: price rises to 103 (up 3%). Trail moves to 103*(1-0.015)=101.455.
    # Bar 7: price drops to low 101. That's above trail (101.455? no, 101<101.455, so hit trail)
    # Actually 101 < 101.455 → trail hit. Use a more explicit setup:
    bars = _flat_bars(30)
    # Entry at bar 5 with price 100 (flat bars)
    # Bar 6: high 103 → trail now at 103 * 0.985 = 101.455
    bars[6] = [6 * 3_600_000, 100.0, 103.0, 100.0, 102.5, 10.0]
    # Bar 7: low 101 → trail hit at 101.455
    bars[7] = [7 * 3_600_000, 102.5, 102.5, 101.0, 101.5, 10.0]
    result = run_backtest(
        OpenLongOnceStrategy(), {"BTC/USDT": bars}, EngineParams()
    )
    assert result.trades_count == 1
    t = result.trades[0]
    assert t["reason"] == "TRAIL"
    # Trail exit price ~= 103 * (1 - 0.015) = 101.455
    assert abs(t["exit_price"] - 101.455) < 1e-6
