"""OHLCV repository: upsert and query candles from TimescaleDB."""

from __future__ import annotations

from datetime import datetime

import polars as pl
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from trdex.market.models import OHLCV
from trdex.storage.models import OHLCVRecord


class OHLCVRepository:
    """Persist and retrieve OHLCV candles via SQLAlchemy async.

    Usage:
        repo = OHLCVRepository(session)
        await repo.upsert("BTC/USDT", "1h", candles, source="binance")
        df = await repo.fetch_polars("BTC/USDT", "1h", limit=200)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        symbol: str,
        timeframe: str,
        candles: list[OHLCV],
        source: str = "binance",
    ) -> int:
        """Insert candles, skipping duplicates (ON CONFLICT DO NOTHING).

        Returns the number of rows inserted.
        """
        if not candles:
            return 0

        rows = [
            {
                "symbol": symbol,
                "timeframe": timeframe,
                # asyncpg + TIMESTAMPTZ requires naive UTC datetimes
                "timestamp": c.timestamp.replace(tzinfo=None) if c.timestamp.tzinfo else c.timestamp,
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": float(c.volume),
                "source": source,
            }
            for c in candles
        ]

        stmt = (
            insert(OHLCVRecord)
            .values(rows)
            .on_conflict_do_nothing(
                constraint="uq_ohlcv_symbol_tf_ts"
            )
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount or 0

    async def fetch(
        self,
        symbol: str,
        timeframe: str,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[OHLCVRecord]:
        """Fetch candles ordered by timestamp ascending."""
        stmt = (
            select(OHLCVRecord)
            .where(OHLCVRecord.symbol == symbol)
            .where(OHLCVRecord.timeframe == timeframe)
            .order_by(OHLCVRecord.timestamp.asc())
            .limit(limit)
        )
        if since:
            stmt = stmt.where(OHLCVRecord.timestamp >= since)

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def time_range(
        self, symbol: str, timeframe: str
    ) -> tuple[datetime | None, datetime | None]:
        """(first, last) stored candle timestamp, (None, None) if none."""
        stmt = select(func.min(OHLCVRecord.timestamp), func.max(OHLCVRecord.timestamp)).where(
            OHLCVRecord.symbol == symbol, OHLCVRecord.timeframe == timeframe
        )
        row = (await self._session.execute(stmt)).one()
        return row[0], row[1]

    async def fetch_polars(
        self,
        symbol: str,
        timeframe: str,
        since: datetime | None = None,
        limit: int = 500,
    ) -> pl.DataFrame:
        """Fetch candles as a polars DataFrame ready for the backtest engine."""
        records = await self.fetch(symbol, timeframe, since=since, limit=limit)
        if not records:
            return pl.DataFrame(
                schema={
                    "timestamp": pl.Datetime,
                    "open": pl.Float64,
                    "high": pl.Float64,
                    "low": pl.Float64,
                    "close": pl.Float64,
                    "volume": pl.Float64,
                }
            )
        return pl.DataFrame(
            {
                "timestamp": [r.timestamp for r in records],
                "open": [r.open for r in records],
                "high": [r.high for r in records],
                "low": [r.low for r in records],
                "close": [r.close for r in records],
                "volume": [r.volume for r in records],
            }
        )

    async def ensure_hypertable(self) -> None:
        """Convert the ohlcv table to a TimescaleDB hypertable (idempotent).

        Must be called once after table creation.
        """
        await self._session.execute(
            text(
                "SELECT create_hypertable('ohlcv', 'timestamp', "
                "if_not_exists => TRUE, migrate_data => TRUE);"
            )
        )
        await self._session.commit()
