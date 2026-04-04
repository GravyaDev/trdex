"""Analyst Agent — technical indicators + LLM-style reasoning with RAG context."""

from __future__ import annotations

import logging
import statistics

from trdex.agents.state import AgentState, AnalysisResult

logger = logging.getLogger(__name__)


def _compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """Compute RSI from a list of closing prices."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        (gains if delta > 0 else losses).append(abs(delta))
    avg_gain = statistics.mean(gains[-period:]) if gains else 0.0
    avg_loss = statistics.mean(losses[-period:]) if losses else 0.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return statistics.mean(closes[-period:])


def _rule_based_signal(
    rsi: float | None,
    sma_short: float | None,
    sma_long: float | None,
    price: float,
    sentiment_avg: float | None,
) -> tuple[str, float, str]:
    """Simple rule engine. Returns (signal, confidence, reasoning)."""
    signals: list[tuple[str, float]] = []
    notes: list[str] = []

    # RSI rule
    if rsi is not None:
        if rsi < 30:
            signals.append(("BUY", 0.6))
            notes.append(f"RSI={rsi:.1f} oversold")
        elif rsi > 70:
            signals.append(("SELL", 0.6))
            notes.append(f"RSI={rsi:.1f} overbought")
        else:
            signals.append(("HOLD", 0.3))
            notes.append(f"RSI={rsi:.1f} neutral")

    # SMA crossover rule
    if sma_short is not None and sma_long is not None:
        if sma_short > sma_long:
            signals.append(("BUY", 0.5))
            notes.append(f"SMA{9}={sma_short:.2f} > SMA{21}={sma_long:.2f} bullish")
        else:
            signals.append(("SELL", 0.5))
            notes.append(f"SMA{9}={sma_short:.2f} < SMA{21}={sma_long:.2f} bearish")

    # Sentiment nudge
    if sentiment_avg is not None:
        if sentiment_avg > 0.3:
            signals.append(("BUY", 0.2))
            notes.append(f"sentiment={sentiment_avg:.2f} positive")
        elif sentiment_avg < -0.3:
            signals.append(("SELL", 0.2))
            notes.append(f"sentiment={sentiment_avg:.2f} negative")

    if not signals:
        return "HOLD", 0.0, "Insufficient data."

    buy_conf = sum(c for s, c in signals if s == "BUY")
    sell_conf = sum(c for s, c in signals if s == "SELL")

    if buy_conf > sell_conf:
        return "BUY", min(buy_conf, 1.0), "; ".join(notes)
    if sell_conf > buy_conf:
        return "SELL", min(sell_conf, 1.0), "; ".join(notes)
    return "HOLD", 0.0, "; ".join(notes)


async def analyst_node(state: AgentState) -> AgentState:
    """Compute technical indicators and produce a trading signal."""
    logger.info("[Analyst] analysing %s", state.symbol)

    if state.market is None:
        state.analysis = AnalysisResult(signal="HOLD", reasoning="No market data.")
        return state

    closes = [c[4] for c in state.market.candles]  # index 4 = close
    price = state.market.price

    rsi = _compute_rsi(closes)
    sma_short = _compute_sma(closes, 9)
    sma_long = _compute_sma(closes, 21)

    # Average sentiment from context
    sentiments = [
        h["sentiment"]
        for h in state.sentiment.items
        if isinstance(h.get("sentiment"), float | int)
    ]
    sentiment_avg = statistics.mean(sentiments) if sentiments else None

    signal, confidence, reasoning = _rule_based_signal(
        rsi, sma_short, sma_long, price, sentiment_avg
    )

    indicators: dict[str, float] = {}
    if rsi is not None:
        indicators["rsi"] = rsi
    if sma_short is not None:
        indicators["sma_9"] = sma_short
    if sma_long is not None:
        indicators["sma_21"] = sma_long
    if sentiment_avg is not None:
        indicators["sentiment_avg"] = sentiment_avg

    state.analysis = AnalysisResult(
        signal=signal,
        confidence=confidence,
        reasoning=reasoning,
        indicators=indicators,
    )
    logger.info(
        "[Analyst] signal=%s confidence=%.2f | %s", signal, confidence, reasoning
    )
    return state
