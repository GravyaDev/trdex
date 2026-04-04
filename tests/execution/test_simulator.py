"""Tests for paper trading simulator."""

import pytest
from decimal import Decimal

from trdex.execution.models import Order, OrderType, Side
from trdex.execution.simulator import Simulator


async def test_simulator_executes_order() -> None:
    sim = Simulator()
    order = Order(
        symbol="BTC/USDT",
        side=Side.BUY,
        type=OrderType.MARKET,
        amount=Decimal("0.1"),
        price=Decimal("67000"),
    )
    result = await sim.execute(order)

    assert result.simulated is True
    assert result.symbol == "BTC/USDT"
    assert result.side == Side.BUY
    assert result.filled_amount == Decimal("0.1")
    assert result.filled_price == Decimal("67000")
    assert result.fee > 0
    assert len(result.order_id) > 0


async def test_simulator_fee_calculation() -> None:
    sim = Simulator(fee_rate=Decimal("0.001"))
    order = Order(
        symbol="ETH/USDT",
        side=Side.SELL,
        type=OrderType.MARKET,
        amount=Decimal("1"),
        price=Decimal("3500"),
    )
    result = await sim.execute(order)

    expected_fee = Decimal("1") * Decimal("3500") * Decimal("0.001")
    assert result.fee == expected_fee


async def test_simulator_cancel_nonexistent() -> None:
    sim = Simulator()
    assert await sim.cancel("nonexistent") is False


async def test_simulator_market_order_no_price_raises() -> None:
    sim = Simulator()
    order = Order(
        symbol="BTC/USDT",
        side=Side.BUY,
        type=OrderType.MARKET,
        amount=Decimal("0.1"),
        price=None,
    )
    with pytest.raises(ValueError, match="no price"):
        await sim.execute(order)


async def test_simulator_stores_order_on_execute() -> None:
    sim = Simulator()
    order = Order(
        symbol="BTC/USDT",
        side=Side.BUY,
        type=OrderType.LIMIT,
        amount=Decimal("0.1"),
        price=Decimal("60000"),
    )
    result = await sim.execute(order)
    assert result.order_id in sim._orders
    assert await sim.cancel(result.order_id) is True
    assert result.order_id not in sim._orders
