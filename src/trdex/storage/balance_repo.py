"""BalanceRepository: cash balance ledger — deposits, withdrawals, trade fills."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trdex.storage.balance_models import BalanceRecord


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class BalanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def current_balance(self) -> Decimal:
        """Return the current cash balance (latest balance_after)."""
        result = await self._session.execute(
            select(BalanceRecord.balance_after)
            .order_by(BalanceRecord.recorded_at.desc(), BalanceRecord.id.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return row if row is not None else Decimal("10000")

    async def peak_balance(self) -> Decimal:
        """Return the highest balance_after ever recorded (for drawdown calc)."""
        result = await self._session.execute(
            select(func.max(BalanceRecord.balance_after))
        )
        row = result.scalar_one_or_none()
        return row if row is not None else Decimal("10000")

    async def total_trade_pnl(self) -> Decimal:
        """Cumulative realised P&L from every trade_fill row in the ledger.

        Single source of truth for realised P&L: sums the ``amount`` column
        across all ``event_type='trade_fill'`` rows. Includes fees because
        the PnL written at close is ``gross - fee_open - fee_close``.
        """
        result = await self._session.execute(
            select(func.coalesce(func.sum(BalanceRecord.amount), 0)).where(
                BalanceRecord.event_type == "trade_fill"
            )
        )
        row = result.scalar_one_or_none()
        return Decimal(str(row)) if row is not None else Decimal("0")

    async def record_event(
        self,
        event_type: str,
        amount: Decimal,
        note: str = "",
    ) -> BalanceRecord:
        """Append a balance event. Computes balance_after from current balance."""
        current = await self.current_balance()
        balance_after = current + amount
        record = BalanceRecord(
            event_type=event_type,
            amount=amount,
            balance_after=balance_after,
            note=note,
            recorded_at=_utcnow(),
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def deposit(self, amount: Decimal, note: str = "") -> BalanceRecord:
        return await self.record_event("deposit", amount, note)

    async def withdraw(self, amount: Decimal, note: str = "") -> BalanceRecord:
        return await self.record_event("withdrawal", -amount, note)

    async def record_trade_fill(
        self,
        pnl: Decimal,
        note: str = "",
    ) -> BalanceRecord:
        """Record the P&L impact of a closed trade on the cash balance."""
        return await self.record_event("trade_fill", pnl, note)

    async def history(self, limit: int = 100) -> list[BalanceRecord]:
        result = await self._session.execute(
            select(BalanceRecord)
            .order_by(BalanceRecord.recorded_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
