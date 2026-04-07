"""SQLAlchemy ORM model for signal_outcomes table (Telegram signal P&L tracking)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from trdex.storage.db import Base


def _utcnow_naive() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class SignalOutcomeRecord(Base):
    """One closed Telegram signal with entry/exit P&L."""

    __tablename__ = "signal_outcomes"
    __table_args__ = (
        Index("ix_signal_outcomes_source", "source"),
        Index("ix_signal_outcomes_executed_at", "executed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(5), nullable=False)   # BUY | SELL
    entry_price: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    exit_price: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    budget: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow_naive)
    closed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    def __repr__(self) -> str:
        return f"<SignalOutcome {self.source} {self.symbol} {self.direction}>"
