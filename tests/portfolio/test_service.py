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


def _wire_atomic_close_session(repo: MagicMock, live_position, current_balance: Decimal) -> None:
    """Wire the session execute() side_effect for the new atomic close path.

    The atomic ``record_close_fill`` makes two ``session.execute(...)``
    calls in order:

        1. ``select(PositionRecord).where(id == position.id)`` →
           ``result.scalar_one_or_none() == live_position`` (or None)
        2. ``BalanceRepository.current_balance()`` →
           ``result.scalar_one_or_none() == current_balance``

    This helper wires both onto a single mock session.
    """
    pos_result = MagicMock()
    pos_result.scalar_one_or_none.return_value = live_position

    balance_result = MagicMock()
    balance_result.scalar_one_or_none.return_value = current_balance

    repo._session.execute = AsyncMock(side_effect=[pos_result, balance_result])
    repo._session.add = MagicMock()
    repo._session.commit = AsyncMock()
    repo._session.refresh = AsyncMock()


async def test_close_fill_buy_profit_writes_positive_pnl() -> None:
    """D17: position update + ledger row commit atomically (single commit)."""
    repo = _make_repo_mock()
    feeds = MagicMock()
    service = PortfolioService(repo, feeds)

    # Caller's snapshot — service should NOT trust this, it re-reads.
    snapshot = _position(entry_price="90000", amount="0.01")
    # Live row that the service finds in the DB.
    live = _position(entry_price="90000", amount="0.01")
    live.status = "open"

    _wire_atomic_close_session(repo, live, current_balance=Decimal("10000"))

    updated, _balance_row = await service.record_close_fill(
        position=snapshot,
        exit_price=Decimal("91000"),  # +1000 per coin * 0.01 = +10 USDT
        fee=Decimal("0.1"),
        closed_by="agent_signal",
    )

    # The live row was mutated, not the snapshot.
    assert updated is live
    assert live.status == "closed"
    assert live.exit_price == Decimal("91000")

    # Single atomic commit (D17): exactly one commit awaited.
    repo._session.commit.assert_awaited_once()

    # Ledger row appended via session.add — pnl = (91000 - 90000) * 0.01 - 0.1 = 9.9
    assert repo._session.add.called
    added_record = repo._session.add.call_args.args[0]
    assert added_record.event_type == "trade_fill"
    assert added_record.amount == Decimal("9.9")
    assert added_record.balance_after == Decimal("10009.9")
    # D20: closed_by must be embedded in the note for inspect_runs to parse.
    assert "closed_by=agent_signal" in added_record.note


async def test_close_fill_buy_loss_writes_negative_pnl() -> None:
    repo = _make_repo_mock()
    feeds = MagicMock()
    service = PortfolioService(repo, feeds)

    snapshot = _position(entry_price="90000", amount="0.01")
    live = _position(entry_price="90000", amount="0.01")
    live.status = "open"

    _wire_atomic_close_session(repo, live, current_balance=Decimal("10000"))

    await service.record_close_fill(
        position=snapshot,
        exit_price=Decimal("89000"),  # -1000 * 0.01 = -10 USDT
        fee=Decimal("0"),
    )

    added_record = repo._session.add.call_args.args[0]
    assert added_record.amount == Decimal("-10.00")
    assert added_record.balance_after == Decimal("9990.00")


async def test_close_fill_raises_if_position_vanished() -> None:
    """D14 / D17: if the live row is missing, raise — caller handles."""
    repo = _make_repo_mock()
    feeds = MagicMock()
    service = PortfolioService(repo, feeds)

    _wire_atomic_close_session(repo, live_position=None, current_balance=Decimal("10000"))

    with pytest.raises(RuntimeError, match="vanished"):
        await service.record_close_fill(
            position=_position(),
            exit_price=Decimal("91000"),
        )

    # No commit happened — atomic abort.
    repo._session.commit.assert_not_awaited()


async def test_close_fill_refuses_double_close() -> None:
    """D17: refuse to re-close a position that's already in 'closed' state."""
    repo = _make_repo_mock()
    feeds = MagicMock()
    service = PortfolioService(repo, feeds)

    already_closed = _position()
    already_closed.status = "closed"

    _wire_atomic_close_session(repo, already_closed, current_balance=Decimal("10000"))

    with pytest.raises(RuntimeError, match="already"):
        await service.record_close_fill(
            position=_position(),
            exit_price=Decimal("91000"),
        )

    repo._session.commit.assert_not_awaited()
