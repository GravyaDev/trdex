"""Price feed manager — unified access to multiple feeds."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trdex.market.feeds.base import PriceFeed
    from trdex.market.models import OHLCV, Ticker

logger = logging.getLogger(__name__)


class FeedError(RuntimeError):
    """Raised when a feed operation fails."""


class ConfigurationError(RuntimeError):
    """Raised when the system is misconfigured (e.g. no feeds registered)."""


class PriceFeedManager:
    """Manages multiple price feeds with routing and failover."""

    def __init__(self) -> None:
        self._feeds: dict[str, PriceFeed] = {}

    def register(self, feed: PriceFeed) -> None:
        """Register a price feed by its name."""
        self._feeds[feed.name] = feed
        logger.info("Registered feed: %s", feed.name)

    def _check_feeds(self) -> None:
        """Raise ConfigurationError if no feeds are registered."""
        if not self._feeds:
            msg = "No feeds registered. Register at least one feed before requesting data."
            raise ConfigurationError(msg)

    async def get_ticker(self, symbol: str, source: str | None = None) -> Ticker:
        """Get ticker from a specific source, or try all feeds."""
        self._check_feeds()

        if source and source in self._feeds:
            try:
                return await self._feeds[source].get_ticker(symbol)
            except Exception as e:
                logger.warning("Feed %s failed for %s: %s", source, symbol, e)
                raise FeedError(f"Feed {source} failed for ticker {symbol}") from e

        # Try each feed in order until one succeeds
        last_error: Exception | None = None
        for feed in self._feeds.values():
            try:
                return await feed.get_ticker(symbol)
            except Exception as e:
                last_error = e
                logger.warning("Feed %s failed for %s: %s", feed.name, symbol, e)

        msg = f"All feeds failed for ticker {symbol}"
        raise FeedError(msg) from last_error

    async def get_ohlcv(
        self, symbol: str, timeframe: str = "1m", limit: int = 100, source: str | None = None
    ) -> list[OHLCV]:
        """Get OHLCV from a specific source, or try all feeds."""
        self._check_feeds()

        if source and source in self._feeds:
            try:
                return await self._feeds[source].get_ohlcv(symbol, timeframe, limit)
            except Exception as e:
                logger.warning("Feed %s failed for OHLCV %s: %s", source, symbol, e)
                raise FeedError(f"Feed {source} failed for OHLCV {symbol}") from e

        last_error: Exception | None = None
        for feed in self._feeds.values():
            try:
                return await feed.get_ohlcv(symbol, timeframe, limit)
            except Exception as e:
                last_error = e
                logger.warning("Feed %s failed for OHLCV %s: %s", feed.name, symbol, e)

        msg = f"All feeds failed for OHLCV {symbol}"
        raise FeedError(msg) from last_error

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
