"""End-to-end test: market data → agent cycle → simulated order."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from trdex.agents.graph import run_agent_cycle
from trdex.agents.intent import Intent
from trdex.agents.state import AgentState, MarketSnapshot


def _make_candles(n: int = 30, base_price: float = 50_000.0) -> list:
    """Generate synthetic OHLCV candles."""
    candles = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        close = base_price + (i * 10)  # gentle uptrend
        candles.append((start + timedelta(hours=i), close - 50, close + 50, close - 100, close, 1000.0))
    return candles


@pytest.fixture
def btc_snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="BTC/USDT",
        price=51_000.0,
        candles=_make_candles(30),
    )


async def test_full_cycle_simulation(btc_snapshot: MarketSnapshot) -> None:
    """Full cycle runs without errors in simulation mode and produces an order."""
    # Patch Qdrant/Jina so the test doesn't need external services
    with patch(
        "trdex.agents.scout.ContextIngestionPipeline.query",
        new_callable=AsyncMock,
        return_value=[
            {"text": "BTC surges on ETF inflows", "source": "mock", "sentiment": 0.6, "published_at": None}
        ],
    ):
        state: AgentState = await run_agent_cycle("BTC/USDT", market_snapshot=btc_snapshot)

    assert state.symbol == "BTC/USDT"
    assert state.run_id != ""
    assert state.completed_at is not None
    assert state.analysis.intent in (Intent.OPEN_LONG, Intent.CLOSE_LONG, Intent.HOLD)
    assert state.order.status in ("filled", "skipped", "rejected")


async def test_cycle_hold_when_no_candles() -> None:
    """Without candles the analyst returns HOLD and executor skips."""
    snapshot = MarketSnapshot(symbol="ETH/USDT", price=3_000.0, candles=[])

    with patch(
        "trdex.agents.scout.ContextIngestionPipeline.query",
        new_callable=AsyncMock,
        return_value=[],
    ):
        state: AgentState = await run_agent_cycle("ETH/USDT", market_snapshot=snapshot)

    assert state.analysis.intent == Intent.HOLD
    assert state.order.status == "skipped"


async def test_cycle_risk_blocks_low_confidence() -> None:
    """Risk manager blocks trades when there is insufficient data for confidence."""
    # 5 candles — not enough for RSI(14) or SMA(21) → analyst returns HOLD → skipped
    few_candles = _make_candles(n=5)
    snapshot = MarketSnapshot(symbol="BTC/USDT", price=50_000.0, candles=few_candles)

    with patch(
        "trdex.agents.scout.ContextIngestionPipeline.query",
        new_callable=AsyncMock,
        return_value=[],
    ):
        state: AgentState = await run_agent_cycle("BTC/USDT", market_snapshot=snapshot)

    # Not enough data → HOLD → risk blocks → skipped
    assert state.analysis.intent == Intent.HOLD
    assert state.order.status == "skipped"
