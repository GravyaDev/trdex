"""LivePerpExecutor — Binance USDⓈ-M perpetual futures via CCXT.

Used in live mode when ``thresholds.execution_venue = usdm`` (the
default; ``trdex.risk.leverage``). Every entry is an isolated-margin
position at the leverage the Risk node chose; closes are reduce-only so
they can never open the other side. CCXT's built-in rate limiter
(``enableRateLimit``) paces the requests; Binance errors propagate to
the gateway, which reports the order as rejected.

Assumes a one-way position mode account (Binance's default): trdex
never holds both sides of a symbol (Risk node and Telegram guards).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from trdex.execution.gateway import ExecutionGateway
from trdex.execution.live_executor import _parse_ccxt_result
from trdex.execution.models import ExecutionResult, Order

if TYPE_CHECKING:
    from trdex.config import Settings

logger = logging.getLogger(__name__)


def perp_symbol(symbol: str) -> str:
    """``BTC/USDT`` -> ``BTC/USDT:USDT`` (CCXT unified linear perpetual)."""
    if ":" in symbol or "/" not in symbol:
        return symbol
    return f"{symbol}:{symbol.split('/', 1)[1]}"


class LivePerpExecutor(ExecutionGateway):
    def __init__(self, exchange: Any) -> None:
        self._exchange = exchange
        self._markets_loaded = False
        self._leverage_set: dict[str, int] = {}  # symbol -> leverage configured on the exchange

    @classmethod
    def from_settings(cls, settings: Settings) -> LivePerpExecutor:
        try:
            import ccxt.async_support as ccxt
        except ImportError as e:
            raise RuntimeError("ccxt required for live execution") from e

        config: dict[str, Any] = {
            "apiKey": settings.binance_api_key,
            "secret": settings.binance_effective_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        }
        exchange = ccxt.binanceusdm(config)
        if settings.binance_testnet:
            # The USDⓈ-M sandbox (testnet) is gone: CCXT refuses it for
            # futures. Binance's demo trading replaces it and needs API keys
            # created on demo.binance.com.
            exchange.enable_demo_trading(True)
            logger.info("[LivePerp] using Binance USDⓈ-M DEMO TRADING (demo.binance.com keys)")
        else:
            logger.warning("[LivePerp] using Binance USDⓈ-M PRODUCTION — real money at risk")
        return cls(exchange)

    async def _load_markets(self) -> None:
        if not self._markets_loaded:
            await self._exchange.load_markets()
            self._markets_loaded = True

    async def _ensure_isolated(self, symbol: str, leverage: int) -> None:
        """Isolated margin and the entry's leverage on ``symbol`` (cached)."""
        if self._leverage_set.get(symbol) == leverage:
            return
        try:
            await self._exchange.set_margin_mode("isolated", symbol)
        except Exception as exc:
            # Binance answers -4046 "No need to change margin type" when
            # it is already isolated; anything else is a real failure.
            if "no need to change margin type" not in str(exc).lower():
                raise
        await self._exchange.set_leverage(leverage, symbol)
        self._leverage_set[symbol] = leverage

    async def execute(self, order: Order) -> ExecutionResult:
        symbol = perp_symbol(order.symbol)
        await self._load_markets()
        amount = float(self._exchange.amount_to_precision(symbol, float(order.amount)))
        if amount <= 0:
            raise ValueError(f"LivePerp: qty rounds to 0 for {symbol} (raw={order.amount})")
        params: dict[str, Any] = {}
        if order.reduce_only:
            params["reduceOnly"] = True
        else:
            await self._ensure_isolated(symbol, max(1, int(order.leverage)))
        raw = await self._exchange.create_order(
            symbol=symbol, type="market", side=order.side.value, amount=amount, params=params
        )
        order_id = str(raw["id"])
        logger.info(
            "[LivePerp] market order id=%s %s %s qty=%s lev=%sx reduce_only=%s",
            order_id,
            order.side.value.upper(),
            symbol,
            amount,
            order.leverage,
            order.reduce_only,
        )
        filled = await self._exchange.fetch_order(order_id, symbol)
        result = _parse_ccxt_result(filled, simulated=False)
        # Back to the symbol trdex uses everywhere else.
        return result.model_copy(update={"symbol": order.symbol})

    async def cancel(self, order_id: str, symbol: str | None = None) -> bool:
        try:
            await self._exchange.cancel_order(order_id, perp_symbol(symbol) if symbol else None)
            return True
        except Exception:
            logger.exception("[LivePerp] failed to cancel order %s", order_id)
            return False

    async def close(self) -> None:
        try:
            await self._exchange.close()
        except Exception:
            logger.exception("[LivePerp] error closing exchange connection")
