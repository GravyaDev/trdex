"""Unit tests for the vectorised SMA crossover strategy.

Three mandatory cases from the design Decision Log (D6):
    1. flat input → no signals at all
    2. controlled crossover → exactly one BUY at the expected bar, one SELL
       at the expected bar, zeros elsewhere
    3. warm-up bars (first long_period rows) → all zero

A fourth test guards the config validation (positive periods, short<long).
"""

from __future__ import annotations

import polars as pl
import pytest

from trdex.strategy.backtest.sma_cross import (
    BacktestSMACross,
    BacktestSMACrossConfig,
)


def _df(closes: list[float]) -> pl.DataFrame:
    return pl.DataFrame({"close": closes})


# ---------------------------------------------------------------------------
# 1. flat input → no cross
# ---------------------------------------------------------------------------


def test_no_cross_returns_all_zeros() -> None:
    """A flat price series can never produce a SMA crossing."""
    strat = BacktestSMACross(BacktestSMACrossConfig(short_period=3, long_period=5))
    sig = strat.generate_signals(_df([100.0] * 30))

    assert len(sig) == 30
    assert sig.dtype == pl.Int8
    assert sig.sum() == 0
    assert set(sig.to_list()) == {0}


# ---------------------------------------------------------------------------
# 2. controlled crossover → single BUY then single SELL at known bars
# ---------------------------------------------------------------------------


def test_golden_then_death_cross_emits_single_signals() -> None:
    """A V-shaped price series produces exactly one BUY and one SELL,
    each on the bar where the cross actually happens (not on every bar
    where short>long persists)."""

    # 10 flat bars (warm-up), 10 bars rising, 10 bars falling.
    closes = [100.0] * 10 + [101.0 + i * 0.5 for i in range(10)] + [
        110.0 - i * 0.5 for i in range(10)
    ]
    strat = BacktestSMACross(BacktestSMACrossConfig(short_period=3, long_period=5))
    sig = strat.generate_signals(_df(closes))
    values = sig.to_list()

    buys = [i for i, v in enumerate(values) if v == 1]
    sells = [i for i, v in enumerate(values) if v == -1]

    # Exactly one BUY and one SELL — emission is single, not continuous.
    assert len(buys) == 1, f"expected 1 BUY, got {len(buys)} at {buys}"
    assert len(sells) == 1, f"expected 1 SELL, got {len(sells)} at {sells}"

    # The BUY must come from the rising leg (bars 10..19), the SELL from
    # the falling leg (bars 20..29). Exact bar depends on the SMA periods
    # chosen — we only assert it lands in the right segment.
    assert 10 <= buys[0] < 20, f"BUY at bar {buys[0]} outside rising leg"
    assert 20 <= sells[0] < 30, f"SELL at bar {sells[0]} outside falling leg"

    # All other bars must be HOLD.
    for i, v in enumerate(values):
        if i in buys or i in sells:
            continue
        assert v == 0, f"unexpected non-zero {v} at bar {i}"


# ---------------------------------------------------------------------------
# 3. warm-up period is zero
# ---------------------------------------------------------------------------


def test_warmup_period_is_zero() -> None:
    """The first long_period bars cannot have a valid SMA — must be 0."""
    cfg = BacktestSMACrossConfig(short_period=3, long_period=10)
    strat = BacktestSMACross(cfg)

    # Strong rising trend immediately — would normally produce a BUY
    # in the *first few bars*, but we require the warm-up to suppress it.
    closes = [float(i) for i in range(50)]  # 0,1,2,...,49
    sig = strat.generate_signals(_df(closes))
    values = sig.to_list()

    warmup = values[: cfg.long_period]
    assert all(v == 0 for v in warmup), (
        f"warm-up region must be all zeros, got {warmup}"
    )


# ---------------------------------------------------------------------------
# 4. config validation
# ---------------------------------------------------------------------------


def test_config_rejects_non_positive_periods() -> None:
    with pytest.raises(ValueError):
        BacktestSMACrossConfig(short_period=0, long_period=5)
    with pytest.raises(ValueError):
        BacktestSMACrossConfig(short_period=5, long_period=-1)


def test_config_rejects_short_ge_long() -> None:
    with pytest.raises(ValueError):
        BacktestSMACrossConfig(short_period=10, long_period=10)
    with pytest.raises(ValueError):
        BacktestSMACrossConfig(short_period=20, long_period=10)


def test_strategy_rejects_dataframe_without_close_column() -> None:
    strat = BacktestSMACross()
    with pytest.raises(ValueError, match="close"):
        strat.generate_signals(pl.DataFrame({"open": [1.0, 2.0, 3.0]}))


def test_strategy_name_includes_periods() -> None:
    strat = BacktestSMACross(BacktestSMACrossConfig(short_period=7, long_period=21))
    assert strat.name == "sma_cross(7,21)"
