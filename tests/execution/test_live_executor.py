"""Tests for LiveExecutor — CCXT exchange is always mocked, never real network calls."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from trdex.execution.live_executor import LiveExecutor, _parse_ccxt_result
from trdex.execution.models import Order, OrderType, Side


def _mock_exchange(create_response: dict, fetch_response: dict) -> MagicMock:
    ex = MagicMock()
    ex.create_order = AsyncMock(return_value=create_response)
    ex.fetch_order = AsyncMock(return_value=fetch_response)
    ex.cancel_order = AsyncMock(return_value={})
    ex.close = AsyncMock()
    return ex


_CCXT_FILLED = {
    "id": "order-999",
    "symbol": "BTC/USDT",
    "side": "buy",
    "amount": 0.01,
    "filled": 0.01,
    "average": 90_000.0,
    "price": 90_000.0,
    "fee": {"cost": 0.9, "currency": "USDT"},
    "timestamp": int(datetime.now(tz=timezone.utc).timestamp() * 1000),
    "status": "closed",
}


def _make_order(side: Side = Side.BUY) -> Order:
    return Order(
        symbol="BTC/USDT",
        side=side,
        type=OrderType.MARKET,
        amount=Decimal("0.01"),
        price=Decimal("90000"),
    )


# ── _parse_ccxt_result ────────────────────────────────────────────────────────

def test_parse_ccxt_result_maps_fields():
    result = _parse_ccxt_result(_CCXT_FILLED, simulated=False)
    assert result.order_id == "order-999"
    assert result.symbol == "BTC/USDT"
    assert result.side == Side.BUY
    assert result.filled_amount == Decimal("0.01")
    assert result.filled_price == Decimal("90000.0")
    assert result.fee == Decimal("0.9")
    assert result.simulated is False


def test_parse_ccxt_result_simulated_flag():
    result = _parse_ccxt_result(_CCXT_FILLED, simulated=True)
    assert result.simulated is True


# ── LiveExecutor.execute() ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_calls_create_and_fetch_order():
    exchange = _mock_exchange(
        create_response={"id": "order-999"},
        fetch_response=_CCXT_FILLED,
    )
    executor = LiveExecutor(exchange)
    result = await executor.execute(_make_order())

    exchange.create_order.assert_awaited_once_with(
        symbol="BTC/USDT",
        type="limit",
        side="buy",
        amount=pytest.approx(0.01),
        price=pytest.approx(90_000.0),
    )
    exchange.fetch_order.assert_awaited_once_with("order-999", "BTC/USDT")
    assert result.order_id == "order-999"
    assert result.filled_amount == Decimal("0.01")


@pytest.mark.asyncio
async def test_execute_sell_order():
    exchange = _mock_exchange(
        create_response={"id": "order-sell-1"},
        fetch_response={**_CCXT_FILLED, "id": "order-sell-1", "side": "sell"},
    )
    executor = LiveExecutor(exchange)
    result = await executor.execute(_make_order(side=Side.SELL))

    exchange.create_order.assert_awaited_once()
    call_kwargs = exchange.create_order.call_args
    assert call_kwargs.kwargs["side"] == "sell"
    assert result.side == Side.SELL


@pytest.mark.asyncio
async def test_execute_raises_on_exchange_error():
    exchange = MagicMock()
    exchange.create_order = AsyncMock(side_effect=RuntimeError("Exchange down"))
    executor = LiveExecutor(exchange)

    with pytest.raises(RuntimeError, match="Exchange down"):
        await executor.execute(_make_order())


@pytest.mark.asyncio
async def test_execute_raises_without_price():
    exchange = _mock_exchange({}, {})
    executor = LiveExecutor(exchange)
    order_no_price = Order(
        symbol="BTC/USDT",
        side=Side.BUY,
        type=OrderType.MARKET,
        amount=Decimal("0.01"),
        price=None,
    )
    with pytest.raises(ValueError, match="requires a price"):
        await executor.execute(order_no_price)


# ── LiveExecutor.cancel() ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_calls_exchange_cancel_order():
    exchange = _mock_exchange({}, {})
    executor = LiveExecutor(exchange)
    result = await executor.cancel("order-999")
    exchange.cancel_order.assert_awaited_once_with("order-999")
    assert result is True


@pytest.mark.asyncio
async def test_cancel_returns_false_on_error():
    exchange = MagicMock()
    exchange.cancel_order = AsyncMock(side_effect=RuntimeError("not found"))
    executor = LiveExecutor(exchange)
    result = await executor.cancel("bad-id")
    assert result is False


# ── LiveExecutor.close() ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_releases_exchange():
    exchange = _mock_exchange({}, {})
    executor = LiveExecutor(exchange)
    await executor.close()
    exchange.close.assert_awaited_once()
