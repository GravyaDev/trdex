"""Unit tests for PortfolioService fill persistence (write path).

The existing ``test_models.py`` covers the read-side dataclasses. This
file focuses on ``record_open_fill`` and ``record_close_fill`` which are
the single-writer entry points used by AgentRunner and StopLossMonitor.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from trdex.portfolio.service import PortfolioService
from trdex.storage.balance_models import BalanceRecord
from trdex.storage.portfolio_models import PositionRecord


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _position(
    *,
    id: int = 1,
    symbol: str = "BTC/USDT",
    side: str = "BUY",
    entry_price: str = "90000",
    amount: str = "0.001",
) -> PositionRecord:
    r = PositionRecord()
    r.id = id
    r.symbol = symbol
    r.side = side
    r.entry_price = Decimal(entry_price)
    r.amount = Decimal(amount)
    r.budget = r.entry_price * r.amount
    r.source = "agent"
    r.signal_id = "test-run"
    r.status = "open"
    r.opened_at = datetime(2026, 4, 7, 9, 0)
    return r


def _balance_row(amount: str, balance_after: str) -> BalanceRecord:
    r = BalanceRecord()
    r.event_type = "trade_fill"
    r.amount = Decimal(amount)
    r.balance_after = Decimal(balance_after)
    r.note = ""
    r.recorded_at = datetime(2026, 4, 7, 10, 0)
    return r


def _make_repo_mock() -> MagicMock:
    """Build a mock ``PortfolioRepository`` wrapping an AsyncMock session."""
    repo = MagicMock()
    repo._session = AsyncMock()
    repo.open_position = AsyncMock()
    repo.close_position = AsyncMock()
    return repo


# ---------------------------------------------------------------------------
# record_open_fill
# ---------------------------------------------------------------------------


async def test_open_fill_buy_creates_position() -> None:
    repo = _make_repo_mock()
    feeds = MagicMock()
    service = PortfolioService(repo, feeds)

    expected = _position()
    repo.open_position.return_value = expected

    out = await service.record_open_fill(
        symbol="BTC/USDT",
        side="BUY",
        amount=Decimal("0.001"),
        entry_price=Decimal("90000"),
        budget=Decimal("90"),
        source="agent",
        signal_id="r-1",
    )

    assert out is expected
    repo.open_position.assert_awaited_once()
    kwargs = repo.open_position.call_args.kwargs
    assert kwargs["symbol"] == "BTC/USDT"
    assert kwargs["side"] == "BUY"
    assert kwargs["amount"] == Decimal("0.001")
    assert kwargs["entry_price"] == Decimal("90000")
    assert kwargs["signal_id"] == "r-1"
    assert kwargs["source"] == "agent"


async def test_open_fill_sell_is_refused_long_only() -> None:
    """A SELL fill without an existing long position must not open a short."""
    repo = _make_repo_mock()
    feeds = MagicMock()
    service = PortfolioService(repo, feeds)

    out = await service.record_open_fill(
        symbol="BTC/USDT",
        side="SELL",
        amount=Decimal("0.001"),
        entry_price=Decimal("90000"),
        budget=Decimal("90"),
    )

    assert out is None
    repo.open_position.assert_not_called()


async def test_open_fill_unknown_side_is_refused() -> None:
    repo = _make_repo_mock()
    feeds = MagicMock()
    service = PortfolioService(repo, feeds)

    out = await service.record_open_fill(
        symbol="BTC/USDT",
        side="HOLD",  # nonsense side from a hypothetical bug
        amount=Decimal("0.001"),
        entry_price=Decimal("90000"),
        budget=Decimal("90"),
    )

    assert out is None
    repo.open_position.assert_not_called()


# ---------------------------------------------------------------------------
# record_close_fill
# ---------------------------------------------------------------------------


async def test_close_fill_buy_profit_writes_positive_pnl() -> None:
    repo = _make_repo_mock()
    feeds = MagicMock()
    service = PortfolioService(repo, feeds)

    position = _position(entry_price="90000", amount="0.01")
    closed = _position(entry_price="90000", amount="0.01")
    closed.status = "closed"
    repo.close_position.return_value = closed

    # The BalanceRepository inside the service uses _session.execute.
    # It calls current_balance first (one scalar_one_or_none on balance_after)
    # then inserts a new row. Stub the first select to return 10_000 as
    # current balance.
    current_balance_result = MagicMock()
    current_balance_result.scalar_one_or_none.return_value = Decimal("10000")
    repo._session.execute.return_value = current_balance_result

    # Simulate that _session.add / refresh work transparently.
    repo._session.add = MagicMock()
    repo._session.refresh = AsyncMock()

    updated, balance_row = await service.record_close_fill(
        position=position,
        exit_price=Decimal("91000"),  # +1000 per coin * 0.01 = +10 USDT
        fee=Decimal("0.1"),           # minus fee
    )

    # Position update path
    repo.close_position.assert_awaited_once()
    close_kwargs = repo.close_position.call_args.kwargs
    assert close_kwargs["position_id"] == position.id
    assert close_kwargs["exit_price"] == Decimal("91000")
    assert updated is closed

    # Ledger write path: the BalanceRepository was given repo._session,
    # went through current_balance() + session.add(). The row passed to
    # session.add must be a BalanceRecord with a realised pnl of +9.9.
    assert repo._session.add.called
    added_record = repo._session.add.call_args.args[0]
    assert added_record.event_type == "trade_fill"
    assert added_record.amount == Decimal("9.9")  # (91000 - 90000) * 0.01 - 0.1
    # balance_after = current + pnl = 10000 + 9.9
    assert added_record.balance_after == Decimal("10009.9")


async def test_close_fill_buy_loss_writes_negative_pnl() -> None:
    repo = _make_repo_mock()
    feeds = MagicMock()
    service = PortfolioService(repo, feeds)

    position = _position(entry_price="90000", amount="0.01")
    closed = _position(entry_price="90000", amount="0.01")
    closed.status = "closed"
    repo.close_position.return_value = closed

    current_balance_result = MagicMock()
    current_balance_result.scalar_one_or_none.return_value = Decimal("10000")
    repo._session.execute.return_value = current_balance_result
    repo._session.add = MagicMock()
    repo._session.refresh = AsyncMock()

    await service.record_close_fill(
        position=position,
        exit_price=Decimal("89000"),  # -1000 per coin * 0.01 = -10 USDT
        fee=Decimal("0"),
    )

    added_record = repo._session.add.call_args.args[0]
    assert added_record.amount == Decimal("-10.00")
    assert added_record.balance_after == Decimal("9990.00")


async def test_close_fill_raises_if_position_vanished() -> None:
    repo = _make_repo_mock()
    feeds = MagicMock()
    service = PortfolioService(repo, feeds)

    repo.close_position.return_value = None  # gone from DB
    with pytest.raises(RuntimeError, match="returned None"):
        await service.record_close_fill(
            position=_position(),
            exit_price=Decimal("91000"),
        )
