"""LiveExecutor — routes orders to a real exchange via CCXT (Binance testnet by default)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from trdex.execution.gateway import ExecutionGateway
from trdex.execution.models import ExecutionResult, Order, Side

if TYPE_CHECKING:
    from trdex.config import Settings

logger = logging.getLogger(__name__)


def _parse_ccxt_result(raw: dict[str, Any], simulated: bool = False) -> ExecutionResult:
    """Convert a CCXT order dict to an ExecutionResult."""
    filled = Decimal(str(raw.get("filled") or raw.get("amount") or 0))
    price = Decimal(str(raw.get("average") or raw.get("price") or 0))
    fee_cost = Decimal(str((raw.get("fee") or {}).get("cost") or 0))
    ts_raw = raw.get("timestamp")
    ts = datetime.fromtimestamp(ts_raw / 1000, tz=timezone.utc) if ts_raw else datetime.now(tz=timezone.utc)
    side = Side(raw.get("side", "buy").lower())

    return ExecutionResult(
        order_id=str(raw.get("id") or uuid.uuid4()),
        symbol=raw.get("symbol", ""),
        side=side,
        filled_amount=filled,
        filled_price=price,
        fee=fee_cost,
        timestamp=ts,
        simulated=simulated,
    )


class LiveExecutor(ExecutionGateway):
    """Routes orders to a real exchange via CCXT.

    Default target: Binance testnet (spot).
    Can be pointed at any CCXT-compatible exchange by passing a pre-built exchange object.

    Usage:
        executor = LiveExecutor.from_settings(settings)
        result = await executor.execute(order)
        await executor.close()
    """

    def __init__(self, exchange: Any) -> None:
        """
        Args:
            exchange: A CCXT async exchange instance (e.g. ccxt.async_support.binance(...)).
        """
        self._exchange = exchange

    @classmethod
    def from_settings(cls, settings: Settings) -> LiveExecutor:
        """Build a LiveExecutor pointed at Binance testnet using credentials from Settings."""
        try:
            import ccxt.async_support as ccxt  # type: ignore[import-untyped]
        except ImportError as e:
            raise RuntimeError(
                "ccxt is required for live execution. Install it with: pip install ccxt"
            ) from e

        exchange = ccxt.binance({
            "apiKey": settings.binance_api_key,
            "secret": settings.binance_api_secret,
            "options": {"defaultType": "spot"},
            "urls": {
                "api": {
                    "public": "https://testnet.binance.vision/api",
                    "private": "https://testnet.binance.vision/api",
                }
            },
        })
        return cls(exchange)

    async def execute(self, order: Order) -> ExecutionResult:
        """Send order to exchange, wait for fill, return result."""
        if order.price is None:
            raise ValueError(f"LiveExecutor requires a price for {order.symbol}.")

        # CCXT symbol format: "BTC/USDT" (already our format)
        try:
            raw = await self._exchange.create_order(
                symbol=order.symbol,
                type="limit",
                side=order.side.value,          # "buy" or "sell"
                amount=float(order.amount),
                price=float(order.price),
            )
            order_id = str(raw["id"])
            logger.info("[Live] order placed id=%s %s %s @ %s",
                        order_id, order.side.value.upper(), order.amount, order.price)

            # Fetch the actual fill (may be immediate on testnet)
            filled_raw = await self._exchange.fetch_order(order_id, order.symbol)
            result = _parse_ccxt_result(filled_raw, simulated=False)
            logger.info("[Live] fill confirmed id=%s filled=%s @ %s",
                        order_id, result.filled_amount, result.filled_price)
            return result

        except Exception as exc:
            logger.exception("[Live] order failed for %s: %s", order.symbol, exc)
            raise

    async def cancel(self, order_id: str) -> bool:
        try:
            await self._exchange.cancel_order(order_id)
            logger.info("[Live] cancelled order %s", order_id)
            return True
        except Exception:
            logger.exception("[Live] failed to cancel order %s", order_id)
            return False

    async def close(self) -> None:
        """Release the underlying CCXT exchange connection."""
        try:
            await self._exchange.close()
        except Exception:
            logger.exception("[Live] error closing exchange connection")
