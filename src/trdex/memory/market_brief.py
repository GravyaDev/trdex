"""Market brief generator — static summary of current market conditions.

Produces a compact, LLM-ready text block summarizing the current state of
a symbol from its most recent OHLCV data. This is a *static* snapshot
(no semantic search involved) meant to be injected as a KB-like preamble
in the Analyst prompt before any RAG tiers.

The brief covers:
- Current price and 24h change
- Volatility regime and CV
- RSI level
- SMA alignment (bullish/bearish)
- Volume activity vs baseline
- Recent trend direction

Usage:
    brief = build_market_brief("BTC/USDT", closes, volumes, current_price)
    # Returns a multi-line string ready for prompt injection
"""

from __future__ import annotations

from trdex.backtest.indicators import (
    classify_volatility,
    rsi_from_list,
    sma_from_list,
    volume_ratio,
)


def build_market_brief(
    symbol: str,
    closes: list[float],
    volumes: list[float],
    current_price: float,
) -> str:
    """Generate a static market brief from recent OHLCV data.

    Returns an empty string if insufficient data (< 20 candles).
    """
    if len(closes) < 20:
        return ""

    lines: list[str] = [f"## Market Brief — {symbol}"]

    # Price and 24h change (assuming 1h candles, last 24 = index -24)
    ref_idx = min(24, len(closes) - 1)
    ref_price = closes[-ref_idx]
    pct_24h = (current_price - ref_price) / ref_price * 100 if ref_price != 0 else 0.0
    lines.append(f"- Price: {current_price:.8g} ({pct_24h:+.2f}% vs 24h ago)")

    # Volatility
    regime, cv = classify_volatility(closes)
    cv_str = f" (CV={cv*100:.2f}%)" if cv is not None else ""
    lines.append(f"- Volatility: {regime}{cv_str}")

    # RSI
    rsi_val = rsi_from_list(closes)
    if rsi_val is not None:
        zone = ""
        if rsi_val < 30:
            zone = " — oversold"
        elif rsi_val < 40:
            zone = " — approaching oversold"
        elif rsi_val > 70:
            zone = " — overbought"
        elif rsi_val > 60:
            zone = " — approaching overbought"
        lines.append(f"- RSI(14): {rsi_val:.1f}{zone}")

    # SMA alignment
    sma5 = sma_from_list(closes, 5)
    sma13 = sma_from_list(closes, 13)
    if sma5 is not None and sma13 is not None:
        alignment = "bullish (SMA5 > SMA13)" if sma5 > sma13 else "bearish (SMA5 < SMA13)"
        lines.append(f"- Trend: {alignment}")

    # Volume
    vol_r = volume_ratio(volumes)
    if vol_r is not None:
        vol_label = "normal"
        if vol_r > 2.0:
            vol_label = "surge"
        elif vol_r > 1.3:
            vol_label = "elevated"
        elif vol_r < 0.5:
            vol_label = "dried up"
        lines.append(f"- Volume: {vol_r:.1f}x baseline ({vol_label})")

    # Short-term trend (last 10 candles)
    if len(closes) >= 10:
        short_pct = (closes[-1] - closes[-10]) / closes[-10] * 100 if closes[-10] != 0 else 0.0
        direction = "up" if short_pct > 0.5 else "down" if short_pct < -0.5 else "flat"
        lines.append(f"- Short-term (10 candles): {direction} ({short_pct:+.2f}%)")

    return "\n".join(lines)
