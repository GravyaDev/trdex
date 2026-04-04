"""Shared test fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trdex.market.models import OHLCV


@pytest.fixture
def sample_candles() -> list[OHLCV]:
    """Generate 50 sample candles with a simple uptrend then downtrend."""
    candles: list[OHLCV] = []
    base_price = 100.0
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    for i in range(50):
        # Uptrend for first 30, downtrend for last 20
        price = base_price + i * 0.5 if i < 30 else base_price + 30 * 0.5 - (i - 30) * 0.8

        candles.append(
            OHLCV(
                timestamp=start + timedelta(hours=i),
                open=Decimal(str(price - 0.2)),
                high=Decimal(str(price + 0.5)),
                low=Decimal(str(price - 0.5)),
                close=Decimal(str(price)),
                volume=Decimal("1000"),
            )
        )
    return candles
