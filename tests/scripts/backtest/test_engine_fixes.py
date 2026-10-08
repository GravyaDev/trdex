"""Regression tests for backtest engine bugs found in the 2026-10 review.

Each test reproduces one bias that made results look better (or simply
different) than what the strategy would have done.
"""

from __future__ import annotations

from scripts.backtest.core import (
    EngineParams,
    run_backtest,
    sharpe_ratio,
    split_trades_by_quarter,
)
from scripts.backtest.strategies import LiveRuleEngine

from trdex.agents.analyst import _rule_based_signal

H = 3_600_000
DAY = 24 * H


def _flat(n: int, price: float = 100.0, t0: int = 0, step: int = H) -> list[list]:
    return [[t0 + i * step, price, price, price, price, 10.0] for i in range(n)]


class BuyAt:
    """BUY once at ``at`` (per-symbol bar index), then HOLD."""

    def __init__(self, at: int = 2, timeframe: str = "1h", **overrides) -> None:
        self.name = "BuyAt"
        self.timeframe = timeframe
        self._at = at
        for k, v in overrides.items():
            setattr(self, k, v)

    def generate_signal(self, bar_index, candles, indicators, position_state):
        return "BUY" if bar_index == self._at and position_state == "flat" else "HOLD"


class SellAt(BuyAt):
    def generate_signal(self, bar_index, candles, indicators, position_state):
        return "SELL" if bar_index == self._at and position_state == "flat" else "HOLD"


NO_FEES_WIDE = EngineParams(fee_pct=0.0, sl_pct=0.5, tp_pct=0.5, trail_pct=0.5)


# ── 1. positions still open at the end of the data ────────────────────────


def test_open_positions_are_closed_at_end_of_data_not_lost():
    result = run_backtest(BuyAt(), {"A": _flat(20), "B": _flat(20)}, NO_FEES_WIDE)
    assert result.final_equity == 10_000.0  # was 9_500: A's budget vanished
    assert [t["reason"] for t in result.trades] == ["EOD", "EOD"]


# ── 2. symbols run on one shared timeline ─────────────────────────────────


def test_symbols_are_simulated_concurrently_on_a_shared_timeline():
    result = run_backtest(BuyAt(), {"A": _flat(20), "B": _flat(20)}, NO_FEES_WIDE)
    # One equity point per timestamp, not one per (symbol, bar).
    assert len(result.equity_curve) == 20
    # Both positions were open at the same time, sized on the same equity.
    a, b = result.trades
    assert a["entry_ts"] == b["entry_ts"]
    assert a["qty"] == b["qty"]


# ── 3. Sharpe annualised with the strategy's own timeframe ───────────────


def test_sharpe_uses_daily_annualisation_for_daily_strategies():
    bars = [
        [i * H, 100 + i * 0.01, 101 + i * 0.01, 99 + i * 0.01, 100.5 + i * 0.01, 1.0]
        for i in range(24 * 30)
    ]
    bars[24 * 20 + 5][3] = 80.0  # one ugly intraday low so the curve is not monotonic
    result = run_backtest(
        BuyAt(at=2, timeframe="1d"),
        {"A": bars},
        EngineParams(fee_pct=0.0, sl_pct=0.5, tp_pct=0.5, trail_pct=0.0),
    )
    assert result.sharpe == sharpe_ratio(result.equity_curve, bars_per_year=365)


# ── 4. "quarters" cover the whole sample ──────────────────────────────────


def test_quarter_split_covers_five_years_evenly():
    trades = [{"entry_ts": d * DAY, "net_pnl": 1.0} for d in range(1825)]
    sizes = [len(v) for v in split_trades_by_quarter(trades).values()]
    assert max(sizes) - min(sizes) <= 1  # was 91 / 91 / 91 / 1552


# ── 5. gap through the stop fills at the open ─────────────────────────────


def test_gap_down_through_stop_fills_at_open_not_at_stop():
    bars = [*_flat(3), [3 * H, 80.0, 81.0, 79.0, 80.0, 1.0], *_flat(2, 80.0, t0=4 * H)]
    result = run_backtest(
        BuyAt(), {"A": bars}, EngineParams(fee_pct=0.0, sl_pct=0.02, tp_pct=0.5, trail_pct=0.0)
    )
    t = result.trades[0]
    assert t["reason"] == "SL"
    assert t["exit_price"] == 80.0  # was 98.0


def test_gap_up_through_short_stop_fills_at_open():
    bars = [*_flat(3), [3 * H, 120.0, 121.0, 119.0, 120.0, 1.0], *_flat(2, 120.0, t0=4 * H)]
    result = run_backtest(
        SellAt(), {"A": bars}, EngineParams(fee_pct=0.0, sl_pct=0.02, tp_pct=0.5, trail_pct=0.0)
    )
    assert result.trades[0]["exit_price"] == 120.0  # was 102.0


# ── 6. trail_pct == 0 means "no trailing stop" ────────────────────────────


