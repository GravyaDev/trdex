"""Tests for DefaultExecutionGateway routing and kill-switch logic."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trdex.agents.state import OrderResult
from trdex.config import TrdexMode
from trdex.execution.default_gateway import DefaultExecutionGateway, _to_order_result
from trdex.execution.models import ExecutionResult, Order, OrderType, Side
from trdex.execution.simulator import Simulator
from trdex.risk.stop_loss import KillSwitch


def _make_execution_result(simulated: bool = True) -> ExecutionResult:
    from datetime import datetime, timezone
    return ExecutionResult(
        order_id="abc123",
        symbol="BTC/USDT",
        side=Side.BUY,
        filled_amount=Decimal("0.01"),
        filled_price=Decimal("90000"),
        fee=Decimal("0.9"),
        timestamp=datetime.now(tz=timezone.utc),
        simulated=simulated,
    )


def _make_gateway(
    mode: TrdexMode = TrdexMode.SIMULATION,
    live_executor=None,
    kill_switch_active: bool = False,
) -> DefaultExecutionGateway:
    ks = MagicMock(spec=KillSwitch)
    ks.active = kill_switch_active
    ks.status = {"reason": "manual override"}
    return DefaultExecutionGateway(
        mode=mode,
        simulator=Simulator(),
        live_executor=live_executor,
        kill_switch=ks,
    )


# ── place() routing ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_place_routes_to_simulator_in_sim_mode():
    gw = _make_gateway(mode=TrdexMode.SIMULATION)
    result = await gw.place("BTC/USDT", "BUY", qty=0.01, price=90_000.0)
    assert result.status == "filled"
    assert result.filled_price == pytest.approx(90_000.0)
    assert result.filled_qty == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_place_routes_to_live_executor_in_live_mode():
    mock_live = AsyncMock()
    mock_live.execute.return_value = _make_execution_result(simulated=False)

    gw = _make_gateway(mode=TrdexMode.LIVE, live_executor=mock_live)
    result = await gw.place("BTC/USDT", "BUY", qty=0.01, price=90_000.0)

    mock_live.execute.assert_awaited_once()
    assert result.status == "filled"


@pytest.mark.asyncio
async def test_place_blocks_when_kill_switch_active():
    gw = _make_gateway(kill_switch_active=True)
    # Patch simulator so we can assert it's never called
    gw._simulator.execute = AsyncMock()

    result = await gw.place("BTC/USDT", "BUY", qty=0.01, price=90_000.0)

    assert result.status == "rejected"
    assert "Kill switch" in result.message
    gw._simulator.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_place_rejects_when_live_executor_not_configured():
    gw = _make_gateway(mode=TrdexMode.LIVE, live_executor=None)
    result = await gw.place("BTC/USDT", "BUY", qty=0.01, price=90_000.0)
    assert result.status == "rejected"
    assert "not configured" in result.message.lower() or "Execution error" in result.message


@pytest.mark.asyncio
async def test_place_sell_direction():
    gw = _make_gateway(mode=TrdexMode.SIMULATION)
    result = await gw.place("ETH/USDT", "SELL", qty=0.5, price=2_000.0)
    assert result.status == "filled"
    assert "SELL" in result.message


# ── _to_order_result conversion ───────────────────────────────────────────────

def test_to_order_result_maps_all_fields():
    er = _make_execution_result(simulated=True)
    or_ = _to_order_result(er)
    assert or_.status == "filled"
    assert or_.order_id == "abc123"
    assert or_.filled_price == pytest.approx(90_000.0)
    assert or_.filled_qty == pytest.approx(0.01)
    assert "Simulated" in or_.message


def test_to_order_result_live_label():
    er = _make_execution_result(simulated=False)
    or_ = _to_order_result(er)
    assert "Live" in or_.message


# ── cancel() routing ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_routes_to_simulator():
    gw = _make_gateway(mode=TrdexMode.SIMULATION)
    # Place first to register the order in sim
    result = await gw.place("BTC/USDT", "BUY", qty=0.01, price=90_000.0)
    cancelled = await gw.cancel(result.order_id)
    assert isinstance(cancelled, bool)


@pytest.mark.asyncio
async def test_cancel_returns_false_when_live_not_configured():
    gw = _make_gateway(mode=TrdexMode.LIVE, live_executor=None)
    result = await gw.cancel("nonexistent-id")
    assert result is False


# ── reduce-only orders pass the kill switch (closing must stay possible) ─────

@pytest.mark.asyncio
async def test_kill_switch_blocks_opening_orders():
    gw = _make_gateway(kill_switch_active=True)
    result = await gw.place("BTC/USDT", "BUY", qty=0.01, price=90_000.0)
    assert result.status == "rejected"
    assert "Kill switch" in result.message


@pytest.mark.asyncio
async def test_kill_switch_lets_reduce_only_orders_through():
    gw = _make_gateway(kill_switch_active=True)
    result = await gw.place(
        "BTC/USDT", "SELL", qty=0.01, price=90_000.0,
        idempotency_key="close:1", reduce_only=True,
    )
    assert result.status == "filled"
