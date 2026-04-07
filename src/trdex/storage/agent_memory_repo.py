"""AgentMemoryRepository — CRUD + retrieval for trdex_agent_memory (Tier 2)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from trdex.storage.agent_memory_models import AgentMemoryRecord

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class AgentMemoryRepository:
    """Read/write helper around the trdex_agent_memory table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        agent: str,
        kind: str,
        key: str,
        value: dict,
        *,
        confidence: float = 1.0,
        source: str = "agent",
        note: str = "",
        expires_at: datetime | None = None,
    ) -> AgentMemoryRecord:
        """Insert or update a memory row keyed on (agent, kind, key)."""
        now = _utcnow()
        stmt = (
            pg_insert(AgentMemoryRecord)
            .values(
                agent=agent,
                kind=kind,
                key=key,
                value=value,
                confidence=confidence,
                source=source,
                note=note,
                created_at=now,
                updated_at=now,
                expires_at=expires_at,
            )
            .on_conflict_do_update(
                index_elements=["agent", "kind", "key"],
                set_={
                    "value": value,
                    "confidence": confidence,
                    "source": source,
                    "note": note,
                    "updated_at": now,
                    "expires_at": expires_at,
                },
            )
            .returning(AgentMemoryRecord)
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        record = result.scalar_one()
        logger.debug("[agent_memory] upsert %s/%s/%s", agent, kind, key)
        return record

    async def get(self, agent: str, kind: str, key: str) -> AgentMemoryRecord | None:
        """Return a single memory row, ignoring expired entries."""
        now = _utcnow()
        result = await self._session.execute(
            select(AgentMemoryRecord).where(
                AgentMemoryRecord.agent == agent,
                AgentMemoryRecord.kind == kind,
                AgentMemoryRecord.key == key,
                or_(
                    AgentMemoryRecord.expires_at.is_(None),
                    AgentMemoryRecord.expires_at > now,
                ),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_kind(
        self,
        agent: str,
        kind: str,
        *,
        limit: int = 50,
    ) -> list[AgentMemoryRecord]:
        """All non-expired memories for (agent, kind), most recent first."""
        now = _utcnow()
        result = await self._session.execute(
            select(AgentMemoryRecord)
            .where(
                AgentMemoryRecord.agent == agent,
                AgentMemoryRecord.kind == kind,
                or_(
                    AgentMemoryRecord.expires_at.is_(None),
                    AgentMemoryRecord.expires_at > now,
                ),
            )
            .order_by(AgentMemoryRecord.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_for_agent(
        self,
        agent: str,
        *,
        limit: int = 100,
    ) -> list[AgentMemoryRecord]:
        """All non-expired memories belonging to an agent, most recent first."""
        now = _utcnow()
        result = await self._session.execute(
            select(AgentMemoryRecord)
            .where(
                AgentMemoryRecord.agent == agent,
                or_(
                    AgentMemoryRecord.expires_at.is_(None),
                    AgentMemoryRecord.expires_at > now,
                ),
            )
            .order_by(AgentMemoryRecord.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete(self, agent: str, kind: str, key: str) -> int:
        """Delete a single row. Returns number of rows deleted (0 or 1)."""
        result = await self._session.execute(
            delete(AgentMemoryRecord).where(
                AgentMemoryRecord.agent == agent,
                AgentMemoryRecord.kind == kind,
                AgentMemoryRecord.key == key,
            )
        )
        await self._session.commit()
        return result.rowcount or 0

    async def purge_expired(self) -> int:
        """Delete every row whose expires_at is in the past. Returns count removed."""
        now = _utcnow()
        result = await self._session.execute(
            delete(AgentMemoryRecord).where(
                and_(
                    AgentMemoryRecord.expires_at.is_not(None),
                    AgentMemoryRecord.expires_at <= now,
                )
            )
        )
        await self._session.commit()
        removed = result.rowcount or 0
        if removed:
            logger.info("[agent_memory] purged %d expired rows", removed)
        return removed
