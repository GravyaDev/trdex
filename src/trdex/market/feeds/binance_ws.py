"""Binance WebSocket price feed via ccxt.pro."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from trdex.config import get_settings
from trdex.market.feeds.base import PriceFeed
from trdex.market.models import OHLCV, Ticker

logger = logging.getLogger(__name__)


class BinanceWSFeed(PriceFeed):
    """Real-time Binance ticker feed via ccxt.pro WebSocket.

    Maintains a per-symbol price cache updated by background tasks.
    Falls back to a one-shot watch_ticker call for cache misses.

    Usage:
        feed = BinanceWSFeed()
        await feed.subscribe_ticker("BTC/USDT", callback)
        ticker = await feed.get_ticker("BTC/USDT")  # instant cache lookup
        await feed.close()
    """

    def __init__(self) -> None:
        import ccxt.pro as ccxtpro  # type: ignore[import-untyped]

        s = get_settings()
        self._exchange = ccxtpro.binance(
            {
                "apiKey": s.binance_api_key or None,
                "secret": s.binance_api_secret or None,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            }
        )
        self._cache: dict[str, Ticker] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def name(self) -> str:
        return "binance_ws"

    async def subscribe_ticker(self, symbol: str, callback: Callable[[Ticker], Any] | None = None) -> None:
        """Start a background task that streams ticks and updates the cache."""
        if symbol in self._tasks and not self._tasks[symbol].done():
            return  # already streaming

        async def _stream() -> None:
            logger.info("[BinanceWS] subscribing %s", symbol)
            while True:
                try:
                    raw = await self._exchange.watch_ticker(symbol)
                    price = raw.get("last") or raw.get("close") or 0.0
                    ts = raw.get("timestamp")
                    timestamp = (
                        datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                        if ts
                        else datetime.now(tz=timezone.utc)
                    )
                    ticker = Ticker(
                        symbol=symbol,
                        price=Decimal(str(price)),
                        timestamp=timestamp,
                        source=self.name,
                    )
                    self._cache[symbol] = ticker
                    if callback:
                        callback(ticker)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.warning("[BinanceWS] error streaming %s: %s", symbol, exc)
                    await asyncio.sleep(1)

        self._tasks[symbol] = asyncio.create_task(_stream(), name=f"ws-{symbol}")

    async def get_ticker(self, symbol: str) -> Ticker:
        """Return cached ticker, or fetch once if cache is empty."""
        if symbol in self._cache:
            return self._cache[symbol]
        # Cache miss — subscribe + wait for first tick
        await self.subscribe_ticker(symbol)
        for _ in range(50):  # wait up to 5s
            await asyncio.sleep(0.1)
            if symbol in self._cache:
                return self._cache[symbol]
        raise RuntimeError(f"BinanceWSFeed: no tick received for {symbol} within timeout")

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
        since: int | None = None,  # noqa: ARG002 - WS feed does not honour historical since
    ) -> list[OHLCV]:
        """OHLCV via REST — WS feed is for tickers only."""
        import ccxt.async_support as ccxt_rest

        s = get_settings()
        exchange = ccxt_rest.binance(
            {
                "apiKey": s.binance_api_key or None,
                "secret": s.binance_api_secret or None,
                "enableRateLimit": True,
            }
        )
        try:
            raw = await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        finally:
            await exchange.close()

        return [
            OHLCV(
                timestamp=datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc),
                open=Decimal(str(row[1])),
                high=Decimal(str(row[2])),
                low=Decimal(str(row[3])),
                close=Decimal(str(row[4])),
                volume=Decimal(str(row[5])),
            )
            for row in raw
        ]

    async def close(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        await self._exchange.close()
        logger.info("[BinanceWS] closed")
