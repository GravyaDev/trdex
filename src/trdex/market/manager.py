"""Price feed manager — unified access to multiple feeds."""

from __future__ import annotations

import asyncio
import logging
import statistics
from decimal import Decimal
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


# ── Runtime-configurable feed selection for aggregation ────────────────
# The user selects which feeds to use via the dashboard. If empty/None,
# all registered feeds are queried.

_selected_feeds: list[str] | None = None


def set_selected_feeds(names: list[str]) -> None:
    """Set which feeds are used for aggregated price queries."""
    global _selected_feeds
    _selected_feeds = list(names) if names else None
    logger.info("[FeedManager] aggregation feeds set to: %s", _selected_feeds or "ALL")


def get_selected_feeds() -> list[str] | None:
    """Return the current feed selection, or None (= all)."""
    return _selected_feeds


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

    async def get_ticker_aggregated(
        self,
        symbol: str,
        feed_names: list[str] | None = None,
        outlier_pct: float = 0.02,
    ) -> Ticker:
        """Query selected feeds in parallel and return the median price.

        Args:
            symbol: Trading pair (e.g. "BTC/USDT").
            feed_names: List of feed names to query (e.g. ["binance", "coingecko"]).
                        If None or empty, queries ALL registered feeds.
            outlier_pct: Max deviation from median before a price is discarded
                         as an outlier (default 2%).

        If only 1 feed is selected (or only 1 responds), returns that
        feed's price directly (no median needed). If 2+ respond, returns
        the median after outlier filtering.
        """
        from trdex.market.models import Ticker as TickerModel

        self._check_feeds()

        # Select which feeds to query
        if feed_names:
            selected = {n: f for n, f in self._feeds.items() if n in feed_names}
        else:
            selected = dict(self._feeds)

        if not selected:
            raise FeedError(f"No matching feeds for aggregation: {feed_names}")

        async def _fetch_one(name: str, feed) -> tuple[str, float] | None:
            try:
                t = await self._rate_limited_call(name, feed.get_ticker(symbol))
                return (name, float(t.price))
            except Exception as e:
                logger.debug("Aggregation: feed %s failed for %s: %s", name, symbol, e)
                return None

        results = await asyncio.gather(
            *[_fetch_one(name, feed) for name, feed in selected.items()]
        )
        prices = [(name, price) for r in results if r is not None for name, price in [r]]

        if not prices:
            raise FeedError(f"All selected feeds failed for ticker {symbol}")

        if len(prices) == 1:
            name, price = prices[0]
            return await self.get_ticker(symbol, source=name)

        # Compute median
        price_values = [p for _, p in prices]
        median = statistics.median(price_values)

        # Filter outliers
        filtered = [(n, p) for n, p in prices if abs(p - median) / median <= outlier_pct]
        if not filtered:
            filtered = prices

        final_price = statistics.median([p for _, p in filtered])
        sources = ",".join(n for n, _ in filtered)

        from datetime import datetime, timezone
        logger.info(
            "[Aggregation] %s: %d/%d feeds, median=%.6f, sources=%s",
            symbol, len(filtered), len(prices), final_price, sources,
        )

        return TickerModel(
            symbol=symbol,
            price=Decimal(str(final_price)),
            timestamp=datetime.now(tz=timezone.utc),
            source=f"aggregated({sources})",
        )

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 100,
        source: str | None = None,
        since: int | None = None,
    ) -> list[OHLCV]:
        """Get OHLCV from a specific source, or try all feeds.

        ``since`` is an optional millisecond UTC timestamp forwarded to the
        underlying feed. Feeds that ignore the parameter (most aggregators)
        will return their default range; feeds that honour it (Binance,
        CryptoCompare) use it as the lower bound for the returned candles.
        """
        self._check_feeds()

        if source and source in self._feeds:
            try:
                return await self._rate_limited_call(
                    source,
                    self._feeds[source].get_ohlcv(
                        symbol, timeframe, limit, since=since
                    ),
                )
            except Exception as e:
                logger.warning("Feed %s failed for OHLCV %s: %s", source, symbol, e)
                raise FeedError(f"Feed {source} failed for OHLCV {symbol}") from e

        last_error: Exception | None = None
        for feed in self._feeds.values():
            try:
                return await self._rate_limited_call(
                    feed.name,
                    feed.get_ohlcv(symbol, timeframe, limit, since=since),
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
