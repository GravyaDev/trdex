"""SQLAlchemy ORM models for agent LLM configuration and usage tracking."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import REAL, UUID, Boolean, DateTime, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from trdex.storage.db import Base


def _utcnow_naive() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


class AgentConfigRecord(Base):
    """Per-agent LLM configuration. Dashboard reads/writes, agent nodes read."""

    __tablename__ = "agent_config"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    # Provider
    provider: Mapped[str] = mapped_column(Text, nullable=False, default="anthropic")
    model_id: Mapped[str] = mapped_column(Text, nullable=False, default="claude-haiku-4-5-20251001")

    # Sampling
    temperature: Mapped[float] = mapped_column(REAL, nullable=False, default=0.3)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=1024)
    top_p: Mapped[float] = mapped_column(REAL, nullable=False, default=1.0)

    # Prompt
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Feature flags
    llm_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=_utcnow_naive,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=_utcnow_naive,
    )


class AgentLLMUsageRecord(Base):
    """Logs every LLM call for cost tracking and observability."""

    __tablename__ = "agent_llm_usage"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=_utcnow_naive,
    )
