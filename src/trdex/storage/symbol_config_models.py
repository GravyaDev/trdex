"""SQLAlchemy ORM model for symbol_config table."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from trdex.storage.db import Base


def _utcnow_naive() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class SymbolConfigRecord(Base):
    """Per-symbol risk threshold overrides.

    When a row exists for a symbol, StopLossMonitor uses the values
    here instead of the adaptive CV-based defaults. Any column left
    NULL falls back to the adaptive calculation (max(base, mult×CV)).
    """

    __tablename__ = "symbol_config"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    sl_pct: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    tp_pct: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    trailing_pct: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow_naive, onupdate=_utcnow_naive)
