"""SQLAlchemy ORM model for agent run history."""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone

from sqlalchemy import UUID, Boolean, DateTime, Index, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trdex.storage.db import Base


def _utcnow_naive() -> datetime:
    """Return current UTC time as naive datetime (asyncpg requirement)."""
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class AgentRunRecord(Base):
    """Persists one full agent cycle (Scout→Analyst→Risk→Executor)."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_symbol", "symbol"),
        Index("ix_agent_runs_ran_at", "ran_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, unique=True,
                                        default=lambda: str(_uuid.uuid4()))
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False,
        default=_utcnow_naive,
    )

    # Analyst
    signal: Mapped[str] = mapped_column(Text, nullable=False, default="HOLD")
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")
    indicators: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Risk
    risk_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    risk_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    position_size: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    stop_loss_pct: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    take_profit_pct: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, default=0)

    # Order
    order_status: Mapped[str] = mapped_column(Text, nullable=False, default="skipped")  # filled | rejected | skipped | pending
    filled_price: Mapped[float | None] = mapped_column(Numeric(28, 8), nullable=True)
    filled_qty: Mapped[float | None] = mapped_column(Numeric(28, 8), nullable=True)
    order_message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
