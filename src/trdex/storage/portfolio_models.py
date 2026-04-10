"""SQLAlchemy ORM model for positions table (portfolio tracking)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import BigInteger, Float, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from trdex.storage.db import Base


class PositionSide(StrEnum):
    """Side of a position in the DB — always uppercase."""
    BUY = "BUY"
    SELL = "SELL"


def _utcnow_naive() -> datetime:
    """Return current UTC time as naive datetime (asyncpg requirement)."""
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class PositionRecord(Base):
    """An open or closed trading position."""

    __tablename__ = "positions"
    __table_args__ = (
        Index("ix_positions_symbol_status", "symbol", "status"),
        Index("ix_positions_source_status", "source", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(5), nullable=False)          # PositionSide.BUY | .SELL
    entry_price: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    budget: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="manual")
    signal_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    opened_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=_utcnow_naive,
    )
    closed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(28, 8), nullable=True)
    fee_open: Mapped[float] = mapped_column(Float, default=0.0)

    def __repr__(self) -> str:
        return f"<Position {self.symbol} {self.side} {self.status} entry={self.entry_price}>"
