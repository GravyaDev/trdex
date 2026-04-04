"""Unit tests for OHLCVRepository (no live DB required)."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import polars as pl
import pytest

from trdex.market.models import OHLCV
from trdex.storage.models import OHLCVRecord
from trdex.storage.ohlcv_repo import OHLCVRepository


def _make_ohlcv(n: int = 5) -> list[OHLCV]:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        OHLCV(
            timestamp=base + timedelta(hours=i),
            open=Decimal("50000"),
            high=Decimal("51000"),
            low=Decimal("49000"),
            close=Decimal("50500"),
            volume=Decimal("100"),
        )
        for i in range(n)
    ]


def _make_records(n: int = 5) -> list[OHLCVRecord]:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    records = []
    for i in range(n):
        r = OHLCVRecord()
        r.id = i
        r.symbol = "BTC/USDT"
        r.timeframe = "1h"
        r.timestamp = base + timedelta(hours=i)
        r.open = 50000.0
        r.high = 51000.0
        r.low = 49000.0
        r.close = 50500.0
        r.volume = 100.0
        r.source = "binance"
        records.append(r)
    return records


async def test_upsert_returns_zero_on_empty() -> None:
    session = AsyncMock()
    repo = OHLCVRepository(session)
    inserted = await repo.upsert("BTC/USDT", "1h", [])
    assert inserted == 0
    session.execute.assert_not_called()


async def test_upsert_calls_execute() -> None:
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 3
    session.execute.return_value = mock_result

    repo = OHLCVRepository(session)
    candles = _make_ohlcv(3)
    inserted = await repo.upsert("BTC/USDT", "1h", candles)

    session.execute.assert_called_once()
    session.commit.assert_called_once()
    assert inserted == 3


async def test_fetch_polars_empty_returns_schema() -> None:
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    session.execute.return_value = result_mock

    repo = OHLCVRepository(session)
    df = await repo.fetch_polars("BTC/USDT", "1h")

    assert isinstance(df, pl.DataFrame)
    assert len(df) == 0
    assert "close" in df.columns


async def test_fetch_polars_returns_dataframe() -> None:
    session = AsyncMock()
    records = _make_records(5)
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = records
    session.execute.return_value = result_mock

    repo = OHLCVRepository(session)
    df = await repo.fetch_polars("BTC/USDT", "1h")

    assert isinstance(df, pl.DataFrame)
    assert len(df) == 5
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert df["close"].to_list() == [50500.0] * 5
