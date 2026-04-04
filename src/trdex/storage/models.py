"""SQLAlchemy ORM models for TimescaleDB storage."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Float, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from trdex.storage.db import Base


class OHLCVRecord(Base):
    """OHLCV candle stored in TimescaleDB hypertable.

    The 'timestamp' column is the hypertable time dimension.
    Unique constraint on (symbol, timeframe, timestamp) prevents duplicates on upsert.
    """

    __tablename__ = "ohlcv"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_ohlcv_symbol_tf_ts"),
        Index("ix_ohlcv_symbol_tf_ts", "symbol", "timeframe", "timestamp"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)  # e.g. "1h"
    timestamp: Mapped[datetime] = mapped_column(nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="binance")

    def __repr__(self) -> str:
        return f"<OHLCV {self.symbol} {self.timeframe} {self.timestamp} close={self.close}>"
