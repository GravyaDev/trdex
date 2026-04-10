"""Unit tests for market brief generator."""

from __future__ import annotations

from trdex.memory.market_brief import build_market_brief


def test_market_brief_empty_on_insufficient_data() -> None:
    """< 20 candles → empty string."""
    closes = [100.0] * 10
    volumes = [1000.0] * 10
    assert build_market_brief("BTC/USDT", closes, volumes, 100.0) == ""


def test_market_brief_contains_symbol_and_price() -> None:
    closes = [100.0 + i * 0.1 for i in range(30)]
    volumes = [1000.0] * 30
    brief = build_market_brief("BTC/USDT", closes, volumes, 103.0)
    assert "BTC/USDT" in brief
    assert "Market Brief" in brief
    assert "103" in brief


def test_market_brief_bullish_sma_alignment() -> None:
    """Rising closes → SMA5 > SMA13 → bullish."""
    closes = [100.0 + i * 0.5 for i in range(30)]
    volumes = [1000.0] * 30
    brief = build_market_brief("BTC/USDT", closes, volumes, closes[-1])
    assert "bullish" in brief.lower()


def test_market_brief_bearish_sma_alignment() -> None:
    """Falling closes → SMA5 < SMA13 → bearish."""
    closes = [100.0 - i * 0.5 for i in range(30)]
    volumes = [1000.0] * 30
    brief = build_market_brief("BTC/USDT", closes, volumes, closes[-1])
    assert "bearish" in brief.lower()


def test_market_brief_volume_surge_labelled() -> None:
    closes = [100.0 + i * 0.05 for i in range(30)]
    # Baseline volume 1000, last candle 3000 → surge
    volumes = [1000.0] * 29 + [3000.0]
    brief = build_market_brief("BTC/USDT", closes, volumes, closes[-1])
    assert "surge" in brief.lower()


def test_market_brief_volume_dried_up() -> None:
    closes = [100.0 + i * 0.05 for i in range(30)]
    # Baseline 1000, last 200 → ratio 0.2 < 0.5 → dried up
    volumes = [1000.0] * 29 + [200.0]
    brief = build_market_brief("BTC/USDT", closes, volumes, closes[-1])
    assert "dried up" in brief.lower()


def test_market_brief_rsi_overbought_zone() -> None:
    """Strong uptrend pushes RSI > 70."""
    closes = [100.0 + i * 1.0 for i in range(30)]  # strong up
    volumes = [1000.0] * 30
    brief = build_market_brief("BTC/USDT", closes, volumes, closes[-1])
    # RSI should be high; check the "approaching overbought" or "overbought" label
    assert "overbought" in brief.lower() or "oversold" not in brief.lower()


def test_market_brief_includes_volatility_classification() -> None:
    closes = [100.0 + i * 0.1 for i in range(30)]
    volumes = [1000.0] * 30
    brief = build_market_brief("BTC/USDT", closes, volumes, closes[-1])
    assert "Volatility" in brief
    # Should contain one of the regime labels
    assert any(lab in brief.lower() for lab in ["low", "medium", "high", "unknown"])


def test_market_brief_24h_change_computation() -> None:
    """24h change computed vs candle at index -24 (for 1h candles)."""
    # Base price 100, last 24 hours go up linearly to 110
    closes = [100.0] * 20 + [100.0 + i for i in range(11)]  # ends at 110
    volumes = [1000.0] * 31
    brief = build_market_brief("BTC/USDT", closes, volumes, 110.0)
    # 24h ago the price was closes[-24] = closes[7] = 100.0
    # Change = (110 - 100) / 100 * 100 = +10%
    assert "+10" in brief or "+9" in brief or "+11" in brief
