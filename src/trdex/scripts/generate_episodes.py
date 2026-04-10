"""Generate market episodes from OHLCV data and store in Qdrant.

Usage:
    python -m trdex.scripts.generate_episodes BTC/USDT --timeframe 1h
    python -m trdex.scripts.generate_episodes --all --timeframe 1h
    python -m trdex.scripts.generate_episodes ETH/USDT --timeframe 4h --days 180

Reads OHLCV candles from TimescaleDB, runs the episode detection algorithm,
embeds narratives via Jina, and upserts into the ``trdex_market_episodes``
Qdrant collection. Idempotent: deterministic doc IDs mean re-runs update
existing points rather than creating duplicates.

Prerequisite: OHLCV data must already be in the DB (run backfill_ohlcv.py first).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone

from trdex.config import get_settings
from trdex.memory.market_episodes import (
    MarketEpisodeService,
    detect_episodes,
)
from trdex.storage.db import get_session_factory
from trdex.storage.ohlcv_repo import OHLCVRepository

logger = logging.getLogger(__name__)

# Jina embedding API has a batch limit; process episodes in chunks
EMBED_BATCH_SIZE = 50


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate market episodes from OHLCV data and store in Qdrant."
    )
    parser.add_argument("symbol", nargs="?", default=None, help="Trading pair, e.g. BTC/USDT")
    parser.add_argument(
        "--all", action="store_true",
        help="Process all symbols from TRDEX_AGENT_SCHEDULER_SYMBOLS",
    )
    parser.add_argument("--timeframe", "-t", default="1h", help="Candle timeframe (default: 1h)")
    parser.add_argument("--days", "-d", type=int, default=None, help="Limit to last N days of data")
    parser.add_argument("--window", "-w", type=int, default=50, help="Episode window size in candles (default: 50)")
    parser.add_argument("--stride", "-s", type=int, default=25, help="Stride between windows (default: 25)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    if args.symbol is None and not args.all:
        parser.error("Provide a symbol or use --all")

    return args


async def generate_for_symbol(
    symbol: str,
    timeframe: str,
    since: datetime | None,
    window: int,
    stride: int,
    service: MarketEpisodeService,
) -> int:
    """Detect and store episodes for a single symbol. Returns episode count."""
    async with get_session_factory()() as session:
        repo = OHLCVRepository(session)
        # Fetch all available candles (large limit for backfill data)
        records = await repo.fetch(symbol, timeframe, since=since, limit=100_000)

    if not records:
        logger.warning("[generate] no OHLCV data for %s/%s", symbol, timeframe)
        return 0

    timestamps = [r.timestamp.replace(tzinfo=timezone.utc) if r.timestamp.tzinfo is None else r.timestamp for r in records]
    closes = [r.close for r in records]
    volumes = [r.volume for r in records]

    logger.info("[generate] %s: %d candles loaded, detecting episodes (window=%d stride=%d)...",
                symbol, len(records), window, stride)

    episodes = detect_episodes(
        symbol=symbol,
        timeframe=timeframe,
        timestamps=timestamps,
        closes=closes,
        volumes=volumes,
        window=window,
        stride=stride,
    )

    if not episodes:
        logger.info("[generate] %s: no significant episodes detected", symbol)
        return 0

    # Embed and store in batches
    total = 0
    for i in range(0, len(episodes), EMBED_BATCH_SIZE):
        batch = episodes[i:i + EMBED_BATCH_SIZE]
        stored = await service.record_batch(batch)
        total += stored
        logger.info("[generate] %s: batch %d — stored %d episodes", symbol, i // EMBED_BATCH_SIZE + 1, stored)

    return total


async def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    since = None
    if args.days:
        since = datetime.now(tz=timezone.utc) - timedelta(days=args.days)
        since = since.replace(tzinfo=None)  # asyncpg needs naive UTC

    # Resolve symbols
    if args.all:
        settings = get_settings()
        symbols = settings.agent_scheduler_symbols_list
        if not symbols:
            logger.error("[generate] --all specified but TRDEX_AGENT_SCHEDULER_SYMBOLS is empty")
            return
        logger.info("[generate] Processing %d symbols: %s", len(symbols), ", ".join(symbols))
    else:
        symbols = [args.symbol]

    service = MarketEpisodeService()
    await service.setup()

    grand_total = 0
    for symbol in symbols:
        count = await generate_for_symbol(
            symbol=symbol,
            timeframe=args.timeframe,
            since=since,
            window=args.window,
            stride=args.stride,
            service=service,
        )
        grand_total += count

    await service.close()
    logger.info("[generate] Done: %d total episodes across %d symbols", grand_total, len(symbols))


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
