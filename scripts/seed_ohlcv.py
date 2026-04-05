"""Seed script: fetch historical OHLCV from Binance and persist to TimescaleDB.

Usage:
    uv run python scripts/seed_ohlcv.py

Fetches up to SINCE_DAYS of history for each (symbol, timeframe) combination
and upserts into the ohlcv hypertable. Safe to re-run (ON CONFLICT DO NOTHING).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import ccxt.async_support as ccxt

from trdex.config import get_settings
from trdex.market.models import OHLCV
from trdex.storage.db import get_session_factory
from trdex.storage.ohlcv_repo import OHLCVRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]
TIMEFRAMES = ["1h", "4h", "1d"]
SINCE_DAYS = 365
BATCH_SIZE = 1000  # Binance max per request


def _parse_candles(raw: list) -> list[OHLCV]:
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


async def seed_symbol(
    exchange: ccxt.Exchange,
    repo: OHLCVRepository,
    symbol: str,
    timeframe: str,
) -> int:
    since_dt = datetime.now(tz=timezone.utc) - timedelta(days=SINCE_DAYS)
    since_ms = int(since_dt.timestamp() * 1000)
    total = 0

    while True:
        raw = await exchange.fetch_ohlcv(
            symbol, timeframe=timeframe, since=since_ms, limit=BATCH_SIZE
        )
        if not raw:
            break

        candles = _parse_candles(raw)
        inserted = await repo.upsert(symbol, timeframe, candles)
        total += inserted
        logger.info("  %s %s  +%d rows (total %d)", symbol, timeframe, inserted, total)

        last_ts_ms = raw[-1][0]
        if len(raw) < BATCH_SIZE or last_ts_ms >= int(datetime.now(tz=timezone.utc).timestamp() * 1000):
            break

        since_ms = last_ts_ms + 1
        await asyncio.sleep(0.3)  # stay well under Binance rate limit

    return total


async def main() -> None:
    settings = get_settings()
    exchange = ccxt.binance(
        {
            "apiKey": settings.binance_api_key or None,
            "secret": settings.binance_api_secret or None,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
    )

    session_factory = get_session_factory()

    try:
        async with session_factory() as session:
            repo = OHLCVRepository(session)
            await repo.ensure_hypertable()

            grand_total = 0
            for symbol in SYMBOLS:
                for timeframe in TIMEFRAMES:
                    logger.info("Seeding %s %s ...", symbol, timeframe)
                    n = await seed_symbol(exchange, repo, symbol, timeframe)
                    grand_total += n

        logger.info("Done. Total rows inserted: %d", grand_total)
    finally:
        await exchange.close()


if __name__ == "__main__":
    asyncio.run(main())
