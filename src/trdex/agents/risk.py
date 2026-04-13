"""Risk Manager Agent — external to AI reasoning, hard safety gate."""

from __future__ import annotations

import logging

from trdex.agents.intent import Intent
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
                    "intent": state.analysis.intent.value,
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
MIN_CONFIDENCE = 0.3          # Analyst must be at least 30% confident
MAX_POSITION_FRACTION = 0.05  # Never more than 5% of portfolio per trade
MAX_DRAWDOWN_BLOCK_LIVE = 0.10   # Block new trades in live mode at 10%
MAX_DRAWDOWN_BLOCK_SIM = 0.20    # More permissive in simulation (20%) to collect more data


async def risk_node(state: AgentState) -> AgentState:
    """Approve or block execution based on risk rules.

    This node is intentionally simple and rule-based — it must NOT
    be influenced by LLM reasoning. It is the last hard gate before
    any order reaches the Executor.
    """
    intent = state.analysis.intent
    logger.info("[Risk] evaluating intent=%s confidence=%.2f",
                intent.value, state.analysis.confidence)

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

    # Gate 1: HOLD intent → nothing to approve
    if intent == Intent.HOLD:
        state.risk = RiskDecision(approved=False, reason="Intent is HOLD — no trade.")
        return state

    # Gate 2: Minimum confidence threshold
    if state.analysis.confidence < MIN_CONFIDENCE:
        reason = f"Confidence {state.analysis.confidence:.2f} below threshold {MIN_CONFIDENCE}."
        state.risk = RiskDecision(approved=False, reason=reason)
        logger.warning("[Risk] BLOCKED — low confidence")
        await _write_last_signal(state, approved=False, reason=reason)
        return state

    # Gate 3: Portfolio drawdown gate — block if already in significant loss.
    # Applies only to OPEN intents: if we're already drawn down, closing an
    # existing position is exactly what we want to allow, not block.
    # Threshold is configurable via Runtime Config and mode-dependent:
    # simulation uses a higher default (20%) to accumulate more trade data,
    # live uses a tighter default (10%) to protect real capital.
    portfolio = state.portfolio
    from trdex.services.runtime_config import get_config_service
    _cfg = get_config_service()
    _dd_default = MAX_DRAWDOWN_BLOCK_SIM if settings.mode.value == "simulation" else MAX_DRAWDOWN_BLOCK_LIVE
    max_dd_block = (
        _cfg.get_typed("thresholds", "max_drawdown_block", _dd_default)
        if _cfg else _dd_default
    )
    if intent.is_open and portfolio.drawdown_pct >= max_dd_block:
        reason = f"Portfolio drawdown {portfolio.drawdown_pct:.1%} exceeds limit {max_dd_block:.1%}."
        state.risk = RiskDecision(approved=False, reason=reason)
        logger.warning("[Risk] BLOCKED — drawdown %.1f%%", portfolio.drawdown_pct * 100)
        await _write_last_signal(state, approved=False, reason=reason)
        return state

    # Gate 4 (D7): OPEN intents on an existing agent-owned position are
    # pyramiding attempts and must be blocked. CLOSE intents on an
    # existing position are the normal exit path and must pass through
    # — this is the core fix for the signal-vs-close paradox. The
    # translator already guarantees that CLOSE_LONG is only emitted
    # when the agent has an open long on this symbol (D21), so no
    # separate "CLOSE with no position" gate is needed (removed D8).
    if intent.is_open and state.symbol in portfolio.open_position_symbols_by_agent:
        reason = f"Already have an open position on {state.symbol} — no pyramiding."
        state.risk = RiskDecision(approved=False, reason=reason)
        logger.info("[Risk] BLOCKED — existing position on %s", state.symbol)
        await _write_last_signal(state, approved=False, reason=reason)
        return state

    # Gate 4b: Forex weekend closure — block OPEN intents on forex pairs
    # when the market is closed (Friday 22:00 → Sunday 22:00 UTC).
    # CLOSE intents pass through to allow exiting positions.
    if intent.is_open:
        from trdex.market.hours import is_market_open
        if not is_market_open(state.symbol):
            reason = f"Market closed for {state.symbol} (forex weekend)."
            state.risk = RiskDecision(approved=False, reason=reason)
            logger.info("[Risk] BLOCKED — forex market closed for %s", state.symbol)
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

    # SL/TP: use analyst LLM suggestions when available, clipped to safe range.
    # Fallback to defaults when LLM didn't run or didn't suggest.
    _SL_MIN, _SL_MAX, _SL_DEFAULT = 0.01, 0.10, 0.03
    _TP_MIN, _TP_MAX, _TP_DEFAULT = 0.02, 0.20, 0.05
    sl_suggestion = state.analysis.suggested_stop_loss
    tp_suggestion = state.analysis.suggested_take_profit
    if sl_suggestion is not None:
        final_sl = max(_SL_MIN, min(_SL_MAX, sl_suggestion))
        logger.info("[Risk] SL from LLM: %.2f%% → clipped to %.2f%%", sl_suggestion * 100, final_sl * 100)
    else:
        final_sl = _SL_DEFAULT
    if tp_suggestion is not None:
        final_tp = max(_TP_MIN, min(_TP_MAX, tp_suggestion))
        logger.info("[Risk] TP from LLM: %.2f%% → clipped to %.2f%%", tp_suggestion * 100, final_tp * 100)
    else:
        final_tp = _TP_DEFAULT

    # Flag trades approved above the live-mode drawdown threshold (10%).
    # These would have been blocked in live mode — useful for analysis.
    dd_warning = portfolio.drawdown_pct >= MAX_DRAWDOWN_BLOCK_LIVE
    approved_reason = "All risk gates passed."
    if dd_warning:
        approved_reason += f" (drawdown {portfolio.drawdown_pct:.1%} — would be blocked in live mode at {MAX_DRAWDOWN_BLOCK_LIVE:.0%})"
    state.risk = RiskDecision(
        approved=True,
        reason=approved_reason,
        position_size=position_size,
        stop_loss_pct=final_sl,
        take_profit_pct=final_tp,
        drawdown_warning=dd_warning,
    )
    logger.info("[Risk] APPROVED — position_size=%.3f dd_warning=%s", position_size, dd_warning)
    await _write_last_signal(state, approved=True, reason=approved_reason)

    # Optional LLM risk annotation (observability-only, never changes the decision)
    await _maybe_annotate_risk(state)

    return state


