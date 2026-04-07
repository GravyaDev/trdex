"""SQLAlchemy ORM model for trdex_agent_memory (Tier 2 — operational agent memory).

Stores typed observations and state per agent that need to persist across runs
but do not belong to the static KB (.md), the entity graph (subject-predicate
facts), or trade narratives (Qdrant).

Upsert key: (agent, kind, key).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Float, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trdex.storage.db import Base


def _utcnow_naive() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class AgentMemoryRecord(Base):
    __tablename__ = "trdex_agent_memory"
    __table_args__ = (
        UniqueConstraint("agent", "kind", "key", name="ux_agent_memory_triple"),
        Index("ix_agent_memory_agent_kind", "agent", "kind"),
        Index("ix_agent_memory_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent: Mapped[str] = mapped_column(String(40), nullable=False)
    # analyst | risk | executor | scout | stop_loss_monitor | system
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    # category, e.g. indicator_observation, rejection_stat, slippage_sample
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    # composite id inside the kind, e.g. "BTC/USDT:rsi"
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="agent")
    # agent | system | manual
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, default=_utcnow_naive, onupdate=_utcnow_naive
    )
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)

    def __repr__(self) -> str:
        return f"<AgentMemory {self.agent}/{self.kind}/{self.key}>"
