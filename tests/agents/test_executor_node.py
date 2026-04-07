"""Tests for executor_node with injected gateway."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from trdex.agents.executor import executor_node
from trdex.agents.state import (
    AgentState,
    AnalysisResult,
    MarketSnapshot,
    OrderResult,
    PortfolioContext,
    RiskDecision,
)
from datetime import datetime, timezone


def _make_state(
    signal: str = "BUY",
    approved: bool = True,
    price: float = 90_000.0,
    equity: float = 10_000.0,
    position_size: float = 0.02,
    gateway=None,
) -> AgentState:
    state = AgentState(
        symbol="BTC/USDT",
        run_id="test-run",
        market=MarketSnapshot(
            symbol="BTC/USDT",
            price=price,
            timestamp=datetime.now(tz=timezone.utc),
        ),
        analysis=AnalysisResult(signal=signal, confidence=0.8),
        risk=RiskDecision(
            approved=approved,
            reason="All gates passed." if approved else "Blocked.",
            position_size=position_size,
        ),
        portfolio=PortfolioContext(equity=equity),
        gateway=gateway,
    )
    return state


# ── Skip when not approved ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_executor_skips_when_not_approved():
    state = _make_state(approved=False)
    result = await executor_node(state)
    assert result.order.status == "skipped"
    assert "Blocked" in result.order.message


# ── Uses injected gateway ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_executor_uses_injected_gateway():
    mock_gw = AsyncMock()
    mock_gw.place.return_value = OrderResult(
        order_id="gw-001",
        status="filled",
        filled_price=90_000.0,
        filled_qty=0.00222,
        message="Simulated BUY fill",
    )

    state = _make_state(gateway=mock_gw)
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


@pytest.mark.asyncio
async def test_executor_sell_direction():
    mock_gw = AsyncMock()
    mock_gw.place.return_value = OrderResult(status="filled", message="SELL fill")

    state = _make_state(signal="SELL", gateway=mock_gw)
    await executor_node(state)

    call_kwargs = mock_gw.place.call_args.kwargs
    assert call_kwargs["direction"] == "SELL"


# ── Falls back to DefaultExecutionGateway when no gateway injected ────────────

@pytest.mark.asyncio
async def test_executor_falls_back_to_default_gateway():
    """Without an injected gateway, executor creates DefaultExecutionGateway.create()."""
    state = _make_state(gateway=None)

    # Patch DefaultExecutionGateway.create() so we don't need real settings/DB
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
    """qty = equity * position_size / price"""
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
