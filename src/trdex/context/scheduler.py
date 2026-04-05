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

    def __init__(self, interval_seconds: int = 300) -> None:
        self._interval = interval_seconds
        self._sources: list[NewsSource] = []
        self._symbols: list[str] = []
        self._pipeline = ContextIngestionPipeline()
        self._task: asyncio.Task[None] | None = None
        self._last_run: datetime | None = None

    def register(self, source: NewsSource) -> None:
        """Add a news source to the scheduler."""
        self._sources.append(source)
        logger.info("[scheduler] registered source: %s", source.name)

    def set_symbols(self, symbols: list[str]) -> None:
        """Set the list of symbols to fetch news for (in addition to global news)."""
        self._symbols = list(symbols)

    async def start(self) -> None:
        """Start the background ingestion loop."""
        await self._pipeline.setup()
        self._task = asyncio.create_task(self._loop(), name="ingestion-scheduler")
        logger.info("[scheduler] started — interval=%ds sources=%d", self._interval, len(self._sources))

    async def stop(self) -> None:
        """Cancel the background loop and close all sources."""
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
                    logger.exception(
                        "[scheduler] fetch failed: source=%s symbol=%s", source.name, symbol
                    )

        self._last_run = datetime.now(tz=timezone.utc)
        return total

    async def _loop(self) -> None:
        """Background loop: run ingestion every `_interval` seconds."""
        while True:
            try:
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
            "running": self._task is not None and not self._task.done(),
            "last_run": self._last_run.isoformat() if self._last_run else None,
        }
