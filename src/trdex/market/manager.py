"""Price feed manager — unified access to multiple feeds."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trdex.market.feeds.base import PriceFeed
    from trdex.market.models import OHLCV, Ticker

logger = logging.getLogger(__name__)


class PriceFeedManager:
    """Manages multiple price feeds with routing and failover."""

    def __init__(self) -> None:
        self._feeds: dict[str, PriceFeed] = {}

    def register(self, feed: PriceFeed) -> None:
        """Register a price feed by its name."""
        self._feeds[feed.name] = feed
        logger.info("Registered feed: %s", feed.name)

    async def get_ticker(self, symbol: str, source: str | None = None) -> Ticker:
        """Get ticker from a specific source, or try all feeds."""
        if source and source in self._feeds:
            return await self._feeds[source].get_ticker(symbol)

        # Try each feed in order until one succeeds
        last_error: Exception | None = None
        for feed in self._feeds.values():
            try:
                return await feed.get_ticker(symbol)
            except Exception as e:
                last_error = e
                logger.warning("Feed %s failed for %s: %s", feed.name, symbol, e)

        msg = f"All feeds failed for ticker {symbol}"
        raise RuntimeError(msg) from last_error

    async def get_ohlcv(
        self, symbol: str, timeframe: str = "1m", limit: int = 100, source: str | None = None
    ) -> list[OHLCV]:
        """Get OHLCV from a specific source, or try all feeds."""
        if source and source in self._feeds:
            return await self._feeds[source].get_ohlcv(symbol, timeframe, limit)

        last_error: Exception | None = None
        for feed in self._feeds.values():
            try:
                return await feed.get_ohlcv(symbol, timeframe, limit)
            except Exception as e:
                last_error = e
                logger.warning("Feed %s failed for OHLCV %s: %s", feed.name, symbol, e)

        msg = f"All feeds failed for OHLCV {symbol}"
        raise RuntimeError(msg) from last_error

    async def close_all(self) -> None:
        """Close all registered feeds."""
        for feed in self._feeds.values():
            try:
                await feed.close()
            except Exception:
                logger.exception("Error closing feed %s", feed.name)

    @property
    def feeds(self) -> dict[str, PriceFeed]:
        return dict(self._feeds)
