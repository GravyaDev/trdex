"""Executor Agent — sends approved orders through the execution gateway."""

from __future__ import annotations

import logging

from trdex.agents.memory_helpers import attach_memory_snapshot
from trdex.agents.state import AgentState, OrderResult

logger = logging.getLogger(__name__)


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

    signal = state.analysis.signal
    price = state.market.price if state.market else 0.0

    if price <= 0:
        state.order = OrderResult(status="rejected", message="No valid market price.")
        logger.warning("[Executor] rejected — price=0 for %s", state.symbol)
        return state

    # Real position sizing: fraction of current equity divided by price
    equity = state.portfolio.equity if state.portfolio.equity > 0 else 10_000.0
    trade_value = equity * state.risk.position_size
    qty = trade_value / price

    # Resolve gateway — use injected one or create a default instance
    gateway = state.gateway
    if gateway is None:
        from trdex.execution.default_gateway import DefaultExecutionGateway
        gateway = DefaultExecutionGateway.create()

    logger.info(
        "[Executor] %s %s qty=%.6f @ %.4f value=%.2f",
        signal, state.symbol, qty, price, trade_value,
    )

    state.order = await gateway.place(
        symbol=state.symbol,
        direction=signal,  # "BUY" or "SELL"
        qty=qty,
        price=price,
        idempotency_key=f"agent:{state.run_id}",
    )
    logger.info("[Executor] result: status=%s %s", state.order.status, state.order.message)
    return state
