"""Risk Manager Agent — external to AI reasoning, hard safety gate."""

from __future__ import annotations

import logging
from typing import Any

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


def _cfg_float(cfg: Any, key: str, default: float | None) -> float | None:
    """Read a ``thresholds`` value from Runtime Config, falling back to ``default``."""
    if cfg is None:
        return default
    value = cfg.get_typed("thresholds", key, default)
    return None if value is None else float(value)


async def _entry_stop_pct(
    state: AgentState,
    cv: float | None,
    cfg: Any,
    settings: Any,
    position: Any = None,
) -> float:
    """Stop-loss fraction the StopLossMonitor will apply to a new position on
    ``state.symbol``: per-symbol override, else ``max(base, 2.5 x CV)``.

    ``position`` carries per-position values stored at open (on main there
    are none: always ``None``; on llm-agents the LLM-suggested stop, which
    ``effective_thresholds`` can only use to widen the adaptive floor).

    Uses the monitor's own ``effective_thresholds`` and the same Runtime
    Config keys the monitor is built from, so sizing and exits agree.
    Raises if the per-symbol override cannot be read (caller fails closed).
    """
    from trdex.risk.stop_loss import effective_thresholds

    base_sl = _cfg_float(cfg, "sl_position_pct", settings.sl_position_pct)
    base_tp = _cfg_float(cfg, "sl_take_profit_pct", settings.sl_take_profit_pct)
    base_trail = _cfg_float(cfg, "sl_trailing_stop_pct", settings.sl_trailing_stop_pct)
    override = None
    if state.session_factory is not None:
        from trdex.storage.symbol_config_repo import SymbolConfigRepository
        async with state.session_factory() as session:
            override = await SymbolConfigRepository(session).get(state.symbol)
    stop_pct, _, _ = effective_thresholds(
        position,
        override,
        cv if cv is not None else 0.0,
        base_sl=base_sl or 0.0,
        base_tp=base_tp or 0.0,
        base_trail=base_trail or 0.0,
    )
    return float(stop_pct)


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

    # Volatility of the candles the Analyst used: same formula and window
    # as the value it writes to the entity graph for the StopLossMonitor.
    from trdex.risk.sizing import RegimeBounds, check_regime, recent_cv, risk_position_fraction
    cv = recent_cv([c[4] for c in state.market.candles]) if state.market else None

    # Gate 4c: volatility regime — OPEN intents only (CLOSE must always
    # pass). Entries outside the CV range the strategy was backtested on
    # are blocked; bounds come from scripts/backtest/regime_range.py via
    # Runtime Config (thresholds.regime_cv_min / regime_cv_max).
    # Simulation: unset bounds = gate off, to keep collecting data.
    # Live: unset bounds = fail-closed (untested conditions).
    if intent.is_open:
        try:
            bounds = RegimeBounds.from_config(
                _cfg_float(_cfg, "regime_cv_min", None),
                _cfg_float(_cfg, "regime_cv_max", None),
            )
            regime_block = check_regime(cv, bounds)
            if regime_block is None and not bounds.configured and settings.mode.value == "live":
                regime_block = (
                    "regime bounds not configured — live mode requires "
                    "thresholds.regime_cv_min/regime_cv_max from scripts/backtest/regime_range.py"
                )
        except Exception as exc:
            regime_block = f"invalid regime bounds (fail-closed): {exc}"
        if regime_block is not None:
            reason = f"Volatility regime gate: {regime_block}."
            state.risk = RiskDecision(approved=False, reason=reason)
            logger.info("[Risk] BLOCKED — %s", reason)
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

    # Position sizing — risk-based. An OPEN commits the equity fraction
    # that loses ``risk_per_trade_pct`` if the StopLossMonitor's stop is
    # hit, capped at max_position_pct (and the hard MAX_POSITION_FRACTION).
    # With the defaults (risk 0.1%, base stop 2%, cap 5%) a low-volatility
    # entry is sized exactly as before; wider adaptive stops get smaller
    # positions instead of more risk. CLOSE sells the whole position
    # (executor), so its size is informational only.
    sizing_note = ""
    try:
        max_fraction = min(
            _cfg_float(_cfg, "max_position_pct", settings.max_position_pct) or 0.0,
            MAX_POSITION_FRACTION,
        )
        position_size = max_fraction
        if intent.is_open:
            stop_pct = await _entry_stop_pct(state, cv, _cfg, settings)
            risk_per_trade = _cfg_float(_cfg, "risk_per_trade_pct", settings.risk_per_trade_pct) or 0.0
            position_size = risk_position_fraction(
                risk_per_trade=risk_per_trade, stop_pct=stop_pct, max_fraction=max_fraction,
            )
            sizing_note = (
                f" Size {position_size:.2%} of equity: risk {position_size * stop_pct:.3%}"
                f" at stop {stop_pct:.2%} (cv={cv if cv is not None else 0.0:.4f})."
            )
    except Exception as exc:
        reason = f"Position sizing failed (fail-closed): {exc}"
        state.risk = RiskDecision(approved=False, reason=reason)
        logger.exception("[Risk] BLOCKED — %s", reason)
        await _write_last_signal(state, approved=False, reason=reason)
        return state
    if portfolio.equity > 0:
        trade_value = portfolio.equity * position_size
        logger.info("[Risk] equity=%.2f position_size=%.3f → trade_value≈%.2f",
                    portfolio.equity, position_size, trade_value)

    # Flag trades approved above the live-mode drawdown threshold (10%).
    # These would have been blocked in live mode — useful for analysis.
    dd_warning = portfolio.drawdown_pct >= MAX_DRAWDOWN_BLOCK_LIVE
    approved_reason = "All risk gates passed." + sizing_note
    if dd_warning:
        approved_reason += f" (drawdown {portfolio.drawdown_pct:.1%} — would be blocked in live mode at {MAX_DRAWDOWN_BLOCK_LIVE:.0%})"
    state.risk = RiskDecision(
        approved=True,
        reason=approved_reason,
        position_size=position_size,
        stop_loss_pct=0.03,
        take_profit_pct=0.05,
        drawdown_warning=dd_warning,
    )
    logger.info("[Risk] APPROVED — position_size=%.3f dd_warning=%s", position_size, dd_warning)
    await _write_last_signal(state, approved=True, reason=approved_reason)
    return state
