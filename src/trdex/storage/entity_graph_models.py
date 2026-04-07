"""SQLAlchemy ORM model for trdex_entity_graph table.

Stores structured facts as subject-predicate-object triples with temporal
auditability. A NULL valid_until means the fact is currently active.

Example facts:
    subject_type=symbol,  subject_id=BTC/USDT, predicate=volatility_regime,  object_value={"value": "high"}
    subject_type=channel, subject_id=@chan,     predicate=win_rate,           object_value={"value": 0.62}
    subject_type=symbol,  subject_id=BTC/USDT, predicate=correlates_with,    object_id=ETH/USDT
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Float, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trdex.storage.db import Base


def _utcnow_naive() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class EntityGraphRecord(Base):
    __tablename__ = "trdex_entity_graph"
    __table_args__ = (
        Index("ix_entity_graph_subject", "subject_type", "subject_id"),
        Index("ix_entity_graph_predicate", "predicate"),
        Index("ix_entity_graph_active", "subject_id", "valid_until"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # symbol | channel | strategy | portfolio
    subject_id: Mapped[str] = mapped_column(String(100), nullable=False)
    predicate: Mapped[str] = mapped_column(String(60), nullable=False)
    # e.g. volatility_regime | win_rate | correlates_with | last_signal | drawdown_pct
    object_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # structured value, e.g. {"value": 0.62} or {"value": "high"}
    object_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # if fact is a relation to another entity (e.g. correlates_with ETH/USDT)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # 1.0 = explicit/observed, <1.0 = inferred
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="agent")
    # agent | system | manual
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    valid_from: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow_naive)
    valid_until: Mapped[datetime | None] = mapped_column(nullable=True)
    # NULL = currently active; set to invalidate

    def __repr__(self) -> str:
        return f"<Entity {self.subject_type}:{self.subject_id} {self.predicate}>"