async def _maybe_annotate_risk(state: AgentState) -> None:
    """Call Haiku for a 1-2 sentence risk commentary. Best-effort, never blocks."""
    if state.llm_caller is None:
        return

    from langchain_core.messages import HumanMessage, SystemMessage
    from pydantic import BaseModel, Field

    class RiskAnnotation(BaseModel):
        annotation: str = Field(max_length=500)

    config = state.llm_caller.configs.get("risk")
    if config is None or not config.llm_enabled:
        return

    narrative = state.memory_snapshots.get("risk", "")
    prompt = (
        f"Symbol: {state.symbol}\n"
        f"Analyst signal: {state.analysis.intent.value} (confidence {state.analysis.confidence:.2f})\n"
        f"Risk decision: {'APPROVED' if state.risk.approved else 'BLOCKED'} — {state.risk.reason}\n"
        f"Portfolio: equity={state.portfolio.equity:.2f}, drawdown={state.portfolio.drawdown_pct:.1%}\n"
    )
    if narrative:
        prompt += f"\nRecent history:\n{narrative[:500]}\n"

    messages = [
        SystemMessage(content=(
            "You are reviewing a risk decision for trdex. This is an ANNOTATION — "
            "your output does NOT change the approve/block decision. "
            "In 1-2 sentences, note any risk factors the deterministic gates might miss: "
            "correlation between open positions, unusual loss/win streaks, market regime concerns. "
            "If nothing notable, output: 'No additional concerns.'"
        )),
        HumanMessage(content=prompt),
    ]

    try:
        result = await state.llm_caller.invoke("risk", messages, RiskAnnotation)
        if result is not None:
            state.risk.annotation = result.annotation
            logger.info("[Risk] annotation: %s", result.annotation[:100])
    except Exception:
        logger.debug("[Risk] annotation call failed — non-critical, continuing")
