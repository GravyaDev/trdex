"""Backfill historical OHLCV data from Binance into TimescaleDB.

Usage:
    python -m trdex.scripts.backfill_ohlcv BTC/USDT --timeframe 1h --days 365
    python -m trdex.scripts.backfill_ohlcv ETH/USDT --timeframe 4h --start 2025-01-01

Paginates through Binance's REST API (1000 candles/request via CCXT
enableRateLimit) and upserts into the existing ohlcv hypertable.
Idempotent: safe to re-run — duplicates are skipped (ON CONFLICT DO NOTHING).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone

from trdex.market.feeds.binance import BinanceFeed
from trdex.storage.db import get_session_factory
from trdex.storage.ohlcv_repo import OHLCVRepository

logger = logging.getLogger(__name__)

# Binance caps at 1000 candles per request
MAX_CANDLES_PER_REQUEST = 1000

# Mapping from timeframe string to timedelta per candle
TIMEFRAME_DELTA: dict[str, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "2h": timedelta(hours=2),
    "4h": timedelta(hours=4),
    "6h": timedelta(hours=6),
    "8h": timedelta(hours=8),
    "12h": timedelta(hours=12),
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill OHLCV candles from Binance into TimescaleDB."
    )
    parser.add_argument("symbol", help="Trading pair, e.g. BTC/USDT")
    parser.add_argument(
        "--timeframe", "-t", default="1h", choices=list(TIMEFRAME_DELTA.keys()),
        help="Candle timeframe (default: 1h)",
    )
    parser.add_argument(
        "--days", "-d", type=int, default=None,
        help="Number of days to backfill from now (mutually exclusive with --start)",
    )
    parser.add_argument(
        "--start", "-s", type=str, default=None,
        help="Start date ISO format YYYY-MM-DD (mutually exclusive with --days)",
    )
    parser.add_argument(
        "--end", "-e", type=str, default=None,
        help="End date ISO format YYYY-MM-DD (default: now)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    # Validate symbol format (e.g. BTC/USDT, ETH/BTC)
    import re
    if not re.match(r"^[A-Z0-9]{2,10}/[A-Z0-9]{2,10}$", args.symbol):
        parser.error(f"Invalid symbol format: {args.symbol!r} — expected e.g. BTC/USDT")

    if args.days is not None and args.days > 3650:
        parser.error(f"--days {args.days} exceeds maximum (3650)")

    if args.days is None and args.start is None:
        args.days = 90  # default: 90 days

    return args


async def backfill(
    symbol: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
) -> int:
    """Paginate through Binance OHLCV and upsert into DB.

    Returns total number of new rows inserted.
    """
    delta = TIMEFRAME_DELTA[timeframe]
    total_inserted = 0
    cursor_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    async with BinanceFeed() as feed:
        async with get_session_factory()() as session:
            repo = OHLCVRepository(session)
            page = 0

            while cursor_ms < end_ms:
                page += 1
                candles = await feed.get_ohlcv(
                    symbol,
                    timeframe=timeframe,
                    limit=MAX_CANDLES_PER_REQUEST,
                    since=cursor_ms,
                )

                if not candles:
                    logger.info("[backfill] no more candles at page %d", page)
                    break

                # Filter out candles beyond end_dt
                candles = [c for c in candles if c.timestamp <= end_dt]

                if candles:
                    inserted = await repo.upsert(symbol, timeframe, candles, source="binance")
                    total_inserted += inserted
                    logger.info(
                        "[backfill] page %d: fetched %d candles, inserted %d new (symbol=%s tf=%s)",
                        page, len(candles), inserted, symbol, timeframe,
                    )

                # Advance cursor past the last candle we received
                last_ts_ms = int(candles[-1].timestamp.timestamp() * 1000) if candles else cursor_ms
                next_cursor = last_ts_ms + int(delta.total_seconds() * 1000)

                if next_cursor <= cursor_ms:
                    # Safety: avoid infinite loop if API returns same data
                    break
                cursor_ms = next_cursor

    return total_inserted


async def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    now = datetime.now(tz=timezone.utc)

    if args.start:
        start_dt = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    else:
        start_dt = now - timedelta(days=args.days)

    if args.end:
        end_dt = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    else:
        end_dt = now

    logger.info(
        "[backfill] Starting: symbol=%s timeframe=%s range=%s → %s",
        args.symbol, args.timeframe,
        start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"),
    )

    total = await backfill(args.symbol, args.timeframe, start_dt, end_dt)
    logger.info("[backfill] Done: %d new candles inserted for %s/%s", total, args.symbol, args.timeframe)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
