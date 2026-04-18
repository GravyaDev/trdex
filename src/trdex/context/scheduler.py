"""IngestionScheduler: periodically fetches news from all sources and ingests into Qdrant."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from trdex.context.ingestion import ContextIngestionPipeline
from trdex.context.news_sources.base import NewsSource
from trdex.context.vector_store import ContextDocument

logger = logging.getLogger(__name__)


class IngestionScheduler:
    """Runs all registered NewsSource implementations on a configurable interval.

    Usage:
        scheduler = IngestionScheduler(interval_seconds=300)
        scheduler.register(CryptoCompareNewsSource(api_key=...))
        scheduler.register(StockDataNewsSource(api_key=...))
        scheduler.set_symbols(["BTC/USDT", "ETH/USDT"])

        await scheduler.start()   # starts background task
        ...
        await scheduler.stop()    # cancels and cleans up
    """

    # Circuit breaker: after N consecutive ingest failures, skip ingestion
    # and back off exponentially. Resets on first success.
    _CB_THRESHOLD = 3       # consecutive failures before tripping
    _CB_MAX_BACKOFF = 1800  # max backoff in seconds (30 min)

    def __init__(self, interval_seconds: int = 300) -> None:
        self._interval = interval_seconds
        self._sources: list[NewsSource] = []
        self._symbols: list[str] = []
        self._pipeline = ContextIngestionPipeline()
        self._task: asyncio.Task[None] | None = None
        self._last_run: datetime | None = None
        self._running = False
        self._consecutive_failures = 0
        self._circuit_open = False

    def register(self, source: NewsSource) -> None:
        """Add a news source to the scheduler."""
        self._sources.append(source)
        logger.info("[scheduler] registered source: %s", source.name)

    def unregister(self, name: str) -> bool:
        """Remove a news source by name. Returns True if found and removed, False otherwise.

        Schedules source.close() as a background task when a running loop is available.
        Safe to call from synchronous context (e.g. dashboard toggle handler).
        """
        for source in self._sources:
            if source.name == name:
                self._sources.remove(source)
                try:
                    asyncio.get_running_loop()  # raises RuntimeError if no loop running
                    asyncio.create_task(source.close())
                except RuntimeError:
                    logger.warning(
                        "[scheduler] no running loop — skipping close() for source: %s", name
                    )
                logger.info("[scheduler] unregistered source: %s", name)
                return True
        return False

    def set_symbols(self, symbols: list[str]) -> None:
        """Set the list of symbols to fetch news for (in addition to global news)."""
        self._symbols = list(symbols)

    async def start(self) -> None:
        """Start the background ingestion loop."""
        await self._pipeline.setup()
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="ingestion-scheduler")
        logger.info("[scheduler] started — interval=%ds sources=%d", self._interval, len(self._sources))

    async def stop(self) -> None:
        """Cancel the background loop and close all sources."""
        self._running = False
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        for source in self._sources:
            try:
                await source.close()
            except Exception:
                logger.exception("[scheduler] error closing source %s", source.name)

    async def run_once(self) -> int:
        """Run a single ingestion cycle immediately. Returns number of docs ingested."""
        total = 0
        cycle_had_failure = False
        fetch_targets: list[str | None] = [None, *self._symbols]  # None = global news

        for source in self._sources:
            for symbol in fetch_targets:
                try:
                    articles = await source.fetch(symbol=symbol, limit=50)
                    docs = [
                        ContextDocument(
                            text=article.full_text,
                            source=article.source,
                            symbol=article.symbol,
                            sentiment=article.sentiment,
                            published_at=article.published_at,
                        )
                        for article in articles
                        if article.full_text.strip()
                    ]
                    if docs:
                        await self._pipeline.ingest(docs)
                        total += len(docs)
                        logger.info(
                            "[scheduler] ingested %d docs from %s (symbol=%s)",
                            len(docs), source.name, symbol,
                        )
                except Exception:
                    cycle_had_failure = True
                    logger.exception(
                        "[scheduler] fetch failed: source=%s symbol=%s", source.name, symbol
                    )

        # Circuit breaker: track consecutive cycle failures
        if cycle_had_failure and total == 0:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._CB_THRESHOLD:
                self._circuit_open = True
                logger.warning(
                    "[scheduler] circuit OPEN after %d consecutive failures — backing off",
                    self._consecutive_failures,
                )
        else:
            if self._circuit_open:
                logger.info("[scheduler] circuit CLOSED — ingestion recovered")
            self._consecutive_failures = 0
            self._circuit_open = False

        self._last_run = datetime.now(tz=timezone.utc)
        return total

    def _backoff_seconds(self) -> int:
        """Exponential backoff: 2^(failures - threshold) * interval, capped."""
        exponent = self._consecutive_failures - self._CB_THRESHOLD
        delay = min(self._interval * (2 ** max(exponent, 0)), self._CB_MAX_BACKOFF)
        return int(delay)

    async def _loop(self) -> None:
        """Background loop: run ingestion every `_interval` seconds."""
        while True:
            try:
                if self._circuit_open:
                    backoff = self._backoff_seconds()
                    logger.info("[scheduler] circuit open — backoff %ds before retry", backoff)
                    await asyncio.sleep(backoff)
                total = await self.run_once()
                logger.info("[scheduler] cycle complete — %d total docs ingested", total)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("[scheduler] unexpected error in ingestion cycle")
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break

    @property
    def status(self) -> dict:
        return {
            "sources": [s.name for s in self._sources],
            "symbols": self._symbols,
            "interval_seconds": self._interval,
            "running": self._running and self._task is not None and not self._task.done(),
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "circuit_open": self._circuit_open,
            "consecutive_failures": self._consecutive_failures,
        }
