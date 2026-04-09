"""AgentConfigRepository — CRUD for agent_config table."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from trdex.storage.agent_config_models import AgentConfigRecord

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class AgentConfigRepository:
    """Read/write helper around the agent_config table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, agent_name: str) -> AgentConfigRecord | None:
        """Fetch config for a single agent. Returns ``None`` if not found."""
        stmt = select(AgentConfigRecord).where(AgentConfigRecord.agent_name == agent_name)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(self) -> list[AgentConfigRecord]:
        """Fetch config for all agents."""
        stmt = select(AgentConfigRecord).order_by(AgentConfigRecord.agent_name)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_as_dict(self) -> dict[str, AgentConfigRecord]:
        """Fetch all configs keyed by agent_name. Used by LLMCaller init."""
        rows = await self.get_all()
        return {r.agent_name: r for r in rows}

    async def update_config(
        self,
        agent_name: str,
        *,
        provider: str | None = None,
        model_id: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        system_prompt: str | None = None,
        llm_enabled: bool | None = None,
    ) -> AgentConfigRecord | None:
        """Update specific fields for an agent's config. Returns updated record."""
        values: dict = {"updated_at": _utcnow()}
        if provider is not None:
            values["provider"] = provider
        if model_id is not None:
            values["model_id"] = model_id
        if temperature is not None:
            values["temperature"] = temperature
        if max_tokens is not None:
            values["max_tokens"] = max_tokens
        if top_p is not None:
            values["top_p"] = top_p
        if system_prompt is not None:
            values["system_prompt"] = system_prompt
        if llm_enabled is not None:
            values["llm_enabled"] = llm_enabled

        stmt = (
            update(AgentConfigRecord)
            .where(AgentConfigRecord.agent_name == agent_name)
            .values(**values)
        )
        await self._session.execute(stmt)
        await self._session.commit()
        return await self.get(agent_name)
