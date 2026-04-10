"""Prompt assembly for LLM-enabled agent nodes.

Builds the messages list (system + user) for each agent, enforcing
the ``max_prompt_tokens`` budget from settings. Memory tiers are
truncated LIFO (Tier 4b episodes first, then Tier 4a similar trades,
then Tier 6 narrative, then Tier 5 entity facts, then Tier 2
operational) if the assembled prompt exceeds the budget.

RAG content is sanitized via ``sanitize_rag_content()`` before inclusion.
"""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from trdex.agents.llm_provider import sanitize_rag_content
from trdex.agents.state import AgentState
from trdex.memory.market_brief import build_market_brief

logger = logging.getLogger(__name__)

# Default system prompt for the Analyst (used when agent_config.system_prompt is empty).
_DEFAULT_ANALYST_SYSTEM_PROMPT = """\
You are the Analyst Agent for trdex, an AI crypto trading platform.

Your job is to analyze technical indicators and market context, then produce a trading signal with confidence.

## Your Personality
- You think probabilistically. Every trade has uncertain outcome.
- You never abandon a strategy based on a few losses.
- You respect the math of your indicators and never override them with intuition.
- You are measured and conservative. When in doubt, you say HOLD.

## Hard Constraints (INVIOLABLE)
- Never emit BUY or SELL with confidence below 0.40. If unsure, output HOLD.
- You do NOT decide execution. The Risk Manager gates your signal independently.

## Indicator Reference (what the numbers mean — NOT prescriptive rules)
- **RSI(14)**: momentum oscillator, 0-100. Below 30 = oversold, above 70 = overbought. Zones of interest, not automatic signals.
- **SMA(9) vs SMA(21)**: short crosses above long = bullish shift; below = bearish. Lagging signal.
- **Volatility regime (CV)**: Low (<1%) = range-bound, medium (1-3%) = trending, high (>3%) = volatile/unpredictable.
- **Sentiment score (-1 to +1)**: Scout's news assessment. Complements but should not override technical signals.

## Reasoning Guidelines
- Weigh ALL inputs together — indicators, sentiment, memory, entity facts. No single input should dominate unless extreme.
- Your reflection memory shows recent performance. If a pattern has been consistently unprofitable, factor that in.
- Explain your reasoning in 2-3 sentences. Be specific about which inputs drove the decision.
- Calibrate confidence honestly: 0.40-0.55 = marginal edge, 0.55-0.70 = moderate, 0.70-0.85 = strong, >0.85 = exceptional (rare)."""


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    return len(text) // 4


def build_analyst_messages(
    state: AgentState,
    *,
    system_prompt: str = "",
    indicators: dict[str, float],
    regime: str,
    cv: float | None,
    price: float,
    max_prompt_tokens: int = 4096,
) -> list[SystemMessage | HumanMessage]:
    """Assemble the messages list for the Analyst LLM call.

    Returns [SystemMessage, HumanMessage] with the user message containing
    all structured data (indicators, sentiment, memory snapshot).
    """
    sys_text = system_prompt.strip() or _DEFAULT_ANALYST_SYSTEM_PROMPT
    sys_msg = SystemMessage(content=sys_text)

    # Budget: subtract system prompt, leave room for output
    budget = max_prompt_tokens - _estimate_tokens(sys_text) - 200  # 200 tok buffer

    # === Build user message sections, ordered by priority (highest first) ===
    sections: list[str] = []

    # 0. Market brief (static snapshot — small, high-signal preamble)
    if state.market and state.market.candles:
        closes = [c[4] for c in state.market.candles]
        volumes = [c[5] for c in state.market.candles]
        brief = build_market_brief(state.symbol, closes, volumes, price)
        if brief:
            sections.append(brief)

    # 1. Technical indicators (always included — small, critical)
    ind_lines = [f"## Technical Indicators for {state.symbol}"]
    ind_lines.append(f"- Current price: {price:.8g}")
    for k, v in indicators.items():
        ind_lines.append(f"- {k}: {v:.4f}")
    ind_lines.append(f"- Volatility regime: {regime} (CV={cv:.4f})" if cv else f"- Volatility regime: {regime}")
    ind_section = "\n".join(ind_lines)
    sections.append(ind_section)

    # 2. Sentiment context (sanitized)
    sent_lines = ["\n## Market Context (from Scout)"]
    summary = sanitize_rag_content(state.sentiment.summary) if state.sentiment.summary else "No context available."
    sent_lines.append(summary)
    if state.sentiment.sentiment_score is not None:
        sent_lines.append(f"\nSentiment score: {state.sentiment.sentiment_score:.2f}")
    if state.sentiment.key_events:
        sent_lines.append("Key events: " + "; ".join(state.sentiment.key_events))
    sent_section = "\n".join(sent_lines)
    sections.append(sent_section)

    # 3. Memory snapshot (may be large — truncated if over budget)
    memory_text = state.memory_snapshots.get("analyst", "")
    if memory_text:
        sections.append(f"\n## Reflection Memory\n{memory_text}")

    # === Enforce token budget ===
    user_text = "\n".join(sections)
    tokens = _estimate_tokens(user_text)

    if tokens > budget and memory_text:
        # Truncate memory (LIFO: memory is the most expendable)
        excess = tokens - budget
        chars_to_cut = excess * 4  # reverse of estimate
        truncated_memory = memory_text[:max(0, len(memory_text) - chars_to_cut)]
        if truncated_memory:
            sections[-1] = f"\n## Reflection Memory (truncated)\n{truncated_memory}..."
        else:
            sections.pop()  # remove memory entirely
        user_text = "\n".join(sections)
        logger.info(
            "[prompt_builder] truncated memory snapshot for analyst (%d → %d est. tokens)",
            tokens, _estimate_tokens(user_text),
        )

    return [sys_msg, HumanMessage(content=user_text)]


