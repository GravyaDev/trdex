"""Risk Manager Agent — external to AI reasoning, hard safety gate."""

from __future__ import annotations

import logging

from trdex.agents.memory_helpers import attach_memory_snapshot
from trdex.agents.state import AgentState, RiskDecision
from trdex.config import get_settings

logger = logging.getLogger(__name__)


async def _write_last_signal(state: AgentState, approved: bool, reason: str) -> None:
    """Persist last_signal fact for this symbol in the entity graph."""
    if state.session_factory is None:
        return
    try:
        from trdex.storage.entity_graph_repo import EntityGraphRepository
        async with state.session_factory() as session:
            repo = EntityGraphRepository(session)
            await repo.upsert(
                subject_type="symbol",
                subject_id=state.symbol,
                predicate="last_signal",
                object_value={
                    "signal": state.analysis.signal,
                    "confidence": state.analysis.confidence,
                    "approved": approved,
                    "reason": reason,
                    "run_id": state.run_id,
                },
                source="risk",
                note=f"run_id={state.run_id}",
            )
    except Exception:
        logger.exception("[Risk] failed to write last_signal to entity graph")

# Hard limits — never bypassed by the AI signal
MIN_CONFIDENCE = 0.4          # Analyst must be at least 40% confident
MAX_POSITION_FRACTION = 0.05  # Never more than 5% of portfolio per trade
MAX_DRAWDOWN_BLOCK = 0.10     # Block new trades if drawdown exceeds 10%


async def risk_node(state: AgentState) -> AgentState:
    """Approve or block execution based on risk rules.

    This node is intentionally simple and rule-based — it must NOT
    be influenced by LLM reasoning. It is the last hard gate before
    any order reaches the Executor.
    """
    logger.info("[Risk] evaluating signal=%s confidence=%.2f",
                state.analysis.signal, state.analysis.confidence)

    # Attach risk-agent memory snapshot for observability/prompt material only.
    # NOTE: hard rules below MUST remain rule-based — never branch on memory.
    await attach_memory_snapshot(state, "risk")

    settings = get_settings()

    # Gate 0: Kill switch — overrides everything, including the AI
    from trdex.risk.stop_loss import get_kill_switch
    ks = get_kill_switch()
    if ks.active:
        state.risk = RiskDecision(
            approved=False,
            reason=f"Kill switch active: {ks.status['reason']}",
        )
        logger.critical("[Risk] BLOCKED by kill switch — %s", ks.status["reason"])
        return state

    # Gate 1: HOLD signal → nothing to approve
    if state.analysis.signal == "HOLD":
        state.risk = RiskDecision(approved=False, reason="Signal is HOLD — no trade.")
        return state

    # Gate 2: Minimum confidence threshold
    if state.analysis.confidence < MIN_CONFIDENCE:
        reason = f"Confidence {state.analysis.confidence:.2f} below threshold {MIN_CONFIDENCE}."
        state.risk = RiskDecision(approved=False, reason=reason)
        logger.warning("[Risk] BLOCKED — low confidence")
        await _write_last_signal(state, approved=False, reason=reason)
        return state

    # Gate 3: Portfolio drawdown gate — block if already in significant loss
    portfolio = state.portfolio
    if portfolio.drawdown_pct >= MAX_DRAWDOWN_BLOCK:
        reason = f"Portfolio drawdown {portfolio.drawdown_pct:.1%} exceeds limit {MAX_DRAWDOWN_BLOCK:.1%}."
        state.risk = RiskDecision(approved=False, reason=reason)
        logger.warning("[Risk] BLOCKED — drawdown %.1f%%", portfolio.drawdown_pct * 100)
        await _write_last_signal(state, approved=False, reason=reason)
        return state

    # Gate 4: Already have an open position on this symbol — no pyramiding
    if state.symbol in portfolio.open_position_symbols:
        reason = f"Already have an open position on {state.symbol} — no pyramiding."
        state.risk = RiskDecision(approved=False, reason=reason)
        logger.info("[Risk] BLOCKED — existing position on %s", state.symbol)
        await _write_last_signal(state, approved=False, reason=reason)
        return state

    # Gate 5: Live mode requires passing simulation gate criteria
    if settings.mode.value == "live" and state.session_factory is not None:
        from trdex.risk.readiness import evaluate_readiness
        try:
            async with state.session_factory() as session:
                report = await evaluate_readiness(session, settings)
            if not report.ready:
                reason = (
                    f"Live mode blocked — simulation criteria not met: "
                    f"{'; '.join(report.failures)}. "
                    f"Run at least {settings.gate_min_days} days of simulation "
                    f"with >{settings.gate_min_win_rate:.0%} win rate and "
                    f"<{settings.gate_max_drawdown:.0%} drawdown."
                )
                state.risk = RiskDecision(approved=False, reason=reason)
                logger.warning("[Risk] BLOCKED — %s", reason)
                await _write_last_signal(state, approved=False, reason=reason)
                return state
            logger.info("[Risk] simulation gate PASSED — live trading allowed")
        except Exception:
            reason = "Live mode blocked — could not evaluate simulation readiness (fail-closed)."
            logger.exception("[Risk] %s", reason)
            state.risk = RiskDecision(approved=False, reason=reason)
            await _write_last_signal(state, approved=False, reason=reason)
            return state

    # Position sizing: use configured max, capped at hard limit
    # If we have real equity, log it for transparency
    position_size = min(settings.max_position_pct, MAX_POSITION_FRACTION)
    if portfolio.equity > 0:
        trade_value = portfolio.equity * position_size
        logger.info("[Risk] equity=%.2f position_size=%.3f → trade_value≈%.2f",
                    portfolio.equity, position_size, trade_value)

    approved_reason = "All risk gates passed."
    state.risk = RiskDecision(
        approved=True,
        reason=approved_reason,
        position_size=position_size,
        stop_loss_pct=0.02,
        take_profit_pct=0.04,
    )
    logger.info("[Risk] APPROVED — position_size=%.3f", position_size)
    await _write_last_signal(state, approved=True, reason=approved_reason)
    return state
