"""SQLAlchemy ORM model for stop_loss_events table.

Persistent log of every StopLossEvent fired by the risk monitor.
Replaces the prior in-memory list that was lost on every restart,
so incident reviews and audit trails survive container cycles.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, Double, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from trdex.storage.db import Base


def _utcnow_naive() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class StopLossEventRecord(Base):
    """One stop-loss trigger event — persisted for post-mortem."""

    __tablename__ = "stop_loss_events"
    __table_args__ = (
        Index("ix_stop_loss_events_fired_at", "fired_at"),
        Index("ix_stop_loss_events_reason", "reason"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True,
    )
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    symbol: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
    )  # NULL = portfolio-level event
    position_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True,
    )
    trigger_price: Mapped[Decimal | None] = mapped_column(
        Numeric(28, 8), nullable=True,
    )
    entry_price: Mapped[Decimal | None] = mapped_column(
        Numeric(28, 8), nullable=True,
    )
    loss_pct: Mapped[float | None] = mapped_column(
        Double, nullable=True,
    )
    message: Mapped[str] = mapped_column(
        Text, nullable=False, default="",
    )
    fired_at: Mapped[datetime] = mapped_column(
        nullable=False, default=_utcnow_naive,
    )

    def __repr__(self) -> str:
        return f"<StopLossEvent {self.reason} {self.symbol or 'portfolio'}>"
