"""Unit tests for Risk Gate 4 (D7): OPEN intents block on existing
agent positions, CLOSE intents pass through."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from trdex.agents.intent import Intent
from trdex.agents.risk import risk_node
from trdex.agents.state import (
    AgentState,
    AnalysisResult,
    PortfolioContext,
)


def _state(intent: Intent, agent_positions: list[str]) -> AgentState:
    return AgentState(
        symbol="BTC/USDT",
        run_id="r-gate4",
        analysis=AnalysisResult(intent=intent, confidence=0.8),
        portfolio=PortfolioContext(
            equity=10_000.0,
            open_position_symbols=agent_positions,
            open_position_symbols_by_agent=agent_positions,
        ),
    )


@pytest.mark.asyncio
async def test_gate4_blocks_open_long_with_existing_agent_position():
    """OPEN_LONG on a symbol the agent already holds → BLOCKED (no pyramiding)."""
    state = _state(Intent.OPEN_LONG, ["BTC/USDT"])
    fake_ks = AsyncMock()
    fake_ks.active = False
    with patch("trdex.risk.stop_loss.get_kill_switch", return_value=fake_ks):
        result = await risk_node(state)
    assert result.risk.approved is False
    assert "pyramiding" in result.risk.reason


@pytest.mark.asyncio
async def test_gate4_allows_close_long_with_existing_agent_position_THE_FIX():
    """CLOSE_LONG on a symbol the agent holds → APPROVED.

    This is the core fix. Pre-refactor, the equivalent SELL signal was
    blocked by Gate 4 because all non-HOLD signals were treated as open
    attempts.
    """
    state = _state(Intent.CLOSE_LONG, ["BTC/USDT"])
    fake_ks = AsyncMock()
    fake_ks.active = False
    with patch("trdex.risk.stop_loss.get_kill_switch", return_value=fake_ks):
        result = await risk_node(state)
    assert result.risk.approved is True
    assert "passed" in result.risk.reason.lower()


@pytest.mark.asyncio
async def test_gate4_allows_open_long_when_no_position():
    """OPEN_LONG with empty portfolio → APPROVED."""
    state = _state(Intent.OPEN_LONG, [])
    fake_ks = AsyncMock()
    fake_ks.active = False
    with patch("trdex.risk.stop_loss.get_kill_switch", return_value=fake_ks):
        result = await risk_node(state)
    assert result.risk.approved is True


@pytest.mark.asyncio
async def test_gate1_hold_intent_is_no_op():
    """HOLD → not approved (nothing to trade), but not 'blocked' either."""
    state = _state(Intent.HOLD, [])
    fake_ks = AsyncMock()
    fake_ks.active = False
    with patch("trdex.risk.stop_loss.get_kill_switch", return_value=fake_ks):
        result = await risk_node(state)
    assert result.risk.approved is False
    assert "HOLD" in result.risk.reason
