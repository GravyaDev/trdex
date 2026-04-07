"""Unit tests for the attach_memory_snapshot helper."""

from __future__ import annotations

from unittest.mock import AsyncMock

from trdex.agents.memory_helpers import attach_memory_snapshot
from trdex.agents.state import AgentState
from trdex.memory.context import MemoryContext


def _state() -> AgentState:
    return AgentState(symbol="BTC/USDT", run_id="r-1")


def _ctx(*, empty: bool = False, text: str = "snapshot text") -> MemoryContext:
    ctx = MemoryContext(agent="analyst", symbol="BTC/USDT")
    if not empty:
        # Use operational dict to make is_empty() return False without
        # depending on the KBLoader fixture.
        ctx.operational = {"k": [{"key": "BTC/USDT", "value": {}, "updated_at": None}]}
    # Override to_prompt_text so we don't depend on its formatting.
    ctx.to_prompt_text = lambda **_kwargs: text  # type: ignore[method-assign]
    return ctx


async def test_returns_empty_when_no_loader() -> None:
    state = _state()
    out = await attach_memory_snapshot(state, "analyst")
    assert out == ""
    assert state.memory_snapshots == {}
    assert state.memory_snapshot_text == ""


async def test_attaches_snapshot_to_state() -> None:
    state = _state()
    state.memory_loader = AsyncMock()
    state.memory_loader.build.return_value = _ctx(text="ANALYST CONTEXT")

    out = await attach_memory_snapshot(state, "analyst")

    assert out == "ANALYST CONTEXT"
    assert state.memory_snapshots["analyst"] == "ANALYST CONTEXT"
    # Backward-compatible field set on first attach.
    assert state.memory_snapshot_text == "ANALYST CONTEXT"


async def test_legacy_field_not_overwritten_by_second_attach() -> None:
    state = _state()
    state.memory_loader = AsyncMock()
    state.memory_loader.build.side_effect = [
        _ctx(text="ANALYST"),
        _ctx(text="RISK"),
    ]

    await attach_memory_snapshot(state, "analyst")
    await attach_memory_snapshot(state, "risk")

    assert state.memory_snapshots == {"analyst": "ANALYST", "risk": "RISK"}
    # Legacy field stays at the *first* writer (analyst).
    assert state.memory_snapshot_text == "ANALYST"


async def test_skips_when_context_is_empty() -> None:
    state = _state()
    state.memory_loader = AsyncMock()
    state.memory_loader.build.return_value = _ctx(empty=True)

    out = await attach_memory_snapshot(state, "scout")

    assert out == ""
    assert "scout" not in state.memory_snapshots
    assert state.memory_snapshot_text == ""


async def test_swallows_loader_exception() -> None:
    state = _state()
    state.memory_loader = AsyncMock()
    state.memory_loader.build.side_effect = RuntimeError("boom")

    out = await attach_memory_snapshot(state, "analyst")

    assert out == ""
    assert state.memory_snapshots == {}
    assert state.memory_snapshot_text == ""


async def test_forwards_similarity_query() -> None:
    state = _state()
    state.memory_loader = AsyncMock()
    state.memory_loader.build.return_value = _ctx()

    await attach_memory_snapshot(state, "analyst", similarity_query="BTC oversold")

    state.memory_loader.build.assert_awaited_once()
    kwargs = state.memory_loader.build.call_args.kwargs
    assert kwargs["similarity_query"] == "BTC oversold"
