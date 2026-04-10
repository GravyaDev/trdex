"""SQLAlchemy ORM model for runtime configuration."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from trdex.storage.db import Base


def _utcnow_naive() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class RuntimeConfigRecord(Base):
    """Persistent key-value config, categorised."""

    __tablename__ = "runtime_config"

    category: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False,
        default=_utcnow_naive, onupdate=_utcnow_naive,
    )
