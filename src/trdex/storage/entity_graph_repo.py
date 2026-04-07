"""EntityGraphRepository: upsert and query structured facts about symbols, channels, strategies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from trdex.storage.entity_graph_models import EntityGraphRecord

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class EntityGraphRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        subject_type: str,
        subject_id: str,
        predicate: str,
        object_value: dict | None = None,
        object_id: str | None = None,
        confidence: float = 1.0,
        source: str = "agent",
        note: str = "",
    ) -> EntityGraphRecord:
        """Invalidate the current active fact for (subject_type, subject_id, predicate)
        and insert the new one. Preserves full temporal history.
        """
        now = _utcnow()

        # Invalidate any currently active fact for this triple
        await self._session.execute(
            update(EntityGraphRecord)
            .where(
                EntityGraphRecord.subject_type == subject_type,
                EntityGraphRecord.subject_id == subject_id,
                EntityGraphRecord.predicate == predicate,
                EntityGraphRecord.valid_until.is_(None),
            )
            .values(valid_until=now)
        )

        record = EntityGraphRecord(
            subject_type=subject_type,
            subject_id=subject_id,
            predicate=predicate,
            object_value=object_value,
            object_id=object_id,
            confidence=confidence,
            source=source,
            note=note,
            valid_from=now,
            valid_until=None,
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        logger.debug("[entity_graph] upsert %s:%s %s", subject_type, subject_id, predicate)
        return record

    async def get_active(
        self,
        subject_type: str | None = None,
        subject_id: str | None = None,
        predicate: str | None = None,
    ) -> list[EntityGraphRecord]:
        """Return currently active facts (valid_until IS NULL), with optional filters."""
        q = select(EntityGraphRecord).where(EntityGraphRecord.valid_until.is_(None))
        if subject_type:
            q = q.where(EntityGraphRecord.subject_type == subject_type)
        if subject_id:
            q = q.where(EntityGraphRecord.subject_id == subject_id)
        if predicate:
            q = q.where(EntityGraphRecord.predicate == predicate)
        q = q.order_by(EntityGraphRecord.valid_from.desc())
        result = await self._session.execute(q)
        return list(result.scalars().all())

    async def get_value(
        self,
        subject_type: str,
        subject_id: str,
        predicate: str,
    ) -> Any | None:
        """Return the current object_value dict for a specific fact, or None if not found."""
        facts = await self.get_active(subject_type=subject_type, subject_id=subject_id, predicate=predicate)
        if not facts:
            return None
        return facts[0].object_value

    async def history(
        self,
        subject_type: str,
        subject_id: str,
        predicate: str,
        limit: int = 20,
    ) -> list[EntityGraphRecord]:
        """Return full history (active + superseded) for a specific triple."""
        result = await self._session.execute(
            select(EntityGraphRecord)
            .where(
                EntityGraphRecord.subject_type == subject_type,
                EntityGraphRecord.subject_id == subject_id,
                EntityGraphRecord.predicate == predicate,
            )
            .order_by(EntityGraphRecord.valid_from.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
