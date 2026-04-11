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
        exit_price: Decimal | None = None,
        budget: Decimal = Decimal("0"),
        executed_at: datetime | None = None,
        closed_at: datetime | None = None,
        note: str = "",
    ) -> SignalOutcomeRecord:
        """Persist a signal outcome. In observe-only mode `exit_price`
        is None and `budget` is 0 until a post-hoc evaluation resolves
        the signal via `close_outcome()`.
        """
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

    async def open_outcomes(self, limit: int = 1_000) -> list[SignalOutcomeRecord]:
        """Return outcomes not yet resolved (exit_price IS NULL).

        Used by the post-hoc TP/SL evaluation job to find signals that
        still need to be scored against historical OHLCV data.
        """
        result = await self._session.execute(
            select(SignalOutcomeRecord)
            .where(SignalOutcomeRecord.exit_price.is_(None))
            .order_by(SignalOutcomeRecord.executed_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def close_outcome(
        self,
        outcome_id: int,
        exit_price: Decimal,
        closed_at: datetime,
        note: str | None = None,
    ) -> None:
        """Resolve an open outcome with final exit price + close time."""
        record = await self._session.get(SignalOutcomeRecord, outcome_id)
        if record is None:
            return
        record.exit_price = exit_price
        record.closed_at = closed_at.replace(tzinfo=None) if closed_at.tzinfo else closed_at
        if note is not None:
            record.note = note
        await self._session.commit()
