"""Smoke tests for each strategy — one expected signal per scenario."""

from __future__ import annotations

from scripts.backtest.strategies import (
    BaselineInverse,
    BaselineLive,
    BollingerSqueezeBreakout,
    BreakoutVolume,
    MeanReversionRSI,
    MultiTimeframeConfirm,
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


def test_multi_timeframe_requires_both_live_signal_and_trend_confirm() -> None:
    # Fix 1: 30 bars, bar_index=30 so bar_index-24=6 is valid
    bars = [[i * 3_600_000, 100.0, 100.0, 100.0, 100.0, 10.0] for i in range(30)]
    # RSI says BUY (live signal = BUY when >=50)
    # SMA20(4h) is rising — confirm BUY
    # Strategy reads sma[bar_index-1]=sma[29] vs sma[bar_index-24]=sma[6]
    # sma[6] = 99.0 + 4*0.2 = 99.8, sma[29] = 99.0 + 27*0.2 = 104.4 → rising ✓
    ind = {
        "rsi14": [None] * 29 + [55.0],
        "sma20_4h": [None, None] + [99.0 + i * 0.2 for i in range(28)],
    }
    sig = MultiTimeframeConfirm().generate_signal(
        bar_index=30, candles=bars, indicators=ind, position_state="flat"
    )
    assert sig == "BUY"


def test_multi_timeframe_rejects_when_trend_opposite() -> None:
    # Fix 2: 30 bars, bar_index=30, falling sma20_4h
    bars = [[i * 3_600_000, 100.0, 100.0, 100.0, 100.0, 10.0] for i in range(30)]
    # RSI says BUY but 4h trend is falling — reject
    # sma[6] = 103.0 - 4*0.15 = 102.4, sma[29] = 103.0 - 27*0.15 = 98.95 → falling ✓
    ind = {
        "rsi14": [None] * 29 + [55.0],
        "sma20_4h": [None, None] + [103.0 - i * 0.15 for i in range(28)],
    }
    sig = MultiTimeframeConfirm().generate_signal(
        bar_index=30, candles=bars, indicators=ind, position_state="flat"
    )
    assert sig == "HOLD"


def test_breakout_volume_fires_on_volume_confirmed_breakout() -> None:
    # 25 bars: first 24 with price in range [99, 100], bar 24 closes at 102 with 3x avg volume.
    bars = []
    for i in range(24):
        bars.append([i * 3_600_000, 99.5, 100.0, 99.0, 99.5, 10.0])
    # Bar 24 breakout
    bars.append([24 * 3_600_000, 100.0, 102.5, 99.9, 102.0, 30.0])  # vol 3x avg

    ind = {
        "closes": [99.5] * 24 + [102.0],
        "highs": [100.0] * 24 + [102.5],
        "lows": [99.0] * 24 + [99.9],
        "volumes": [10.0] * 24 + [30.0],
        "vol_ma24": [None] * 23 + [10.0, 10.83],  # approx
    }
    # Fix 3: bar_index=25 (was 24) → strategy reads closes[24]=102.0 (cur),
    # prev_window=closes[0:24] → prev_max=99.5, 102>99.5 breakout, vol 30>1.5*10.83=16.25 → BUY
    sig = BreakoutVolume().generate_signal(
        bar_index=25, candles=bars, indicators=ind, position_state="flat"
    )
    assert sig == "BUY"


def test_breakout_volume_skips_without_volume_confirm() -> None:
    bars = []
    for i in range(24):
        bars.append([i * 3_600_000, 99.5, 100.0, 99.0, 99.5, 10.0])
    bars.append([24 * 3_600_000, 100.0, 102.5, 99.9, 102.0, 11.0])  # price breakout, low volume

    ind = {
        "closes": [99.5] * 24 + [102.0],
        "highs": [100.0] * 24 + [102.5],
        "lows": [99.0] * 24 + [99.9],
        "volumes": [10.0] * 24 + [11.0],
        "vol_ma24": [None] * 23 + [10.0, 10.04],
    }
    # Fix 4: bar_index=25, vol=11 < 1.5*10.04=15.06 → HOLD ✓
    sig = BreakoutVolume().generate_signal(
        bar_index=25, candles=bars, indicators=ind, position_state="flat"
    )
    assert sig == "HOLD"


def test_bollinger_squeeze_fires_on_squeeze_release_up() -> None:
    # Strategy reads squeeze[bar_index-2] (prev) and squeeze[bar_index-1] (cur)
    # With bar_index=30: prev=squeeze[28], cur=squeeze[29]
    # released = prev_squeeze and not cur_squeeze
    bars = [[i * 3_600_000, 100.0, 100.0, 100.0, 100.0, 10.0] for i in range(30)]
    bars[29] = [29 * 3_600_000, 100.0, 103.0, 100.0, 102.5, 10.0]
    squeeze = [False] * 30
    # Fix 5: squeeze[28]=True (prev bar was squeezing), squeeze[29] stays False (cur released)
    squeeze[28] = True  # prev bar was squeezing, cur is released
    ind = {
        "closes": [100.0] * 29 + [102.5],
        "bb_upper": [None] * 29 + [101.5],
        "bb_lower": [None] * 29 + [98.5],
        "squeeze": squeeze,
    }
    sig = BollingerSqueezeBreakout().generate_signal(
        bar_index=30, candles=bars, indicators=ind, position_state="flat"
    )
    assert sig == "BUY"
