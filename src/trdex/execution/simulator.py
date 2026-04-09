"""Paper trading simulator — executes orders without real money."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal

from trdex.execution.gateway import ExecutionGateway
from trdex.execution.models import ExecutionResult, Order

logger = logging.getLogger(__name__)

# Default simulated fee rate (0.1% taker fee, Binance standard)
DEFAULT_FEE_RATE = Decimal("0.001")

# Cosmetic quantization used ONLY for log output. The values stored on
# ExecutionResult keep full precision so downstream consumers (ledger, P&L,
# Sharpe calc) operate on the exact Decimals.
_QTY_Q = Decimal("0.00000001")  # 8 decimals — satoshi resolution
_PRICE_Q = Decimal("0.01")      # 2 decimals — quote currency cents
_FEE_Q = Decimal("0.0001")      # 4 decimals — sub-cent fee precision


def _fmt(value: Decimal, quant: Decimal) -> str:
    """Quantize a Decimal to a fixed scale for human-readable logging."""
    return str(value.quantize(quant, rounding=ROUND_HALF_EVEN))


class Simulator(ExecutionGateway):
    """Paper trading engine.

    Simulates order execution with configurable fee and slippage.
    Logs every trade to terminal for immediate feedback.
    """

    def __init__(self, fee_rate: Decimal = DEFAULT_FEE_RATE) -> None:
        self.fee_rate = fee_rate
        self._orders: dict[str, Order] = {}

    async def execute(self, order: Order) -> ExecutionResult:
        if order.price is None:
            raise ValueError(
                f"Market order for {order.symbol} has no price. "
                "Inject current market price before calling execute()."
            )

        # Truncate quantity to the exchange's lot size step. Without
        # this, the simulator produces fractional amounts like 6407.7529
        # ENJ when ENJ's step_size is 1 whole token — fine in simulation
        # but rejected by Binance in live mode. Truncating here makes
        # the simulation realistic and the P&L numbers accurate.
        from trdex.market import specs as market_specs
        amount = market_specs.truncate_qty(order.symbol, order.amount)
        if amount <= 0:
            logger.warning(
                "[SIM] qty truncated to 0 for %s (raw=%s, step=%s) — skipping",
                order.symbol, order.amount, market_specs.get_step_size(order.symbol),
            )
            return ExecutionResult(
                order_id="",
                symbol=order.symbol,
                side=order.side,
                filled_amount=Decimal("0"),
                filled_price=order.price,
                fee=Decimal("0"),
                timestamp=datetime.now(UTC),
                simulated=True,
            )

        order_id = str(uuid.uuid4())[:8]
        fill_price = order.price
        fee = amount * fill_price * self.fee_rate

        self._orders[order_id] = order

        result = ExecutionResult(
            order_id=order_id,
            symbol=order.symbol,
            side=order.side,
            filled_amount=amount,
            filled_price=fill_price,
            fee=fee,
            timestamp=datetime.now(UTC),
            simulated=True,
        )

        logger.info(
            "[SIM] %s %s %s @ %s (fee: %s) [%s]",
            order.side.value.upper(),
            _fmt(amount, _QTY_Q),
            order.symbol,
            _fmt(fill_price, _PRICE_Q),
            _fmt(fee, _FEE_Q),
            order_id,
        )

        return result

    async def cancel(self, order_id: str) -> bool:
        if order_id in self._orders:
            del self._orders[order_id]
            logger.info("[SIM] Cancelled order %s", order_id)
            return True
        return False
