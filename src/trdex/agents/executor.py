"""Executor Agent — sends approved orders through the execution gateway."""

from __future__ import annotations

import logging

from trdex.agents.intent import Intent
from trdex.agents.memory_helpers import attach_memory_snapshot
from trdex.agents.state import AgentState, OrderResult

logger = logging.getLogger(__name__)


async def _resolve_close_idempotency_key(state: AgentState) -> tuple[str, int | None]:
    """Look up the agent-owned open position on ``state.symbol`` and
    return ``(idempotency_key, position_id)``.

    D19: the close path must use the same idempotency key shape that
    the StopLossMonitor uses — ``close:{position_id}`` — so the
    exchange deduplicates concurrent close attempts by the agent and
    the SL monitor against a single position.

    Falls back to the run-scoped key if the session factory is not
    injected (unit tests) or the position cannot be located; in that
    case ``position_id`` is ``None`` and the runner's ``_dispatch_fill``
    will not attempt to persist the close (D13 abort path).
    """
    from trdex.storage.portfolio_repo import PortfolioRepository

    fallback = f"agent:{state.run_id}"
    if state.session_factory is None:
        return fallback, None
    try:
        async with state.session_factory() as session:
            repo = PortfolioRepository(session)
            positions = await repo.get_open_positions()
            for p in positions:
                # D21 mirror: only close positions the agent owns.
                if p.symbol == state.symbol and p.source == "agent":
                    return f"close:{p.id}", p.id
    except Exception:
        logger.exception(
            "[Executor] failed to resolve position id for close on %s", state.symbol
        )
    return fallback, None


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

    # Intent → exchange direction. SHORT intents are reserved vocabulary
    # for a future iteration; if one ever reaches here, skip defensively.
    if intent == Intent.OPEN_LONG:
        direction = "BUY"
        idempotency_key = f"agent:{state.run_id}"
        qty_basis = "equity"  # sized from equity
    elif intent == Intent.CLOSE_LONG:
        direction = "SELL"
        idempotency_key, _pos_id = await _resolve_close_idempotency_key(state)
        qty_basis = "position"  # sized from the open position amount
    else:
        state.order = OrderResult(
            status="skipped",
            message=f"Executor does not handle intent {intent.value} (short side not enabled).",
        )
        logger.warning("[Executor] skipped — unsupported intent %s", intent.value)
        return state

    if qty_basis == "equity":
        equity = state.portfolio.equity if state.portfolio.equity > 0 else 10_000.0
        trade_value = equity * state.risk.position_size
        qty = trade_value / price
    else:
        # CLOSE_LONG: close the full position size. Re-read from DB
        # to get the authoritative amount (runner may race with SL).
        qty = await _resolve_close_qty(state)
        if qty <= 0:
            state.order = OrderResult(
                status="skipped",
                message=f"CLOSE_LONG on {state.symbol}: no open agent position found (possibly closed by SL).",
            )
            logger.warning(
                "[Executor] CLOSE_LONG skipped — no open position for %s",
                state.symbol,
            )
            return state

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
    )
    logger.info("[Executor] result: status=%s %s", state.order.status, state.order.message)
    return state


async def _resolve_close_qty(state: AgentState) -> float:
    """Return the quantity of the agent-owned open position on
    ``state.symbol``, or 0.0 if none is found.

    Re-reads the live DB (D13): the cached ``portfolio`` snapshot in
    ``state`` may be stale by the time the executor runs if the SL
    monitor closed the position mid-cycle.
    """
    from trdex.storage.portfolio_repo import PortfolioRepository

    if state.session_factory is None:
        return 0.0
    try:
        async with state.session_factory() as session:
            repo = PortfolioRepository(session)
            positions = await repo.get_open_positions()
            for p in positions:
                if p.symbol == state.symbol and p.source == "agent":
                    return float(p.amount)
    except Exception:
        logger.exception(
            "[Executor] failed to resolve close qty for %s", state.symbol
        )
    return 0.0
