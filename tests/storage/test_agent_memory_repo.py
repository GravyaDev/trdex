"""Unit tests for AgentMemoryRepository (no live DB)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from trdex.storage.agent_memory_models import AgentMemoryRecord
from trdex.storage.agent_memory_repo import AgentMemoryRepository


def _make_record(
    agent: str = "analyst",
    kind: str = "indicator_observation",
    key: str = "BTC/USDT:rsi",
    value: dict | None = None,
    expires_at: datetime | None = None,
) -> AgentMemoryRecord:
    r = AgentMemoryRecord()
    r.id = 1
    r.agent = agent
    r.kind = kind
    r.key = key
    r.value = value or {"v": 1}
    r.confidence = 1.0
    r.source = "agent"
    r.note = ""
    r.expires_at = expires_at
    return r


async def test_upsert_executes_and_returns_record() -> None:
    session = AsyncMock()
    record = _make_record()
    result_mock = MagicMock()
    result_mock.scalar_one.return_value = record
    session.execute.return_value = result_mock

    repo = AgentMemoryRepository(session)
    out = await repo.upsert(
        "analyst",
        "indicator_observation",
        "BTC/USDT:rsi",
        {"value": 42},
        note="from test",
    )

    session.execute.assert_called_once()
    session.commit.assert_called_once()
    assert out is record


async def test_get_returns_none_when_missing() -> None:
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    session.execute.return_value = result_mock

    repo = AgentMemoryRepository(session)
    out = await repo.get("analyst", "kind", "key")
    assert out is None


async def test_list_by_kind_returns_records() -> None:
    session = AsyncMock()
    rows = [_make_record(key=f"k{i}") for i in range(3)]
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = rows
    session.execute.return_value = result_mock

    repo = AgentMemoryRepository(session)
    out = await repo.list_by_kind("analyst", "indicator_observation")
    assert len(out) == 3
    assert out[0].key == "k0"


async def test_delete_returns_rowcount() -> None:
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.rowcount = 1
    session.execute.return_value = result_mock

    repo = AgentMemoryRepository(session)
    removed = await repo.delete("analyst", "kind", "key")
    assert removed == 1
    session.commit.assert_called_once()


async def test_purge_expired_returns_count() -> None:
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.rowcount = 4
    session.execute.return_value = result_mock

    repo = AgentMemoryRepository(session)
    removed = await repo.purge_expired()
    assert removed == 4


def test_record_repr() -> None:
    r = _make_record()
    assert "analyst" in repr(r)
    assert "indicator_observation" in repr(r)
