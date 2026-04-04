"""Tests for market data models."""

from datetime import UTC, datetime
from decimal import Decimal

from trdex.market.models import OHLCV, Ticker


def test_ticker_creation() -> None:
    t = Ticker(
        symbol="BTC/USDT",
        price=Decimal("67000.50"),
        timestamp=datetime(2026, 4, 4, 12, 0, tzinfo=UTC),
        source="binance",
    )
    assert t.symbol == "BTC/USDT"
    assert t.price == Decimal("67000.50")
    assert t.source == "binance"


def test_ohlcv_creation() -> None:
    candle = OHLCV(
        timestamp=datetime(2026, 4, 4, 12, 0, tzinfo=UTC),
        open=Decimal("67000"),
        high=Decimal("67500"),
        low=Decimal("66800"),
        close=Decimal("67200"),
        volume=Decimal("150.5"),
    )
    assert candle.close == Decimal("67200")
    assert candle.volume == Decimal("150.5")
