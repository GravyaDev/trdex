"""Analyst Agent — technical indicators + LLM reasoning with RAG context.

Two execution paths:

1. **LLM path** (when ``state.llm_caller`` is injected and analyst config has
   ``llm_enabled=True``): computes indicators deterministically, assembles a
   prompt with indicators + sentiment + memory, calls the LLM via
   ``LLMCaller.invoke()``, parses the structured ``AnalystOutput``.

2. **Fallback path** (LLM disabled, budget exhausted, or LLM call fails):
   runs the original ``_rule_based_signal()`` deterministic rule engine.
   This is a known quality degradation — the ``llm_used`` flag on
   ``AnalysisResult`` makes the difference visible to the dashboard.
"""

from __future__ import annotations

import logging
import statistics

from trdex.agents.intent import Intent, signal_to_intent
from trdex.agents.memory_helpers import attach_memory_snapshot
from trdex.agents.state import AgentState, AnalysisResult
from trdex.backtest.indicators import rsi_from_list

logger = logging.getLogger(__name__)


# ── Deterministic helpers (unchanged from rule-engine era) ───────────────────


def _classify_volatility(closes: list[float]) -> str:
    """Classify recent volatility regime from close prices.

    Returns one of: "low", "medium", "high".
    Uses coefficient of variation (std/mean) over the last 20 candles.
    Thresholds: <1% low, 1-3% medium, >3% high.
    """
    window = closes[-20:] if len(closes) >= 20 else closes
    if len(window) < 3:
        return "unknown"
    mean = statistics.mean(window)
    if mean == 0:
        return "unknown"
    cv = statistics.stdev(window) / mean
    if cv < 0.01:
        return "low"
    if cv < 0.03:
        return "medium"
    return "high"


async def _write_volatility_regime(state: AgentState, regime: str, cv: float | None = None) -> None:
    """Persist volatility_regime fact for this symbol in the entity graph."""
    if state.session_factory is None:
        return
    try:
        from trdex.storage.entity_graph_repo import EntityGraphRepository
        async with state.session_factory() as session:
            repo = EntityGraphRepository(session)
            await repo.upsert(
                subject_type="symbol",
                subject_id=state.symbol,
                predicate="volatility_regime",
                object_value={"regime": regime, "cv": cv},
                source="analyst",
                note=f"run_id={state.run_id}",
            )
    except Exception:
        logger.exception("[Analyst] failed to write volatility_regime to entity graph")


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
    """Simple rule engine fallback. Returns (signal, confidence, reasoning)."""
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


# ── LLM path ────────────────────────────────────────────────────────────────


async def _llm_analyst_signal(
    state: AgentState,
    indicators: dict[str, float],
    regime: str,
    cv: float | None,
    price: float,
) -> tuple[str, float, str, float | None, float | None] | None:
    """Call the LLM via LLMCaller and return (signal, confidence, reasoning, sl, tp).

    Returns ``None`` if the LLM is unavailable or fails — caller should
    fall back to ``_rule_based_signal()``.
    """
    if state.llm_caller is None:
        return None

    from trdex.agents.prompt_builder import build_analyst_messages
    from trdex.agents.structured_output import AnalystOutput
    from trdex.config import get_settings

    settings = get_settings()

    # Get system prompt from config (LLMCaller holds the configs)
    config = state.llm_caller.configs.get("analyst")
    system_prompt = config.system_prompt if config else ""

    messages = build_analyst_messages(
        state,
        system_prompt=system_prompt,
        indicators=indicators,
        regime=regime,
        cv=cv,
        price=price,
        max_prompt_tokens=settings.llm_max_prompt_tokens,
    )

    result = await state.llm_caller.invoke("analyst", messages, AnalystOutput)
    if result is None:
        return None

    return (
        result.signal,
        result.confidence,
        result.reasoning,
        result.suggested_stop_loss,
        result.suggested_take_profit,
    )


# ── Main node ────────────────────────────────────────────────────────────────


async def analyst_node(state: AgentState) -> AgentState:
    """Compute technical indicators and produce a trading signal.

    Tries the LLM path first; falls back to the deterministic rule engine
    if the LLM is disabled, fails, or returns None.
    """
    logger.info("[Analyst] analysing %s", state.symbol)

    if state.market is None:
        state.analysis = AnalysisResult(intent=Intent.HOLD, reasoning="No market data.")
        return state

    # Pull aggregated memory snapshot from the 6-tier stack (best-effort).
    await attach_memory_snapshot(state, "analyst")

    closes = [c[4] for c in state.market.candles]  # index 4 = close
    price = state.market.price

    rsi = rsi_from_list(closes)
    sma_short = _compute_sma(closes, 9)
    sma_long = _compute_sma(closes, 21)

    # Classify and persist volatility regime
    regime = _classify_volatility(closes)
    window = closes[-20:] if len(closes) >= 20 else closes
    mean = statistics.mean(window) if window else 0
    cv = statistics.stdev(window) / mean if mean and len(window) >= 3 else None
    await _write_volatility_regime(state, regime, cv)
    logger.debug("[Analyst] volatility_regime=%s cv=%s", regime, f"{cv:.4f}" if cv else "n/a")

    # Average sentiment from context
    sentiments = [
        h["sentiment"]
        for h in state.sentiment.items
        if isinstance(h.get("sentiment"), float | int)
    ]
    sentiment_avg = statistics.mean(sentiments) if sentiments else None

    # Build indicator dict for both paths
    indicators: dict[str, float] = {}
    if rsi is not None:
        indicators["rsi"] = rsi
    if sma_short is not None:
        indicators["sma_9"] = sma_short
    if sma_long is not None:
        indicators["sma_21"] = sma_long
    if sentiment_avg is not None:
        indicators["sentiment_avg"] = sentiment_avg

    # ── Try LLM path first ──────────────────────────────────────────────
    llm_result = await _llm_analyst_signal(state, indicators, regime, cv, price)

    if llm_result is not None:
        signal, confidence, reasoning, suggested_sl, suggested_tp = llm_result
        llm_used = True
        logger.info("[Analyst] LLM signal=%s confidence=%.2f", signal, confidence)
    else:
        # ── Fallback: deterministic rule engine ─────────────────────────
        signal, confidence, reasoning = _rule_based_signal(
            rsi, sma_short, sma_long, price, sentiment_avg
        )
        suggested_sl = None
        suggested_tp = None
        llm_used = False
        logger.info("[Analyst] fallback rule engine signal=%s confidence=%.2f", signal, confidence)

    # D5: rule engine stays portfolio-ignorant. Translation to Intent
    # happens here, downstream, with the live portfolio context.
    intent = signal_to_intent(signal, state.symbol, state.portfolio)

    state.analysis = AnalysisResult(
        intent=intent,
        confidence=confidence,
        reasoning=reasoning,
        indicators=indicators,
        suggested_stop_loss=suggested_sl,
        suggested_take_profit=suggested_tp,
        llm_used=llm_used,
    )
    logger.info(
        "[Analyst] signal=%s → intent=%s confidence=%.2f llm=%s | %s",
        signal, intent.value, confidence, llm_used, reasoning,
    )
    return state
