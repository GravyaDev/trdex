"""The agent decides on live candles, never on stale history from the DB.

The ``ohlcv`` table also holds the regime refresher's 5-year history,
forward-filled weekly. The runner used to read ``ORDER BY ts ASC LIMIT
100`` (the *oldest* bars) and accept any non-empty result.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trdex.agents.runner import AgentRunner, _db_candles_fresh

NOW = datetime(2026, 10, 9, 12, 30, tzinfo=UTC)


def _rows(last: datetime, n: int = 100):
    return [
        SimpleNamespace(
            timestamp=(last - timedelta(hours=n - 1 - i)).replace(tzinfo=None),
            open=1.0,
            high=1.0,
            low=1.0,
            close=float(i),
            volume=1.0,
        )
        for i in range(n)
    ]


def test_fresh_means_newest_bar_within_two_bars():
    assert _db_candles_fresh(_rows(NOW - timedelta(minutes=90)), "1h", NOW)
    assert not _db_candles_fresh(_rows(NOW - timedelta(hours=3)), "1h", NOW)
    assert not _db_candles_fresh(_rows(NOW - timedelta(days=7)), "1h", NOW)
    assert not _db_candles_fresh([], "1h", NOW)
    assert not _db_candles_fresh(_rows(NOW), "weird", NOW)


@pytest.mark.asyncio
async def test_stale_db_history_falls_back_to_the_live_feed():
    feeds = MagicMock()
    feeds.get_ticker_aggregated = AsyncMock(return_value=SimpleNamespace(price=Decimal("100")))
    live = [
        SimpleNamespace(
            timestamp=NOW - timedelta(hours=1), open=1, high=1, low=1, close=42, volume=1
        )
    ]
    feeds.get_ohlcv = AsyncMock(return_value=live)
    runner = AgentRunner(session=MagicMock(), feed_manager=feeds)
    runner._ohlcv_repo = MagicMock()
    runner._ohlcv_repo.fetch_latest = AsyncMock(return_value=_rows(NOW - timedelta(days=6)))
    runner._load_portfolio_context = AsyncMock()
    captured = {}

    async def fake_cycle(**kw):
        captured["candles"] = kw["market_snapshot"].candles
        raise RuntimeError("stop here")

    with patch("trdex.agents.runner.run_agent_cycle", fake_cycle), pytest.raises(RuntimeError):
        await runner.run("BTC/USDT")
    assert [c[4] for c in captured["candles"]] == [42.0]
    runner._ohlcv_repo.fetch_latest.assert_awaited_once_with("BTC/USDT", "1h", limit=100)
