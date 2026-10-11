"""LivePerpExecutor — CCXT is always mocked, never real network calls."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from trdex.execution.live_perp_executor import LivePerpExecutor, perp_symbol
from trdex.execution.models import Order, OrderType, Side

FILLED = {
    "id": "p-1", "symbol": "BTC/USDT:USDT", "side": "sell", "amount": 0.012, "filled": 0.012,
    "average": 90_000.0, "fee": {"cost": 0.43}, "timestamp": 1_760_000_000_000,
}


def _exchange(**over):
    ex = MagicMock()
    ex.load_markets = AsyncMock()
    ex.amount_to_precision = MagicMock(side_effect=lambda sym, a: f"{a:.3f}")
    ex.set_margin_mode = AsyncMock()
    ex.set_leverage = AsyncMock()
    ex.create_order = AsyncMock(return_value={"id": "p-1"})
    ex.fetch_order = AsyncMock(return_value=FILLED)
    for k, v in over.items():
        setattr(ex, k, v)
    return ex


def _order(side=Side.SELL, amount="0.0123", reduce_only=False, leverage=3):
    return Order(symbol="BTC/USDT", side=side, type=OrderType.MARKET, amount=Decimal(amount),
                 price=Decimal("90000"), reduce_only=reduce_only, leverage=leverage)


def test_perp_symbol_mapping():
    assert perp_symbol("BTC/USDT") == "BTC/USDT:USDT"
    assert perp_symbol("ETH/USDC") == "ETH/USDC:USDC"
    assert perp_symbol("BTC/USDT:USDT") == "BTC/USDT:USDT"


@pytest.mark.asyncio
async def test_entry_sets_isolated_margin_and_leverage_once_then_orders():
    ex = _exchange()
    executor = LivePerpExecutor(ex)
    result = await executor.execute(_order())
    ex.set_margin_mode.assert_awaited_once_with("isolated", "BTC/USDT:USDT")
    ex.set_leverage.assert_awaited_once_with(3, "BTC/USDT:USDT")
    ex.create_order.assert_awaited_once_with(
        symbol="BTC/USDT:USDT", type="market", side="sell", amount=0.012, params={}
    )
    assert result.symbol == "BTC/USDT" and result.filled_amount == Decimal("0.012")
    await executor.execute(_order())
    assert ex.set_leverage.await_count == 1 and ex.load_markets.await_count == 1  # cached


@pytest.mark.asyncio
async def test_close_is_reduce_only_and_never_touches_leverage():
    ex = _exchange()
    await LivePerpExecutor(ex).execute(_order(side=Side.BUY, reduce_only=True, leverage=1))
    assert ex.create_order.await_args.kwargs["params"] == {"reduceOnly": True}
    ex.set_leverage.assert_not_awaited()


@pytest.mark.asyncio
async def test_already_isolated_is_fine_other_errors_are_not():
    ok = _exchange(set_margin_mode=AsyncMock(side_effect=Exception("-4046 No need to change margin type.")))
    await LivePerpExecutor(ok).execute(_order())
    ok.create_order.assert_awaited_once()
    bad = _exchange(set_margin_mode=AsyncMock(side_effect=Exception("-2015 Invalid API-key")))
    with pytest.raises(Exception, match="Invalid API-key"):
        await LivePerpExecutor(bad).execute(_order())
    bad.create_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_amount_rounding_to_zero_is_refused():
    with pytest.raises(ValueError, match="rounds to 0"):
        await LivePerpExecutor(_exchange()).execute(_order(amount="0.0001"))


def test_gateway_picks_the_executor_for_the_venue(monkeypatch):
    from trdex.config import TrdexMode, get_settings
    from trdex.execution.default_gateway import DefaultExecutionGateway

    settings = get_settings().model_copy(
        update={"mode": TrdexMode.LIVE, "binance_api_key": "k", "binance_api_secret": "s"}
    )
    built = []
    monkeypatch.setattr(
        "trdex.execution.live_perp_executor.LivePerpExecutor.from_settings",
        classmethod(lambda cls, s: built.append("perp") or SimpleNamespace(kind="perp")),
    )
    monkeypatch.setattr(
        "trdex.execution.live_executor.LiveExecutor.from_settings",
        classmethod(lambda cls, s: built.append("spot") or SimpleNamespace(kind="spot")),
    )

    class Cfg:
        def __init__(self, venue):
            self.venue = venue

        def get(self, category, key, default=""):
            return self.venue if key == "execution_venue" else default

    for venue, kind in (("usdm", "perp"), ("spot", "spot")):
        monkeypatch.setattr("trdex.services.runtime_config.get_config_service", lambda v=venue: Cfg(v))
        assert DefaultExecutionGateway.create(settings)._live_executor.kind == kind
    monkeypatch.setattr("trdex.services.runtime_config.get_config_service", lambda: Cfg("margin"))
    assert DefaultExecutionGateway.create(settings)._live_executor is None  # fail closed
