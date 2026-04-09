"""LiveExecutor — routes orders to a real exchange via CCXT.

Supports both Binance testnet (for testing) and production.
Controlled by TRDEX_BINANCE_TESTNET env var (default: true = testnet).
"""

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

    Usage:
        executor = LiveExecutor.from_settings(settings)
        result = await executor.execute(order)
        await executor.close()
    """

    def __init__(self, exchange: Any) -> None:
        self._exchange = exchange

    @classmethod
    def from_settings(cls, settings: Settings) -> LiveExecutor:
        """Build a LiveExecutor from Settings.

        Uses Binance testnet by default (TRDEX_BINANCE_TESTNET=true).
        Set to false for production Binance (requires real API keys
        and real money — never do this without passing the readiness
        gate first).
        """
        try:
            import ccxt.async_support as ccxt
        except ImportError as e:
            raise RuntimeError("ccxt required for live execution") from e

        secret = settings.binance_effective_secret
        is_pem = "PRIVATE KEY" in secret
        config: dict[str, Any] = {
            "apiKey": settings.binance_api_key,
            "secret": secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
        if is_pem:
            logger.info("[Live] using Ed25519 PEM key for authentication")

        if settings.binance_testnet:
            config["urls"] = {
                "api": {
                    "public": "https://testnet.binance.vision/api",
                    "private": "https://testnet.binance.vision/api",
                }
            }
            logger.info("[Live] using Binance TESTNET")
        else:
            logger.warning("[Live] using Binance PRODUCTION — real money at risk")

        exchange = ccxt.binance(config)
        return cls(exchange)

    async def execute(self, order: Order) -> ExecutionResult:
        """Send order to exchange, wait for fill, return result."""
        from trdex.market import specs as market_specs

        # Truncate quantity to exchange lot size (same as Simulator)
        amount = market_specs.truncate_qty(order.symbol, order.amount)
        if amount <= 0:
            raise ValueError(
                f"LiveExecutor: qty truncated to 0 for {order.symbol} "
                f"(raw={order.amount}, step={market_specs.get_step_size(order.symbol)})"
            )

        try:
            # Use market order for immediate execution. Limit orders
            # on testnet often hang unfilled because the order book
            # is thin. Market orders fill instantly.
            raw = await self._exchange.create_order(
                symbol=order.symbol,
                type="market",
                side=order.side.value,
                amount=float(amount),
            )
            order_id = str(raw["id"])
            logger.info(
                "[Live] market order placed id=%s %s %s qty=%s",
                order_id, order.side.value.upper(), order.symbol, amount,
            )

            # Fetch the fill details (price, fee, filled amount)
            filled_raw = await self._exchange.fetch_order(order_id, order.symbol)
            result = _parse_ccxt_result(filled_raw, simulated=False)
            logger.info(
                "[Live] fill confirmed id=%s filled=%s @ %s fee=%s",
                order_id, result.filled_amount, result.filled_price, result.fee,
            )
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