def test_zero_trail_disables_trailing_instead_of_exiting_at_the_high():
    bars = [*_flat(3), [3 * H, 100, 103, 99.5, 100.2, 1], [4 * H, 100.2, 100.5, 99.8, 100.0, 1]]
    bars += _flat(2, t0=5 * H)
    result = run_backtest(
        BuyAt(tp_pct_override=0.5, trail_pct_override=0.0),
        {"A": bars},
        EngineParams(fee_pct=0.0, sl_pct=0.02),
    )
    t = result.trades[0]
    assert t["reason"] == "EOD"  # was TRAIL at exactly 103.0
    assert t["exit_price"] == 100.0


# ── 7. the entry bar's range is checked after the fill ────────────────────


def test_stop_hit_inside_the_entry_bar_is_not_ignored():
    bars = [*_flat(2), [2 * H, 100.0, 100.2, 97.0, 99.0, 1.0], *_flat(3, 99.0, t0=3 * H)]
    result = run_backtest(
        BuyAt(), {"A": bars}, EngineParams(fee_pct=0.0, sl_pct=0.02, tp_pct=0.5, trail_pct=0.0)
    )
    t = result.trades[0]
    assert t["reason"] == "SL"
    assert t["exit_ts"] == 2 * H


# ── 8. short positions are marked to market correctly ─────────────────────


def test_open_short_does_not_dent_the_equity_curve_at_flat_prices():
    result = run_backtest(SellAt(), {"A": _flat(10)}, NO_FEES_WIDE)
    assert min(result.equity_curve) == 10_000.0  # was 9_500 while the short was open


# ── 9. trade P&L includes the entry fee ──────────────────────────────────


class BuyEveryOther:
    name = "BuyEveryOther"
    timeframe = "1h"

    def generate_signal(self, bar_index, candles, indicators, position_state):
        if position_state == "flat":
            return "BUY"
        return "CLOSE_LONG"


def test_trade_pnl_sums_to_the_change_in_equity():
    result = run_backtest(
        BuyEveryOther(), {"A": _flat(21)}, EngineParams(sl_pct=0.5, tp_pct=0.5, trail_pct=0.0)
    )
    assert result.trades_count == 10
    assert all(t["net_pnl"] < 0 for t in result.trades)  # flat prices: fees only
    assert abs(sum(t["net_pnl"] for t in result.trades) - result.total_pnl) < 1e-9


# ── 10. no re-entry at the open of a bar whose low already stopped us out ──


class AlwaysLong:
    name = "AlwaysLong"
    timeframe = "1h"

    def generate_signal(self, bar_index, candles, indicators, position_state):
        return "BUY" if position_state == "flat" else "HOLD"


def test_no_reentry_on_the_bar_that_hit_the_stop():
    bars = [*_flat(4), [4 * H, 100.0, 100.2, 97.0, 99.0, 1.0], *_flat(3, 99.0, t0=5 * H)]
    result = run_backtest(
        AlwaysLong(),
        {"A": bars},
        EngineParams(fee_pct=0.0, sl_pct=0.02, tp_pct=0.5, trail_pct=0.0),
    )
    stop, eod = result.trades
    assert stop["reason"] == "SL" and stop["exit_ts"] == 4 * H
    assert eod["entry_ts"] == 5 * H  # next bar's open, not bar 4's open


# ── 11. LiveRuleEngine replays the production rule engine ──────────────────


def _ind(rsi, s9, s21, closes=None):
    closes = closes or [100.0] * 30
    n = len(closes)
    return {"rsi14": [rsi] * n, "sma9": [s9] * n, "sma21": [s21] * n, "closes": closes}


def test_live_rule_engine_matches_production_rules_and_is_long_only():
    s = LiveRuleEngine()
    cases = [
        (75, 101, 100),
        (55, 99, 100),
        (25, 99, 100),
        (45, 101, 100),
        (60, 101, 100),
        (40, 99, 100),
    ]
    for rsi, s9, s21 in cases:
        prod, _, _ = _rule_based_signal(rsi, s9, s21, 100.0, None)
        flat = s.generate_signal(25, [], _ind(rsi, s9, s21), "flat")
        long_ = s.generate_signal(25, [], _ind(rsi, s9, s21), "long")
        assert flat == ("BUY" if prod == "BUY" else "HOLD")
        assert long_ == ("CLOSE_LONG" if prod == "SELL" else "HOLD")
        assert "SELL" not in (flat, long_)


def test_live_rule_engine_uses_the_adaptive_stop_floor():
    calm = LiveRuleEngine().exit_pcts(25, _ind(50, 1, 1), EngineParams())
    assert calm == (0.02, 0.04, 0.015)
    wild = [100.0, 130.0] * 15  # CV ≈ 13%
    sl, tp, trail = LiveRuleEngine().exit_pcts(25, _ind(50, 1, 1, wild), EngineParams())
    assert sl > 0.3 and tp > 0.6 and trail > 0.18
