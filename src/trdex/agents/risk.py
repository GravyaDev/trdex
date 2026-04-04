"""Risk Manager Agent — external to AI reasoning, hard safety gate."""

from __future__ import annotations

import logging

from trdex.agents.state import AgentState, RiskDecision
from trdex.config import get_settings

logger = logging.getLogger(__name__)

# Hard limits — never bypassed by the AI signal
MIN_CONFIDENCE = 0.4        # Analyst must be at least 40% confident
MAX_POSITION_FRACTION = 0.05  # Never more than 5% of portfolio per trade


async def risk_node(state: AgentState) -> AgentState:
    """Approve or block execution based on risk rules.

    This node is intentionally simple and rule-based — it must NOT
    be influenced by LLM reasoning. It is the last hard gate before
    any order reaches the Executor.
    """
    logger.info("[Risk] evaluating signal=%s confidence=%.2f",
                state.analysis.signal, state.analysis.confidence)

    settings = get_settings()

    # Gate 1: HOLD signal → nothing to approve
    if state.analysis.signal == "HOLD":
        state.risk = RiskDecision(approved=False, reason="Signal is HOLD — no trade.")
        return state

    # Gate 2: Minimum confidence threshold
    if state.analysis.confidence < MIN_CONFIDENCE:
        state.risk = RiskDecision(
            approved=False,
            reason=f"Confidence {state.analysis.confidence:.2f} below threshold {MIN_CONFIDENCE}.",
        )
        logger.warning("[Risk] BLOCKED — low confidence")
        return state

    # Gate 3: Simulation mode enforcement
    if settings.mode.value == "live":
        # In live mode we'd check portfolio balance, drawdown limits, etc.
        # For now, live mode always requires explicit gate criteria (Phase 5).
        logger.warning("[Risk] Live mode gate not yet implemented — blocking.")
        state.risk = RiskDecision(
            approved=False,
            reason="Live mode gate not yet implemented. Run in simulation.",
        )
        return state

    # Position sizing: use configured max, capped at hard limit
    position_size = min(settings.max_position_pct, MAX_POSITION_FRACTION)

    state.risk = RiskDecision(
        approved=True,
        reason="All risk gates passed.",
        position_size=position_size,
        stop_loss_pct=0.02,
        take_profit_pct=0.04,
    )
    logger.info("[Risk] APPROVED — position_size=%.3f", position_size)
    return state
