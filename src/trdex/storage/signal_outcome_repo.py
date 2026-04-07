"""SignalOutcomeRepository: persistence for Telegram signal P&L outcomes."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trdex.storage.signal_outcome_models import SignalOutcomeRecord


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class SignalOutcomeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(
        self,
        source: str,
        symbol: str,
        direction: str,
        entry_price: Decimal,
        exit_price: Decimal,
        budget: Decimal,
        executed_at: datetime | None = None,
        closed_at: datetime | None = None,
        note: str = "",
    ) -> SignalOutcomeRecord:
        def _naive(dt: datetime | None) -> datetime | None:
            if dt is None:
                return None
            return dt.replace(tzinfo=None) if dt.tzinfo else dt

        record = SignalOutcomeRecord(
            source=source,
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            budget=budget,
            executed_at=_naive(executed_at) or _utcnow(),
            closed_at=_naive(closed_at),
            note=note,
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def all(self, limit: int = 10_000) -> list[SignalOutcomeRecord]:
        result = await self._session.execute(
            select(SignalOutcomeRecord)
            .order_by(SignalOutcomeRecord.executed_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def by_source(self, source: str) -> list[SignalOutcomeRecord]:
        result = await self._session.execute(
            select(SignalOutcomeRecord)
            .where(SignalOutcomeRecord.source == source)
            .order_by(SignalOutcomeRecord.executed_at.asc())
        )
        return list(result.scalars().all())
