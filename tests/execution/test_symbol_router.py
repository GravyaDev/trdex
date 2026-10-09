"""Symbol router tests.

The router today is crypto-only. Forex/commodity/index symbols
raise SymbolNotRoutable — Telegram signals for those get skipped
with a logged reason. When the Multi-asset Forex epic lands, the
router will add a forex branch; until then the executor is
intentionally single-asset-class.
"""

from __future__ import annotations

import pytest

from trdex.execution.symbol_router import (
    SymbolNotRoutable,
    is_crypto,
    route,
)


class FakePriceFeed:
    name = "fake"


class FakeGateway:
    pass


@pytest.mark.parametrize(
    "symbol,expected",
    [
        ("BTC/USDT", True),
        ("ETH/USDT", True),
        ("SOL/USDT", True),
        ("EUR/USD", False),
        ("XAU/USD", False),
        ("NAS100/USD", False),
        ("AAPL", False),
        ("", False),
    ],
)
def test_is_crypto_classification(symbol: str, expected: bool) -> None:
    assert is_crypto(symbol) is expected


def test_route_crypto_returns_feed_and_gateway() -> None:
    feed = FakePriceFeed()
    gateway = FakeGateway()
    got_feed, got_gateway = route("BTC/USDT", feed=feed, gateway=gateway)
    assert got_feed is feed
    assert got_gateway is gateway


def test_route_forex_raises() -> None:
    with pytest.raises(SymbolNotRoutable) as exc_info:
        route("EUR/USD", feed=FakePriceFeed(), gateway=FakeGateway())
    assert "EUR/USD" in str(exc_info.value)


def test_route_commodity_raises() -> None:
    with pytest.raises(SymbolNotRoutable):
        route("XAU/USD", feed=FakePriceFeed(), gateway=FakeGateway())
