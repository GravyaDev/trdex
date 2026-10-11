"""Regression tests for backtest engine bugs found in the 2026-10 review.

Each test reproduces one bias that made results look better (or simply
different) than what the strategy would have done.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from trdex.agents.analyst import _rule_based_signal
from trdex.research.engine import (
    EngineParams,
    run_backtest,
    sharpe_ratio,
    split_trades_by_quarter,
)
from trdex.research.strategies import LiveRuleEngine

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


# ── 12. risk-based sizing and regime gate, as in the live Risk node ───────


class _BuyOnceWithStop:
    name = "BuyOnceWithStop"
    timeframe = "1h"

    def __init__(self, sl: float, risk: float | None):
        self.sl_pct_override = sl
        self.risk_per_trade_pct_override = risk

    def generate_signal(self, bar_index, candles, indicators, position_state):
        return "BUY" if bar_index == 2 and position_state == "flat" else "HOLD"


def _entry_notional(strategy) -> float:
    params = EngineParams(fee_pct=0.0, tp_pct=0.9, trail_pct=0.0)
    trade = run_backtest(strategy, {"A": _flat(10)}, params).trades[0]
    return trade["qty"] * trade["entry_price"]


def test_engine_sizes_by_risk_so_wider_stops_get_smaller_positions():
    tight = _entry_notional(_BuyOnceWithStop(sl=0.02, risk=0.001))
    wide = _entry_notional(_BuyOnceWithStop(sl=0.10, risk=0.001))
    assert tight == pytest.approx(10_000 * 0.05)  # 0.1% / 2% = 5%, the cap
    assert wide == pytest.approx(10_000 * 0.01)  # 0.1% / 10%
    assert tight * 0.02 == pytest.approx(wide * 0.10)  # same risk at the stop


def test_engine_keeps_notional_sizing_without_a_risk_setting():
    assert _entry_notional(_BuyOnceWithStop(sl=0.10, risk=None)) == pytest.approx(10_000 * 0.05)


def test_live_rule_engine_stop_matches_the_live_monitor_floor():
    from trdex.risk.sizing import recent_cv
    from trdex.risk.stop_loss import effective_thresholds

    wild = [100.0, 130.0] * 15
    ind = _ind(50, 1, 1, wild)
    expected = effective_thresholds(
        None, None, recent_cv(wild[5:25]), base_sl=0.02, base_tp=0.04, base_trail=0.015
    )
    assert LiveRuleEngine().exit_pcts(25, ind, EngineParams()) == expected


def test_live_rule_engine_regime_gate_blocks_entries_but_not_exits():
    from trdex.risk.sizing import RegimeBounds

    wild = [100.0, 130.0] * 15  # CV ~13%
    gated = LiveRuleEngine(regime=RegimeBounds(cv_max=0.04))
    rsi_buy, rsi_sell = (60, 101, 100), (40, 99, 100)  # production rules: BUY / SELL
    assert LiveRuleEngine().generate_signal(25, [], _ind(*rsi_buy, wild), "flat") == "BUY"
    assert gated.generate_signal(25, [], _ind(*rsi_buy, wild), "flat") == "HOLD"
    assert gated.generate_signal(25, [], _ind(*rsi_sell, wild), "long") == "CLOSE_LONG"


def test_live_rule_engine_defaults_to_the_live_risk_setting():
    assert LiveRuleEngine().risk_per_trade_pct_override == 0.001
    assert LiveRuleEngine(risk_per_trade_pct=None).risk_per_trade_pct_override is None


# ── 13. portfolio rules, as in the live Risk node ─────────────────────────

FOUR = {s: _flat(10) for s in ("A", "B", "C", "D")}


def _notionals(params, strategy=None) -> dict[str, float]:
    strategy = strategy or _BuyOnceWithStop(sl=0.02, risk=0.001)  # 5% notional, 0.1% risk
    trades = run_backtest(strategy, FOUR, params).trades
    return {t["symbol"]: t["qty"] * t["entry_price"] for t in trades}


BASE = EngineParams(fee_pct=0.0, tp_pct=0.9, trail_pct=0.0)


def test_portfolio_risk_budget_reduces_then_skips_entries():
    got = _notionals(replace(BASE, portfolio_risk_max_pct=0.0025))
    # 0.1% + 0.1% fit, the third gets the 0.05% left (half size), the fourth nothing
    assert sorted(got.values()) == pytest.approx([250.0, 500.0, 500.0])


def test_correlated_cluster_cap_skips_entries_beyond_the_limit():
    params = replace(BASE, clusters=(frozenset({"A", "B", "C"}),), max_per_cluster=2)
    got = _notionals(params)
    assert len(got) == 3 and "D" in got  # D is outside the cluster


def test_reward_risk_rule_skips_entries_whose_target_is_too_close():
    params = replace(BASE, tp_pct=0.04, min_reward_risk=1.5)
    assert _notionals(params, _BuyOnceWithStop(sl=0.03, risk=0.001)) == {}  # 1.33
    assert len(_notionals(params, _BuyOnceWithStop(sl=0.02, risk=0.001))) == 4  # 2.0


def test_portfolio_rules_off_by_default():
    assert len(_notionals(BASE)) == 4


# ── 14. perpetuals: shorts, leverage, funding, liquidation ────────────────


def test_live_rule_engine_opens_shorts_only_on_perps():
    bear = _ind(rsi=40.0, s9=99.0, s21=100.0)
    bull = _ind(rsi=60.0, s9=101.0, s21=100.0)
    spot, perps = LiveRuleEngine(), LiveRuleEngine(shorts=True)
    assert spot.generate_signal(1, None, bear, "flat") == "HOLD"
    assert perps.generate_signal(1, None, bear, "flat") == "SELL"
    assert perps.generate_signal(1, None, bear, "long") == "CLOSE_LONG"
    assert perps.generate_signal(1, None, bull, "short") == "CLOSE_SHORT"
    assert perps.generate_signal(1, None, bear, "short") == "HOLD"


PERPS = EngineParams(
    fee_pct=0.0, sl_pct=0.02, tp_pct=0.9, trail_pct=0.0, perps=True, max_leverage=3.0
)


def test_perps_lock_only_the_margin_and_keep_equity_at_flat_prices():
    result = run_backtest(SellAt(), {"A": _flat(6)}, PERPS)
    (trade,) = result.trades
    assert trade["side"] == "short" and trade["leverage"] == 3
    assert result.final_equity == pytest.approx(10_000.0)


def test_funding_is_paid_by_longs_and_received_by_shorts_every_8h():
    params = replace(PERPS, funding_rate_8h=0.0001)
    days = _flat(49)  # bars at 00:00 ... 48:00 UTC -> boundaries 8,16,24,32,40,48 after entry
    long_eq = run_backtest(BuyAt(), {"A": days}, params).final_equity
    short_eq = run_backtest(SellAt(), {"A": days}, params).final_equity
    notional = 10_000 * 0.05
    assert long_eq == pytest.approx(10_000 - 6 * notional * 0.0001)
    assert short_eq == pytest.approx(10_000 + 6 * notional * 0.0001)


def test_a_gap_through_liquidation_loses_the_whole_margin_and_no_more():
    bars = [*_flat(4), [4 * H, 300.0, 300.0, 300.0, 300.0, 10.0], *_flat(2, t0=5 * H)]
    wide = replace(PERPS, sl_pct=0.15)  # 3x allowed (<= 16.4%)
    result = run_backtest(SellAt(), {"A": bars}, wide)
    (trade,) = result.trades
    assert trade["reason"] == "LIQ" and trade["leverage"] == 3
    margin = 10_000 * 0.05 / 3
    assert trade["net_pnl"] == pytest.approx(-margin)
    assert result.final_equity == pytest.approx(10_000 - margin)


def test_entry_whose_stop_no_leverage_can_protect_is_skipped():
    assert run_backtest(SellAt(), {"A": _flat(6)}, replace(PERPS, sl_pct=0.6)).trades == []
