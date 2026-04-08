"""Tests for executor_node with injected gateway."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trdex.agents.executor import executor_node
from trdex.agents.intent import Intent
from trdex.agents.state import (
    AgentState,
    AnalysisResult,
    MarketSnapshot,
    OrderResult,
    PortfolioContext,
    RiskDecision,
)


def _make_state(
    intent: Intent = Intent.OPEN_LONG,
    approved: bool = True,
    price: float = 90_000.0,
    equity: float = 10_000.0,
    position_size: float = 0.02,
    gateway=None,
    session_factory=None,
) -> AgentState:
    state = AgentState(
        symbol="BTC/USDT",
        run_id="test-run",
        market=MarketSnapshot(
            symbol="BTC/USDT",
            price=price,
            timestamp=datetime.now(tz=timezone.utc),
        ),
        analysis=AnalysisResult(intent=intent, confidence=0.8),
        risk=RiskDecision(
            approved=approved,
            reason="All gates passed." if approved else "Blocked.",
            position_size=position_size,
        ),
        portfolio=PortfolioContext(equity=equity),
        gateway=gateway,
        session_factory=session_factory,
    )
    return state


# ── Skip when not approved ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_executor_skips_when_not_approved():
    state = _make_state(approved=False)
    result = await executor_node(state)
    assert result.order.status == "skipped"
    assert "Blocked" in result.order.message


# ── OPEN_LONG: BUY direction, agent:{run_id} idempotency key ──────────────────

@pytest.mark.asyncio
async def test_executor_open_long_uses_buy_and_run_scoped_key():
    mock_gw = AsyncMock()
    mock_gw.place.return_value = OrderResult(
        order_id="gw-001",
        status="filled",
        filled_price=90_000.0,
        filled_qty=0.00222,
        message="Simulated BUY fill",
    )

    state = _make_state(intent=Intent.OPEN_LONG, gateway=mock_gw)
    result = await executor_node(state)

    mock_gw.place.assert_awaited_once_with(
        symbol="BTC/USDT",
        direction="BUY",
        qty=pytest.approx(10_000.0 * 0.02 / 90_000.0),
        price=90_000.0,
        idempotency_key="agent:test-run",
    )
    assert result.order.status == "filled"
    assert result.order.order_id == "gw-001"


# ── CLOSE_LONG: SELL direction, close:{position_id} idempotency key (D19) ──────

@pytest.mark.asyncio
async def test_executor_close_long_uses_position_id_as_idempotency_key():
    """D19: CLOSE_LONG queries the DB for the open agent position and
    uses ``close:{position.id}`` so concurrent SL/agent closes dedupe."""
    mock_gw = AsyncMock()
    mock_gw.place.return_value = OrderResult(
        order_id="gw-002",
        status="filled",
        filled_price=91_000.0,
        filled_qty=0.00222,
        message="Simulated SELL close fill",
    )

    # Fake live position lookup via a mock session_factory that returns
    # one open agent-owned position with id=42 and amount=0.00222.
    fake_position = MagicMock()
    fake_position.id = 42
    fake_position.symbol = "BTC/USDT"
    fake_position.source = "agent"
    fake_position.amount = 0.00222

    fake_session = AsyncMock()
    fake_session_cm = AsyncMock()
    fake_session_cm.__aenter__.return_value = fake_session
    fake_session_cm.__aexit__.return_value = None
    fake_session_factory = MagicMock(return_value=fake_session_cm)

    with patch(
        "trdex.storage.portfolio_repo.PortfolioRepository.get_open_positions",
        new=AsyncMock(return_value=[fake_position]),
    ):
        state = _make_state(
            intent=Intent.CLOSE_LONG,
            gateway=mock_gw,
            session_factory=fake_session_factory,
        )
        await executor_node(state)

    call_kwargs = mock_gw.place.call_args.kwargs
    assert call_kwargs["direction"] == "SELL"
    assert call_kwargs["idempotency_key"] == "close:42"
    # qty is taken from the live position, NOT from equity × position_size
    assert call_kwargs["qty"] == pytest.approx(0.00222)


@pytest.mark.asyncio
async def test_executor_close_long_skips_when_no_open_position():
    """If the SL closed the position between cycle start and dispatch,
    CLOSE_LONG cannot find it → skip, do not place an order."""
    mock_gw = AsyncMock()

    fake_session = AsyncMock()
    fake_session_cm = AsyncMock()
    fake_session_cm.__aenter__.return_value = fake_session
    fake_session_cm.__aexit__.return_value = None
    fake_session_factory = MagicMock(return_value=fake_session_cm)

    with patch(
        "trdex.storage.portfolio_repo.PortfolioRepository.get_open_positions",
        new=AsyncMock(return_value=[]),  # nothing open
    ):
        state = _make_state(
            intent=Intent.CLOSE_LONG,
            gateway=mock_gw,
            session_factory=fake_session_factory,
        )
        result = await executor_node(state)

    assert result.order.status == "skipped"
    mock_gw.place.assert_not_awaited()


# ── Unsupported intents are no-ops ────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("intent", [Intent.OPEN_SHORT, Intent.CLOSE_SHORT])
async def test_executor_skips_short_intents(intent):
    """SHORT intents are reserved vocabulary and must not reach the gateway."""
    mock_gw = AsyncMock()
    state = _make_state(intent=intent, gateway=mock_gw)
    result = await executor_node(state)
    assert result.order.status == "skipped"
    mock_gw.place.assert_not_awaited()


# ── Falls back to DefaultExecutionGateway when no gateway injected ────────────

@pytest.mark.asyncio
async def test_executor_falls_back_to_default_gateway():
    """Without an injected gateway, executor creates DefaultExecutionGateway.create()."""
    state = _make_state(gateway=None)

    mock_gw = AsyncMock()
    mock_gw.place.return_value = OrderResult(status="filled", message="Fallback sim fill")

    with patch(
        "trdex.execution.default_gateway.DefaultExecutionGateway.create",
        return_value=mock_gw,
    ):
        result = await executor_node(state)

    assert result.order.status == "filled"
    mock_gw.place.assert_awaited_once()


# ── Rejects when price is zero ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_executor_rejects_when_price_zero():
    mock_gw = AsyncMock()
    state = _make_state(price=0.0, gateway=mock_gw)
    result = await executor_node(state)

    assert result.order.status == "rejected"
    assert "price" in result.order.message.lower()
    mock_gw.place.assert_not_awaited()


# ── Position sizing ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_executor_sizing_uses_equity():
    """OPEN_LONG: qty = equity * position_size / price"""
    mock_gw = AsyncMock()
    mock_gw.place.return_value = OrderResult(status="filled", message="ok")

    equity = 50_000.0
    position_size = 0.05
    price = 100_000.0
    expected_qty = equity * position_size / price  # 0.025

    state = _make_state(equity=equity, position_size=position_size, price=price, gateway=mock_gw)
    await executor_node(state)

    call_kwargs = mock_gw.place.call_args.kwargs
    assert call_kwargs["qty"] == pytest.approx(expected_qty)


@pytest.mark.asyncio
async def test_executor_uses_fallback_equity_when_zero():
    """When portfolio.equity == 0, use 10_000 fallback."""
    mock_gw = AsyncMock()
    mock_gw.place.return_value = OrderResult(status="filled", message="ok")

    state = _make_state(equity=0.0, position_size=0.02, price=50_000.0, gateway=mock_gw)
    await executor_node(state)

    call_kwargs = mock_gw.place.call_args.kwargs
    expected_qty = 10_000.0 * 0.02 / 50_000.0
    assert call_kwargs["qty"] == pytest.approx(expected_qty)
