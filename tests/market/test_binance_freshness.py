"""Freshness guard test for BinanceFeed.get_ticker — protects against delisted symbols."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trdex.market.feeds.binance import BinanceFeed, StaleTickerError


class _FakeExchange:
    """Minimal stub for ccxt.binance that returns a caller-supplied ticker."""

    def __init__(self, raw: dict) -> None:
        self._raw = raw

    async def fetch_ticker(self, symbol: str) -> dict:
        return dict(self._raw)

    async def close(self) -> None:
        pass


async def _run_with(feed: BinanceFeed, raw: dict):
    feed._exchange = _FakeExchange(raw)  # type: ignore[assignment]
    return await feed.get_ticker("RNDR/USDT")


@pytest.mark.asyncio
async def test_fresh_ticker_returns_price() -> None:
    feed = BinanceFeed()
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    ticker = await _run_with(feed, {"last": 123.45, "timestamp": now_ms})
    assert float(ticker.price) == 123.45
    assert ticker.source == "binance"


@pytest.mark.asyncio
async def test_stale_ticker_raises() -> None:
    """Ticker older than 5 minutes must raise StaleTickerError (delisted symbol guard)."""
    feed = BinanceFeed()
    old = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    old_ms = int(old.timestamp() * 1000)
    with pytest.raises(StaleTickerError, match="likely delisted"):
        await _run_with(feed, {"last": 7.03, "timestamp": old_ms})


@pytest.mark.asyncio
async def test_borderline_ticker_just_inside_threshold() -> None:
    """A ticker 4 minutes old should still pass — threshold is 5 min."""
    feed = BinanceFeed()
    recent = datetime.now(tz=timezone.utc) - timedelta(minutes=4)
    recent_ms = int(recent.timestamp() * 1000)
    ticker = await _run_with(feed, {"last": 0.5, "timestamp": recent_ms})
    assert float(ticker.price) == 0.5
