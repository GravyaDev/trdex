"""Unit tests for AgentRunner._dispatch_fill (D9, D13, D14)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trdex.agents.intent import Intent
from trdex.agents.runner import AgentRunner
from trdex.agents.state import (
    AgentState,
    AnalysisResult,
    OrderResult,
    PortfolioContext,
    RiskDecision,
)


def _state(intent: Intent, order_status: str = "filled") -> AgentState:
    return AgentState(
        symbol="BTC/USDT",
        run_id="r-disp",
        analysis=AnalysisResult(intent=intent, confidence=0.8),
        risk=RiskDecision(approved=True, position_size=0.02, reason="ok"),
        order=OrderResult(
            order_id="o-1",
            status=order_status,
            filled_price=90_000.0,
            filled_qty=0.001,
            message="sim fill",
        ),
        portfolio=PortfolioContext(equity=10_000.0),
        completed_at=datetime.now(tz=timezone.utc),
    )


def _runner() -> AgentRunner:
    """Build a runner with a stub session and feed manager."""
    return AgentRunner(
        session=MagicMock(),
        feed_manager=MagicMock(),
        session_factory=None,
        gateway=None,
        memory_loader=None,
    )


@pytest.mark.asyncio
async def test_dispatch_open_long_calls_record_open_fill():
    """OPEN_LONG → PortfolioService.record_open_fill is awaited with side=BUY."""
    runner = _runner()
    state = _state(Intent.OPEN_LONG)

    with patch(
        "trdex.portfolio.service.PortfolioService.record_open_fill",
        new=AsyncMock(return_value=None),
    ) as mock_open:
        await runner._dispatch_fill(state)

    mock_open.assert_awaited_once()
    kwargs = mock_open.call_args.kwargs
    assert kwargs["side"] == "BUY"
    assert kwargs["symbol"] == "BTC/USDT"
    assert kwargs["amount"] == Decimal("0.001")
    assert kwargs["entry_price"] == Decimal("90000.0")
    assert kwargs["source"] == "agent"


@pytest.mark.asyncio
async def test_dispatch_close_long_calls_record_close_fill_when_position_exists():
    """CLOSE_LONG with a matching open agent position → record_close_fill awaited."""
    runner = _runner()
    state = _state(Intent.CLOSE_LONG)

    fake_pos = MagicMock()
    fake_pos.id = 42
    fake_pos.symbol = "BTC/USDT"
    fake_pos.source = "agent"

    with patch(
        "trdex.storage.portfolio_repo.PortfolioRepository.get_open_positions",
        new=AsyncMock(return_value=[fake_pos]),
    ), patch(
        "trdex.portfolio.service.PortfolioService.record_close_fill",
        new=AsyncMock(return_value=(MagicMock(), MagicMock())),
    ) as mock_close:
        await runner._dispatch_fill(state)

    mock_close.assert_awaited_once()
    kwargs = mock_close.call_args.kwargs
    assert kwargs["position"] is fake_pos
    assert kwargs["exit_price"] == Decimal("90000.0")
    assert kwargs["closed_by"] == "agent_signal"


@pytest.mark.asyncio
async def test_dispatch_close_long_aborts_when_position_vanished_D13_D14():
    """CLOSE_LONG with no matching open agent position → log warning, do not write.

    Simulates the SL monitor having closed the position between cycle
    start and the runner dispatching the agent's CLOSE_LONG fill.
    """
    runner = _runner()
    state = _state(Intent.CLOSE_LONG)

    with patch(
        "trdex.storage.portfolio_repo.PortfolioRepository.get_open_positions",
        new=AsyncMock(return_value=[]),  # nothing left
    ), patch(
        "trdex.portfolio.service.PortfolioService.record_close_fill",
        new=AsyncMock(),
    ) as mock_close:
        await runner._dispatch_fill(state)

    mock_close.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_close_long_ignores_non_agent_positions_D21():
    """CLOSE_LONG must NOT close a Telegram-opened position.

    The translator already prevents emitting CLOSE_LONG for non-agent
    holdings, but the runner enforces the same rule defensively.
    """
    runner = _runner()
    state = _state(Intent.CLOSE_LONG)

    fake_pos = MagicMock()
    fake_pos.id = 99
    fake_pos.symbol = "BTC/USDT"
    fake_pos.source = "telegram"  # NOT agent

    with patch(
        "trdex.storage.portfolio_repo.PortfolioRepository.get_open_positions",
        new=AsyncMock(return_value=[fake_pos]),
    ), patch(
        "trdex.portfolio.service.PortfolioService.record_close_fill",
        new=AsyncMock(),
    ) as mock_close:
        await runner._dispatch_fill(state)

    mock_close.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", [Intent.OPEN_SHORT, Intent.CLOSE_SHORT, Intent.HOLD])
async def test_dispatch_short_or_hold_intents_are_noops(intent):
    """Short intents are reserved vocabulary; HOLD doesn't fill anyway."""
    runner = _runner()
    state = _state(intent)

    with patch(
        "trdex.portfolio.service.PortfolioService.record_open_fill",
        new=AsyncMock(),
    ) as mock_open, patch(
        "trdex.portfolio.service.PortfolioService.record_close_fill",
        new=AsyncMock(),
    ) as mock_close:
        await runner._dispatch_fill(state)

    mock_open.assert_not_awaited()
    mock_close.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_skipped_order_is_noop():
    """If the executor skipped, no portfolio write happens."""
    runner = _runner()
    state = _state(Intent.OPEN_LONG, order_status="skipped")

    with patch(
        "trdex.portfolio.service.PortfolioService.record_open_fill",
        new=AsyncMock(),
    ) as mock_open:
        await runner._dispatch_fill(state)

    mock_open.assert_not_awaited()
