"""Integration tests verifying every agent node attaches a memory snapshot."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from trdex.agents.analyst import analyst_node
from trdex.agents.executor import executor_node
from trdex.agents.risk import risk_node
from trdex.agents.scout import scout_node
from trdex.agents.state import (
    AgentState,
    AnalysisResult,
    MarketSnapshot,
    OrderResult,
    PortfolioContext,
    RiskDecision,
)
from trdex.memory.context import MemoryContext


def _make_loader(per_agent_text: dict[str, str]) -> AsyncMock:
    """Return a mock MemoryContextLoader whose build() yields a non-empty
    context with the given prompt text per agent."""

    loader = AsyncMock()

    async def _build(agent: str, symbol: str, **_kwargs):
        ctx = MemoryContext(agent=agent, symbol=symbol)
        ctx.operational = {"k": [{"key": symbol, "value": {}, "updated_at": None}]}
        text = per_agent_text.get(agent, f"snapshot:{agent}")
        ctx.to_prompt_text = lambda **_k: text  # type: ignore[method-assign]
        return ctx

    loader.build.side_effect = _build
    return loader


def _market() -> MarketSnapshot:
    # Provide enough closes for analyst's RSI/SMA/regime computations.
    closes = [90_000.0 + i * 10 for i in range(30)]
    candles = [
        (datetime(2026, 4, 7, 0, 0), c, c + 10, c - 10, c, 100.0) for c in closes
    ]
    return MarketSnapshot(
        symbol="BTC/USDT",
        price=closes[-1],
        timestamp=datetime.now(tz=timezone.utc),
        candles=candles,
    )


# ---------- scout ---------------------------------------------------------


@pytest.mark.asyncio
async def test_scout_attaches_snapshot_under_scout_key() -> None:
    state = AgentState(symbol="BTC/USDT", run_id="r-1")
    state.memory_loader = _make_loader({"scout": "SCOUT_CTX"})

    # Make ContextIngestionPipeline cheap and successful.
    fake_pipeline = AsyncMock()
    fake_pipeline.query.return_value = []
    with patch(
        "trdex.agents.scout.ContextIngestionPipeline",
        return_value=fake_pipeline,
    ):
        await scout_node(state)

    assert state.memory_snapshots["scout"] == "SCOUT_CTX"


@pytest.mark.asyncio
async def test_scout_survives_loader_failure() -> None:
    state = AgentState(symbol="BTC/USDT", run_id="r-1")
    state.memory_loader = AsyncMock()
    state.memory_loader.build.side_effect = RuntimeError("kb down")

    fake_pipeline = AsyncMock()
    fake_pipeline.query.return_value = []
    with patch(
        "trdex.agents.scout.ContextIngestionPipeline",
        return_value=fake_pipeline,
    ):
        result = await scout_node(state)

    # Scout still completes; sentiment populated; snapshot dict empty.
    assert result.sentiment is not None
    assert state.memory_snapshots == {}


# ---------- analyst -------------------------------------------------------


@pytest.mark.asyncio
async def test_analyst_attaches_snapshot_under_analyst_key() -> None:
    state = AgentState(
        symbol="BTC/USDT",
        run_id="r-1",
        market=_market(),
    )
    state.memory_loader = _make_loader({"analyst": "ANALYST_CTX"})

    await analyst_node(state)

    assert state.memory_snapshots["analyst"] == "ANALYST_CTX"
    # Legacy field is set by the first writer (analyst here).
    assert state.memory_snapshot_text == "ANALYST_CTX"
    # Decision logic still ran.
    assert state.analysis is not None


# ---------- risk ----------------------------------------------------------


@pytest.mark.asyncio
async def test_risk_attaches_snapshot_under_risk_key_without_branching() -> None:
    """Risk gates must remain rule-based: snapshot has no influence."""
    state = AgentState(
        symbol="BTC/USDT",
        run_id="r-1",
        analysis=AnalysisResult(signal="HOLD", confidence=0.8),
        portfolio=PortfolioContext(equity=10_000.0),
    )
    state.memory_loader = _make_loader({"risk": "RISK_CTX"})

    # Make sure kill switch is not active by patching the import target.
    fake_ks = AsyncMock()
    fake_ks.active = False
    with patch("trdex.risk.stop_loss.get_kill_switch", return_value=fake_ks):
        result = await risk_node(state)

    assert state.memory_snapshots["risk"] == "RISK_CTX"
    # HOLD signal must still be rejected by Gate 1 (rule-based, not memory).
    assert result.risk.approved is False
    assert "HOLD" in result.risk.reason


# ---------- executor ------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_attaches_snapshot_under_executor_key() -> None:
    mock_gw = AsyncMock()
    mock_gw.place.return_value = OrderResult(status="filled", message="ok")

    state = AgentState(
        symbol="BTC/USDT",
        run_id="r-1",
        market=_market(),
        analysis=AnalysisResult(signal="BUY", confidence=0.8),
        risk=RiskDecision(approved=True, position_size=0.02, reason="ok"),
        portfolio=PortfolioContext(equity=10_000.0),
        gateway=mock_gw,
    )
    state.memory_loader = _make_loader({"executor": "EXEC_CTX"})

    await executor_node(state)

    assert state.memory_snapshots["executor"] == "EXEC_CTX"
    mock_gw.place.assert_awaited_once()


@pytest.mark.asyncio
async def test_executor_attaches_even_when_skipping() -> None:
    """Snapshot must be attached BEFORE the early-return on risk rejection,
    so we still record the executor's view of memory at that moment."""
    state = AgentState(
        symbol="BTC/USDT",
        run_id="r-1",
        risk=RiskDecision(approved=False, reason="blocked"),
    )
    state.memory_loader = _make_loader({"executor": "EXEC_CTX"})

    result = await executor_node(state)

    assert state.memory_snapshots["executor"] == "EXEC_CTX"
    assert result.order.status == "skipped"
