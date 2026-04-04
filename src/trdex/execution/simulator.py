"""Paper trading simulator — executes orders without real money."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from trdex.execution.gateway import ExecutionGateway
from trdex.execution.models import ExecutionResult, Order

logger = logging.getLogger(__name__)

# Default simulated fee rate (0.1% taker fee, Binance standard)
DEFAULT_FEE_RATE = Decimal("0.001")


class Simulator(ExecutionGateway):
    """Paper trading engine.

    Simulates order execution with configurable fee and slippage.
    Logs every trade to terminal for immediate feedback.
    """

    def __init__(self, fee_rate: Decimal = DEFAULT_FEE_RATE) -> None:
        self.fee_rate = fee_rate
        self._orders: dict[str, Order] = {}

    async def execute(self, order: Order) -> ExecutionResult:
        order_id = str(uuid.uuid4())[:8]

        # For market orders, use the order price as fill price
        # In a real simulator, this would use current market price + slippage
        fill_price = order.price or Decimal("0")
        fee = order.amount * fill_price * self.fee_rate

        result = ExecutionResult(
            order_id=order_id,
            symbol=order.symbol,
            side=order.side,
            filled_amount=order.amount,
            filled_price=fill_price,
            fee=fee,
            timestamp=datetime.now(UTC),
            simulated=True,
        )

        logger.info(
            "[SIM] %s %s %s @ %s (fee: %s) [%s]",
            order.side.value.upper(),
            order.amount,
            order.symbol,
            fill_price,
            fee,
            order_id,
        )

        return result

    async def cancel(self, order_id: str) -> bool:
        if order_id in self._orders:
            del self._orders[order_id]
            logger.info("[SIM] Cancelled order %s", order_id)
            return True
        return False
