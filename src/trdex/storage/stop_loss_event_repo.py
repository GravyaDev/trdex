"""Repository for the stop_loss_events table."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trdex.storage.stop_loss_event_models import StopLossEventRecord


def _naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _utcnow_naive() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class StopLossEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(
        self,
        *,
        reason: str,
        symbol: str | None,
        position_id: int | None,
        trigger_price: float | None,
        entry_price: float | None,
        loss_pct: float | None,
        message: str,
        fired_at: datetime | None = None,
    ) -> StopLossEventRecord:
        """Persist a single stop-loss event. Numeric inputs are
        accepted as float for ergonomic call sites in risk/stop_loss.py
        and coerced to Decimal for the Numeric(28,8) columns.
        """
        record = StopLossEventRecord(
            reason=reason,
            symbol=symbol,
            position_id=position_id,
            trigger_price=(
                Decimal(str(trigger_price)) if trigger_price is not None else None
            ),
            entry_price=(
                Decimal(str(entry_price)) if entry_price is not None else None
            ),
            loss_pct=loss_pct,
            message=message,
            fired_at=_naive(fired_at) or _utcnow_naive(),
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def recent(self, limit: int = 50) -> list[StopLossEventRecord]:
        """Return the newest `limit` events, newest first."""
        result = await self._session.execute(
            select(StopLossEventRecord)
            .order_by(StopLossEventRecord.fired_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count(self) -> int:
        """Return the total number of stored events."""
        result = await self._session.execute(
            select(func.count(StopLossEventRecord.id))
        )
        return int(result.scalar_one() or 0)