# ── Scout prompt ─────────────────────────────────────────────────────────────

_DEFAULT_SCOUT_SYSTEM_PROMPT = """\
You are the Scout Agent for trdex, an AI trading platform.

Your sole job is to SUMMARIZE market context for {symbol}. You do NOT make trading decisions.

## Rules
- Report ONLY facts and computed sentiment. No opinions, no recommendations.
- Never output BUY/SELL/HOLD signals.
- Never evaluate technical indicators (that's the Analyst's job).
- Extract a single numeric sentiment score from -1.0 (extremely bearish) to +1.0 (extremely bullish).
- If documents conflict, note the contradiction explicitly.
- If no meaningful context is available, say so honestly."""


def build_scout_messages(
    state: AgentState,
    *,
    system_prompt: str = "",
    rag_hits: list[dict],
    max_prompt_tokens: int = 4096,
) -> list[SystemMessage | HumanMessage]:
    """Assemble the messages list for the Scout LLM call."""
    raw_sys = system_prompt.strip() or _DEFAULT_SCOUT_SYSTEM_PROMPT
    sys_text = raw_sys.replace("{symbol}", state.symbol)
    sys_msg = SystemMessage(content=sys_text)

    budget = max_prompt_tokens - _estimate_tokens(sys_text) - 200

    sections: list[str] = []

    # 1. RAG documents (sanitized)
    sections.append(f"## Retrieved context for {state.symbol}\n")
    if rag_hits:
        for i, h in enumerate(rag_hits, 1):
            text = sanitize_rag_content(h.get("text", ""))[:500]
            source = h.get("source", "unknown")
            sentiment = h.get("sentiment")
            sent_str = f" (sentiment={sentiment:.2f})" if isinstance(sentiment, (int, float)) else ""
            sections.append(f"{i}. [{source}]{sent_str}: {text}")
    else:
        sections.append("No documents retrieved.")

    # 2. Memory snapshot (if available)
    memory_text = state.memory_snapshots.get("scout", "")
    if memory_text:
        sections.append(f"\n## Memory context\n{memory_text}")

    # Enforce budget
    user_text = "\n".join(sections)
    tokens = _estimate_tokens(user_text)
    if tokens > budget and memory_text:
        excess = tokens - budget
        chars_to_cut = excess * 4
        truncated = memory_text[:max(0, len(memory_text) - chars_to_cut)]
        if truncated:
            sections[-1] = f"\n## Memory context (truncated)\n{truncated}..."
        else:
            sections.pop()
        user_text = "\n".join(sections)

    return [sys_msg, HumanMessage(content=user_text)]
