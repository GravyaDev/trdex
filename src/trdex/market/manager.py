"""Price feed manager — unified access to multiple feeds."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from trdex.market.rate_limiter import RateLimiter

if TYPE_CHECKING:
    from trdex.market.feeds.base import PriceFeed
    from trdex.market.models import OHLCV, Ticker

logger = logging.getLogger(__name__)

# Conservative RPM defaults per provider (based on official free tier docs, verified 2026-04-06)
_DEFAULT_RPM: dict[str, int] = {
    "binance": 120,         # 1200 weight/min; CCXT manages internally, this is safety net
    "binance_ws": 999,      # WebSocket — not request-gated
    "coingecko": 25,        # Demo plan: ~30 calls/min (varies with traffic)
    "cryptocompare": 50,    # CoinDesk-acquired; conservative estimate, verify after migration
    "alphavantage": 1,      # Free: 25 req/DAY — extreme caution required
    "forex": 1,             # Free: 100 req/MONTH — must be extremely conservative
    "freecryptoapi": 50,    # Unverified; conservative default
}


class FeedError(RuntimeError):
    """Raised when a feed operation fails."""


class ConfigurationError(RuntimeError):
    """Raised when the system is misconfigured (e.g. no feeds registered)."""


class PriceFeedManager:
    """Manages multiple price feeds with routing and failover.

    Each registered feed automatically gets a RateLimiter with
    provider-appropriate RPM. The limiter's convex throttle and circuit
    breaker protect against exchange bans.
    """

    def __init__(self) -> None:
        self._feeds: dict[str, PriceFeed] = {}
        self._limiters: dict[str, RateLimiter] = {}

    def register(self, feed: PriceFeed, rpm: int | None = None) -> None:
        """Register a price feed with its rate limiter.

        Args:
            feed: PriceFeed implementation to register.
            rpm: Override requests-per-minute for this feed. If None,
                 uses the provider default from _DEFAULT_RPM, or 10 as fallback.
        """
        self._feeds[feed.name] = feed
        effective_rpm = rpm or _DEFAULT_RPM.get(feed.name, 10)
        self._limiters[feed.name] = RateLimiter(
            name=feed.name,
            default_rpm=effective_rpm,
        )
        logger.info("Registered feed: %s (rate limit: %d rpm)", feed.name, effective_rpm)

    def _check_feeds(self) -> None:
        """Raise ConfigurationError if no feeds are registered."""
        if not self._feeds:
            msg = "No feeds registered. Register at least one feed before requesting data."
            raise ConfigurationError(msg)

    async def _rate_limited_call(self, feed_name: str, coro):
        """Wrap an async feed call with rate limiter acquire/report."""
        limiter = self._limiters.get(feed_name)
        if limiter:
            await limiter.acquire()
        try:
            result = await coro
            if limiter:
                limiter.report_success()
            return result
        except Exception as e:
            if limiter and _is_rate_limit_error(e):
                limiter.report_rate_limit()
            raise

    async def get_ticker(self, symbol: str, source: str | None = None) -> Ticker:
        """Get ticker from a specific source, or try all feeds."""
        self._check_feeds()

        if source and source in self._feeds:
            try:
                return await self._rate_limited_call(
                    source, self._feeds[source].get_ticker(symbol),
                )
            except Exception as e:
                logger.warning("Feed %s failed for %s: %s", source, symbol, e)
                raise FeedError(f"Feed {source} failed for ticker {symbol}") from e

        # Try each feed in order until one succeeds
        last_error: Exception | None = None
        for feed in self._feeds.values():
            try:
                return await self._rate_limited_call(
                    feed.name, feed.get_ticker(symbol),
                )
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
                return await self._rate_limited_call(
                    source, self._feeds[source].get_ohlcv(symbol, timeframe, limit),
                )
            except Exception as e:
                logger.warning("Feed %s failed for OHLCV %s: %s", source, symbol, e)
                raise FeedError(f"Feed {source} failed for OHLCV {symbol}") from e

        last_error: Exception | None = None
        for feed in self._feeds.values():
            try:
                return await self._rate_limited_call(
                    feed.name, feed.get_ohlcv(symbol, timeframe, limit),
                )
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

    def get_limiter(self, feed_name: str) -> RateLimiter | None:
        """Access a feed's rate limiter (for monitoring/testing)."""
        return self._limiters.get(feed_name)


def _is_rate_limit_error(exc: Exception) -> bool:
    """Detect rate-limit errors from various APIs/libraries."""
    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
        return True
    # CCXT-specific
    cls_name = type(exc).__name__
    if cls_name in ("RateLimitExceeded", "DDoSProtection"):
        return True
    return False
