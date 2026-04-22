"""Smoke tests for each strategy — one expected signal per scenario."""

from __future__ import annotations

from scripts.backtest.strategies import (
    BaselineInverse,
    BaselineLive,
    MeanReversionRSI,
)


def _bars_with_indicators(rsi_value: float, bars_count: int = 10) -> tuple[list, dict]:
    bars = [[i * 3_600_000, 100.0, 100.0, 100.0, 100.0, 10.0] for i in range(bars_count)]
    ind = {
        "rsi14": [None] * (bars_count - 1) + [rsi_value],
        "sma9": [None] * (bars_count - 1) + [100.0],
        "sma21": [None] * (bars_count - 1) + [100.0],
        "closes": [100.0] * bars_count,
    }
    return bars, ind


def test_baseline_live_buys_on_rsi_above_50() -> None:
    bars, ind = _bars_with_indicators(55.0)
    sig = BaselineLive().generate_signal(
        bar_index=len(bars), candles=bars, indicators=ind, position_state="flat"
    )
    assert sig == "BUY"


def test_baseline_live_sells_on_rsi_below_50() -> None:
    bars, ind = _bars_with_indicators(45.0)
    sig = BaselineLive().generate_signal(
        bar_index=len(bars), candles=bars, indicators=ind, position_state="flat"
    )
    assert sig == "SELL"


def test_baseline_live_holds_when_rsi_none() -> None:
    bars, ind = _bars_with_indicators(50.0)
    ind["rsi14"] = [None] * len(bars)
    sig = BaselineLive().generate_signal(
        bar_index=len(bars), candles=bars, indicators=ind, position_state="flat"
    )
    assert sig == "HOLD"


def test_baseline_inverse_flips_live_signal() -> None:
    bars, ind = _bars_with_indicators(55.0)
    sig = BaselineInverse().generate_signal(
        bar_index=len(bars), candles=bars, indicators=ind, position_state="flat"
    )
    # Inverse of BUY → SELL
    assert sig == "SELL"


def test_mean_reversion_buys_on_rsi_oversold() -> None:
    bars, ind = _bars_with_indicators(25.0)
    sig = MeanReversionRSI().generate_signal(
        bar_index=len(bars), candles=bars, indicators=ind, position_state="flat"
    )
    assert sig == "BUY"


def test_mean_reversion_sells_on_rsi_overbought() -> None:
    bars, ind = _bars_with_indicators(75.0)
    sig = MeanReversionRSI().generate_signal(
        bar_index=len(bars), candles=bars, indicators=ind, position_state="flat"
    )
    assert sig == "SELL"


def test_mean_reversion_holds_in_neutral_zone() -> None:
    bars, ind = _bars_with_indicators(50.0)
    sig = MeanReversionRSI().generate_signal(
        bar_index=len(bars), candles=bars, indicators=ind, position_state="flat"
    )
    assert sig == "HOLD"
