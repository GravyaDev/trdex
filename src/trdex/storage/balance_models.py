"""SQLAlchemy ORM model for account_balance table."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from trdex.storage.db import Base


def _utcnow_naive() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class BalanceRecord(Base):
    """One entry in the account balance ledger.

    Every event that changes the cash balance (deposit, withdrawal, trade fill)
    creates a row. Current balance = latest row's `balance_after`.
    Peak equity is the maximum `balance_after` ever recorded.
    """

    __tablename__ = "account_balance"
    __table_args__ = (
        Index("ix_account_balance_recorded_at", "recorded_at"),
        Index("ix_account_balance_event_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # deposit | withdrawal | trade_fill | fee | manual_adjustment
    amount: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    # positive = credit, negative = debit
    balance_after: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recorded_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow_naive)

    def __repr__(self) -> str:
        return f"<Balance {self.event_type} {self.amount:+} → {self.balance_after}>"
