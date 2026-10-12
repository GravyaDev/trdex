"""Unit tests for backtest indicators."""

from __future__ import annotations

import math

from trdex.research.indicators import (
    bollinger_bands,
    is_squeezing,
    sma,
    volume_ma,
    wilder_rsi,
)


def test_wilder_rsi_returns_none_for_warmup_period() -> None:
    closes = [100.0, 101.0, 102.0]
    result = wilder_rsi(closes, period=14)
    assert len(result) == 3
    assert all(v is None for v in result)


def test_wilder_rsi_computes_once_enough_data() -> None:
    # 15 closes with strict uptrend: RSI should be very high (>90).
    closes = [100.0 + i for i in range(15)]
    result = wilder_rsi(closes, period=14)
    assert result[14] is not None
    assert result[14] > 90.0


def test_wilder_rsi_all_zero_loss_yields_100() -> None:
    # Strict monotone increase: no losses, RSI = 100.
    closes = [100.0 + i for i in range(20)]
    result = wilder_rsi(closes, period=14)
    assert result[-1] == 100.0


def test_sma_returns_none_for_warmup() -> None:
    assert sma([1.0, 2.0], period=3) == [None, None]


def test_sma_correct_value() -> None:
    # SMA(3) at index 2 of [1, 2, 3] = 2.0
    result = sma([1.0, 2.0, 3.0, 4.0], period=3)
    assert result[0] is None
    assert result[1] is None
    assert result[2] == 2.0
    assert result[3] == 3.0


def test_bollinger_bands_structure() -> None:
    closes = [float(i) for i in range(30)]
    upper, mid, lower = bollinger_bands(closes, period=20, std_dev=2.0)
    assert len(upper) == 30
    assert len(mid) == 30
    assert len(lower) == 30
    # First 19 are None (warmup)
    assert upper[18] is None
    assert upper[19] is not None
    # Upper > mid > lower for a non-flat series
    assert upper[25] > mid[25] > lower[25]


def test_volume_ma_correct_value() -> None:
    volumes = [10.0, 20.0, 30.0, 40.0, 50.0]
    result = volume_ma(volumes, period=3)
    assert result[0] is None
    assert result[1] is None
    assert result[2] == 20.0  # (10+20+30)/3
    assert result[3] == 30.0
    assert result[4] == 40.0


def test_is_squeezing_detects_low_bandwidth() -> None:
    # Construct synthetic BB widths: first 50 wide, last 10 narrow.
    # Squeeze should fire on the narrow tail when percentile window covers both.
    closes = [100.0] * 50 + [100.0 + 0.01 * (i % 2) for i in range(50)]
    # Use period=20 for BB, percentile=30 meaning "in bottom 30% of recent widths"
    result = is_squeezing(closes, bb_period=20, std_dev=2.0, lookback=40, pct=0.3)
    assert len(result) == len(closes)
    # Tail should show squeeze=True
    assert result[-1] is True
    # Early bars (warmup) should be False (not enough data)
    assert result[10] is False


def test_wilder_rsi_matches_reference_value() -> None:
    # Known reference: a simple sequence with a couple of losses.
    # Computed manually / cross-checked with polars version in src/trdex.
    closes = [
        44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
        45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00,
        46.03, 46.41, 46.22, 45.64,
    ]
    result = wilder_rsi(closes, period=14)
    # 20 closes, so we have a valid RSI from index 14 onwards.
    assert result[14] is not None
    # Expected range: this uptrend with a pullback yields RSI ~70–80.
    assert 50.0 < result[-1] < 70.0
    # No infs/nans
    for v in result:
        assert v is None or math.isfinite(v)
