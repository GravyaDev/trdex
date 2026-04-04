"""Executor Agent — routes approved orders to simulator or live gateway."""

from __future__ import annotations

import logging
import uuid

from trdex.agents.state import AgentState, OrderResult
from trdex.config import get_settings

logger = logging.getLogger(__name__)


async def executor_node(state: AgentState) -> AgentState:
    """Execute the trade if Risk approved it.

    In simulation mode: logs the order and returns a synthetic fill.
    In live mode: would route to the live execution gateway (Phase 5).
    """
    if not state.risk.approved:
        state.order = OrderResult(
            status="skipped",
            message=f"Skipped: {state.risk.reason}",
        )
        logger.info("[Executor] skipped — %s", state.risk.reason)
        return state

    settings = get_settings()
    signal = state.analysis.signal
    price = state.market.price if state.market else 0.0
    qty = state.risk.position_size  # fraction; real sizing needs portfolio value

    order_id = str(uuid.uuid4())[:8]

    if settings.mode.value == "simulation":
        logger.info(
            "[Executor][SIM] %s %s qty=%.4f @ %.4f (order=%s)",
            signal, state.symbol, qty, price, order_id,
        )
        state.order = OrderResult(
            order_id=order_id,
            status="filled",
            filled_price=price,
            filled_qty=qty,
            message=f"Simulated {signal} fill @ {price}",
        )
    else:
        # Phase 5: wire to live execution gateway
        logger.error("[Executor] Live gateway not implemented.")
        state.order = OrderResult(
            status="rejected",
            message="Live gateway not implemented.",
        )

    return state
