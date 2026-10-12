"""PortfolioRepository: persistence for open/closed positions."""

from __future__ import annotations

from datetime import datetime, timezone


def _utcnow() -> datetime:
    """Return current UTC time as naive datetime (required by asyncpg + TIMESTAMPTZ)."""
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from trdex.storage.portfolio_models import PositionRecord


class PortfolioRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: Decimal,
        amount: Decimal,
        budget: Decimal,
        source: str = "manual",
        signal_id: str | None = None,
    ) -> PositionRecord:
        record = PositionRecord(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            amount=amount,
            budget=budget,
            source=source,
            signal_id=signal_id,
            status="open",
            opened_at=_utcnow(),
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def close_position(
        self,
        position_id: int,
        exit_price: Decimal,
        closed_at: datetime | None = None,
    ) -> PositionRecord | None:
        result = await self._session.execute(
            select(PositionRecord).where(PositionRecord.id == position_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        record.exit_price = exit_price
        _ca = closed_at.replace(tzinfo=None) if closed_at and closed_at.tzinfo else closed_at
        record.closed_at = _ca or _utcnow()
        record.status = "closed"
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def get_open_positions(self) -> list[PositionRecord]:
        result = await self._session.execute(
            select(PositionRecord).where(PositionRecord.status == "open")
        )
        return list(result.scalars().all())

    async def get_open_by_symbol_side(
        self,
        symbol: str,
        side: str,
    ) -> PositionRecord | None:
        """Return the single open position matching (symbol, side), or None.

        Used by the Telegram signal dedup gate to enforce
        "max 1 open position per (symbol, direction)" cheaply
        (indexed lookup rather than Python-side filter).
        """
        stmt = (
            select(PositionRecord)
            .where(PositionRecord.symbol == symbol)
            .where(PositionRecord.side == side)
            .where(PositionRecord.status == "open")
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_closed_positions(
        self,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[PositionRecord]:
        q = select(PositionRecord).where(PositionRecord.status == "closed")
        if since:
            q = q.where(PositionRecord.closed_at >= since)
        q = q.order_by(PositionRecord.closed_at.desc()).limit(limit)
        result = await self._session.execute(q)
        return list(result.scalars().all())

    async def pnl_by_source(self) -> list[dict]:
        """Realized P&L grouped by source for closed positions."""
        rows = await self._session.execute(
            text("""
                SELECT
                    source,
                    COUNT(*)                                         AS trade_count,
                    SUM(CASE WHEN exit_price > entry_price AND side = 'BUY'
                              OR exit_price < entry_price AND side = 'SELL'
                         THEN 1 ELSE 0 END)                         AS win_count,
                    SUM(
                        CASE side
                            WHEN 'BUY'  THEN (exit_price - entry_price) * amount
                            WHEN 'SELL' THEN (entry_price - exit_price) * amount
                        END
                    )                                                AS realized_pnl
                FROM positions
                WHERE status = 'closed'
                  AND exit_price IS NOT NULL
                GROUP BY source
                ORDER BY realized_pnl DESC
            """)
        )
        return [
            {
                "source": r.source,
                "trade_count": int(r.trade_count),
                "win_count": int(r.win_count),
                "realized_pnl": float(r.realized_pnl or 0),
            }
            for r in rows
        ]

    async def pnl_history(self, days: int = 30) -> list[dict]:
        """Cumulative realized P&L over time (for charting).

        Bug 9 (2026-04-08): the previous implementation interpolated
        ``:days`` inside a SQL string literal — ``INTERVAL ':days days'``
        — so the bind placeholder was never parsed. SQLAlchemy saw a
        zero-parameter query while the execute() call passed 1 bind,
        which crashed asyncpg with "the server expects 0 arguments for
        this query, 1 was passed". Fixed by using ``make_interval()``
        which takes the bound integer directly as a named-arg function.
        """
        rows = await self._session.execute(
            text("""
                SELECT
                    closed_at,
                    CASE side
                        WHEN 'BUY'  THEN (exit_price - entry_price) * amount
                        WHEN 'SELL' THEN (entry_price - exit_price) * amount
                    END AS pnl
                FROM positions
                WHERE status = 'closed'
                  AND exit_price IS NOT NULL
                  AND closed_at >= NOW() - make_interval(days => :days)
                ORDER BY closed_at ASC
            """),
            {"days": days},
        )
        cumulative = 0.0
        history = []
        for r in rows:
            cumulative += float(r.pnl or 0)
            history.append({"timestamp": r.closed_at.isoformat(), "cumulative_pnl": cumulative})
        return history
