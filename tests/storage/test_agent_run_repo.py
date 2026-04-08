"""Unit tests for AgentRunRepository.narrative_context() (no live DB)."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from trdex.storage.agent_run_models import AgentRunRecord
from trdex.storage.agent_run_repo import AgentRunRepository


def _make_run(
    *,
    signal: str = "open_long",
    confidence: float = 0.6,
    risk_approved: bool = True,
    order_status: str = "filled",
    minutes_ago: int = 0,
) -> AgentRunRecord:
    r = AgentRunRecord()
    r.id = 1
    r.run_id = "00000000-0000-0000-0000-000000000000"
    r.symbol = "BTC/USDT"
    r.ran_at = datetime(2026, 4, 7, 9, 0, 0) - timedelta(minutes=minutes_ago)
    r.signal = signal
    r.confidence = confidence
    r.risk_approved = risk_approved
    r.order_status = order_status
    r.reasoning = ""
    r.indicators = {}
    r.risk_reason = ""
    r.position_size = 0
    r.stop_loss_pct = 0
    r.take_profit_pct = 0
    r.filled_price = None
    r.filled_qty = None
    r.order_message = ""
    r.error = None
    return r


async def test_narrative_empty_returns_no_runs_message() -> None:
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    session.execute.return_value = result_mock

    repo = AgentRunRepository(session)
    narr = await repo.narrative_context("BTC/USDT")

    assert narr.count == 0
    assert "No prior runs" in narr.text
    assert narr.signals == {}
    assert narr.approval_rate == 0.0
    assert narr.fill_rate == 0.0


async def test_narrative_aggregates_signals_and_rates() -> None:
    session = AsyncMock()
    runs = [
        _make_run(signal="open_long", risk_approved=True, order_status="filled", minutes_ago=0),
        _make_run(signal="hold", risk_approved=False, order_status="skipped", minutes_ago=15),
        _make_run(signal="open_long", risk_approved=True, order_status="rejected", minutes_ago=30),
        _make_run(signal="close_long", risk_approved=True, order_status="filled", minutes_ago=45),
    ]
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = runs
    session.execute.return_value = result_mock

    repo = AgentRunRepository(session)
    narr = await repo.narrative_context("BTC/USDT", limit=10)

    assert narr.count == 4
    assert narr.signals == {"open_long": 2, "hold": 1, "close_long": 1}
    assert narr.approval_rate == 0.75  # 3 of 4 approved
    assert narr.fill_rate == 0.5  # 2 of 4 filled
    assert "BTC/USDT" in narr.text
    assert "open_long:2" in narr.text
    assert narr.text.count("\n") == 4  # header + 4 lines


async def test_recent_for_symbol_calls_session() -> None:
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    session.execute.return_value = result_mock

    repo = AgentRunRepository(session)
    out = await repo.recent_for_symbol("ETH/USDT", limit=5)

    assert out == []
    session.execute.assert_called_once()
