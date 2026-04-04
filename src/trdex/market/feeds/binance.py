"""Binance REST price feed via CCXT."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import ccxt.async_support as ccxt

from trdex.config import get_settings
from trdex.market.feeds.base import PriceFeed
from trdex.market.models import OHLCV, Ticker

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class BinanceFeed(PriceFeed):
    """Binance market data via CCXT async REST API.

    Supports ticker and OHLCV. WebSocket feed is Phase 4.
    Uses public endpoints when no API key is configured (read-only, rate-limited).

    Usage:
        async with BinanceFeed() as feed:
            ticker = await feed.get_ticker("BTC/USDT")
            candles = await feed.get_ohlcv("BTC/USDT", timeframe="1h", limit=50)
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._exchange = ccxt.binance(
            {
                "apiKey": settings.binance_api_key or None,
                "secret": settings.binance_api_secret or None,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            }
        )

    async def __aenter__(self) -> BinanceFeed:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    @property
    def name(self) -> str:
        return "binance"

    async def get_ticker(self, symbol: str) -> Ticker:
        """Fetch current best-bid/ask midpoint price."""
        raw: dict[str, Any] = await self._exchange.fetch_ticker(symbol)
        price = raw.get("last") or raw.get("close") or 0.0
        ts = raw.get("timestamp")
        timestamp = (
            datetime.fromtimestamp(ts / 1000, tz=timezone.utc) if ts else datetime.now(tz=timezone.utc)
        )
        logger.debug("[Binance] ticker %s = %s", symbol, price)
        return Ticker(
            symbol=symbol,
            price=Decimal(str(price)),
            timestamp=timestamp,
            source=self.name,
        )

    async def get_ohlcv(
        self, symbol: str, timeframe: str = "1h", limit: int = 100
    ) -> list[OHLCV]:
        """Fetch historical OHLCV candles."""
        raw: list[list[Any]] = await self._exchange.fetch_ohlcv(
            symbol, timeframe=timeframe, limit=limit
        )
        candles = []
        for entry in raw:
            ts_ms, o, h, l, c, v = entry
            candles.append(
                OHLCV(
                    timestamp=datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                    open=Decimal(str(o)),
                    high=Decimal(str(h)),
                    low=Decimal(str(l)),
                    close=Decimal(str(c)),
                    volume=Decimal(str(v)),
                )
            )
        logger.debug("[Binance] ohlcv %s timeframe=%s candles=%d", symbol, timeframe, len(candles))
        return candles

    async def subscribe_ticker(self, symbol: str, callback: Callable[[Ticker], Any]) -> None:
        """WebSocket subscription — not implemented until Phase 4."""
        raise NotImplementedError("WebSocket feed is Phase 4. Use get_ticker() for polling.")

    async def close(self) -> None:
        await self._exchange.close()
