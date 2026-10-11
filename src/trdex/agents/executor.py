"""Executor Agent — sends approved orders through the execution gateway."""

from __future__ import annotations

import logging

from trdex.agents.intent import Intent
from trdex.agents.memory_helpers import attach_memory_snapshot
from trdex.agents.state import AgentState, OrderResult

logger = logging.getLogger(__name__)


async def _resolve_close(state: AgentState) -> tuple[str, float, str] | None:
    """The agent-owned open position on ``state.symbol``, read ONCE (D13):
    ``(idempotency_key, qty, venue)``, or None if it is gone or unreadable.

    D19: the key is ``close:{position_id}``, the same shape the
    StopLossMonitor uses, so the exchange dedupes concurrent closes.
    Key, quantity and venue come from the same read: a close must never
    be sent to a market guessed after a failed lookup (on spot a SELL for
    a perp position would sell coins held there).
    """
    from trdex.storage.portfolio_repo import PortfolioRepository

    if state.session_factory is None:
        return None
    try:
        async with state.session_factory() as session:
            positions = await PortfolioRepository(session).get_open_positions()
    except Exception:
        logger.exception("[Executor] failed to read the open position on %s", state.symbol)
        return None
    for p in positions:
        # D21 mirror: only close positions the agent owns.
        if p.symbol == state.symbol and p.source == "agent":
            return f"close:{p.id}", float(p.amount), str(getattr(p, "venue", None) or "spot")
    return None


async def executor_node(state: AgentState) -> AgentState:
    """Execute the trade if Risk approved it.

    Uses the gateway injected into AgentState (DefaultExecutionGateway).
    Falls back to a freshly created DefaultExecutionGateway if none is injected,
    which preserves backward-compatibility with tests that don't inject a gateway.
    """
    # Attach executor-agent memory snapshot for traceability (read-only).
    await attach_memory_snapshot(state, "executor")

    if not state.risk.approved:
        state.order = OrderResult(
            status="skipped",
            message=f"Skipped: {state.risk.reason}",
        )
        logger.info("[Executor] skipped — %s", state.risk.reason)
        return state

    intent = state.analysis.intent
    price = state.market.price if state.market else 0.0

    if price <= 0:
        state.order = OrderResult(status="rejected", message="No valid market price.")
        logger.warning("[Executor] rejected — price=0 for %s", state.symbol)
        return state

    # Intent → exchange direction. Opens are sized from equity; closes
    # use the open position's amount and are reduce-only (on perps a close
    # must never open the other side; the kill switch lets them through).
    if intent == Intent.OPEN_LONG:
        direction, qty_basis = "BUY", "equity"
    elif intent == Intent.OPEN_SHORT:
        direction, qty_basis = "SELL", "equity"
    elif intent == Intent.CLOSE_LONG:
        direction, qty_basis = "SELL", "position"
    elif intent == Intent.CLOSE_SHORT:
        direction, qty_basis = "BUY", "position"
    else:
        state.order = OrderResult(
            status="skipped",
            message=f"Executor does not handle intent {intent.value}.",
        )
        logger.warning("[Executor] skipped — unsupported intent %s", intent.value)
        return state
    if qty_basis == "equity":
        idempotency_key, venue = f"agent:{state.run_id}", state.risk.venue
        close_qty = 0.0
    else:
        # A close goes to the market its position lives on; amount and
        # venue come from the same read of the live DB (the SL monitor may
        # have closed it since the cycle started).
        resolved = await _resolve_close(state)
        if resolved is None:
            state.order = OrderResult(
                status="skipped",
                message=(
                    f"{intent.name} on {state.symbol}: no open agent position found "
                    "(possibly closed by SL) or it could not be read."
                ),
            )
            logger.warning(
                "[Executor] %s skipped — no readable open position for %s",
                intent.name, state.symbol,
            )
            return state
        idempotency_key, close_qty, venue = resolved

    if qty_basis == "equity":
        equity = state.portfolio.equity if state.portfolio.equity > 0 else 10_000.0
        trade_value = equity * state.risk.position_size
        qty = trade_value / price
    else:
        qty = close_qty  # the whole position

    # Resolve gateway — use injected one or create a default instance
    gateway = state.gateway
    if gateway is None:
        from trdex.execution.default_gateway import DefaultExecutionGateway
        gateway = DefaultExecutionGateway.create()

    logger.info(
        "[Executor] intent=%s %s %s qty=%.6f @ %.4f key=%s",
        intent.value, direction, state.symbol, qty, price, idempotency_key,
    )

    state.order = await gateway.place(
        symbol=state.symbol,
        direction=direction,
        qty=qty,
        price=price,
        idempotency_key=idempotency_key,
        reduce_only=intent.is_close,
        leverage=state.risk.leverage if intent.is_open else 1,
        venue=venue,
    )
    logger.info("[Executor] result: status=%s %s", state.order.status, state.order.message)
    return state
