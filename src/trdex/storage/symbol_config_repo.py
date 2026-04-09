"""Repository for per-symbol risk threshold overrides."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trdex.storage.symbol_config_models import SymbolConfigRecord


class SymbolConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, symbol: str) -> SymbolConfigRecord | None:
        result = await self._session.execute(
            select(SymbolConfigRecord).where(SymbolConfigRecord.symbol == symbol)
        )
        return result.scalar_one_or_none()

    async def get_all(self) -> list[SymbolConfigRecord]:
        result = await self._session.execute(
            select(SymbolConfigRecord).order_by(SymbolConfigRecord.symbol)
        )
        return list(result.scalars().all())

    async def get_map(self) -> dict[str, SymbolConfigRecord]:
        """Return all overrides as {symbol: record} for efficient lookup."""
        records = await self.get_all()
        return {r.symbol: r for r in records}

    async def upsert(
        self,
        symbol: str,
        *,
        sl_pct: float | None = None,
        tp_pct: float | None = None,
        trailing_pct: float | None = None,
        notes: str = "",
    ) -> SymbolConfigRecord:
        """Create or update per-symbol config. NULL values mean 'use adaptive default'."""
        existing = await self.get(symbol)
        if existing:
            existing.sl_pct = sl_pct
            existing.tp_pct = tp_pct
            existing.trailing_pct = trailing_pct
            existing.notes = notes
        else:
            existing = SymbolConfigRecord(
                symbol=symbol,
                sl_pct=sl_pct,
                tp_pct=tp_pct,
                trailing_pct=trailing_pct,
                notes=notes,
            )
            self._session.add(existing)
        await self._session.commit()
        await self._session.refresh(existing)
        return existing

    async def delete(self, symbol: str) -> bool:
        """Remove per-symbol override, reverting to adaptive defaults."""
        existing = await self.get(symbol)
        if existing:
            await self._session.delete(existing)
            await self._session.commit()
            return True
        return False
