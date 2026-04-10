"""Repository for the runtime_config table."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from trdex.storage.runtime_config_models import RuntimeConfigRecord


def _utcnow_naive() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class RuntimeConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, category: str, key: str) -> str | None:
        result = await self._session.execute(
            select(RuntimeConfigRecord).where(
                RuntimeConfigRecord.category == category,
                RuntimeConfigRecord.key == key,
            )
        )
        row = result.scalar_one_or_none()
        return row.value if row else None

    async def get_category(self, category: str) -> dict[str, str]:
        result = await self._session.execute(
            select(RuntimeConfigRecord).where(
                RuntimeConfigRecord.category == category,
            )
        )
        return {r.key: r.value for r in result.scalars().all()}

    async def get_all(self) -> dict[str, dict[str, str]]:
        result = await self._session.execute(select(RuntimeConfigRecord))
        out: dict[str, dict[str, str]] = {}
        for r in result.scalars().all():
            out.setdefault(r.category, {})[r.key] = r.value
        return out

    async def put(self, category: str, key: str, value: str) -> None:
        result = await self._session.execute(
            select(RuntimeConfigRecord).where(
                RuntimeConfigRecord.category == category,
                RuntimeConfigRecord.key == key,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.value = value
            row.updated_at = _utcnow_naive()
        else:
            self._session.add(RuntimeConfigRecord(
                category=category, key=key, value=value,
            ))
        await self._session.commit()

    async def put_many(self, category: str, pairs: dict[str, str]) -> None:
        for key, value in pairs.items():
            result = await self._session.execute(
                select(RuntimeConfigRecord).where(
                    RuntimeConfigRecord.category == category,
                    RuntimeConfigRecord.key == key,
                )
            )
            row = result.scalar_one_or_none()
            if row:
                row.value = value
                row.updated_at = _utcnow_naive()
            else:
                self._session.add(RuntimeConfigRecord(
                    category=category, key=key, value=value,
                ))
        await self._session.commit()

    async def delete(self, category: str, key: str) -> bool:
        result = await self._session.execute(
            delete(RuntimeConfigRecord).where(
                RuntimeConfigRecord.category == category,
                RuntimeConfigRecord.key == key,
            )
        )
        await self._session.commit()
        return result.rowcount > 0
