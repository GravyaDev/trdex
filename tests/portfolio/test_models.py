"""Tests for portfolio models."""

from datetime import UTC, datetime
from decimal import Decimal

from trdex.portfolio.models import Portfolio, Position


def test_position_unrealized_pnl_long() -> None:
    pos = Position(
        symbol="BTC/USDT",
        side="long",
        entry_price=Decimal("60000"),
        amount=Decimal("0.5"),
        current_price=Decimal("65000"),
        opened_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    assert pos.unrealized_pnl == Decimal("2500.0")


def test_position_unrealized_pnl_short() -> None:
    pos = Position(
        symbol="ETH/USDT",
        side="short",
        entry_price=Decimal("3500"),
        amount=Decimal("2"),
        current_price=Decimal("3300"),
        opened_at=datetime(2026, 4, 1, tzinfo=UTC),
    )
    assert pos.unrealized_pnl == Decimal("400")


def test_portfolio_equity() -> None:
    portfolio = Portfolio(
        balance=Decimal("10000"),
        positions=[
            Position(
                symbol="BTC/USDT",
                side="long",
                entry_price=Decimal("60000"),
                amount=Decimal("0.1"),
                current_price=Decimal("62000"),
                opened_at=datetime(2026, 4, 1, tzinfo=UTC),
            )
        ],
    )
    # Balance 10000 + unrealized (62000-60000)*0.1 = 200
    assert portfolio.equity == Decimal("10200.0")


def test_portfolio_win_rate() -> None:
    portfolio = Portfolio(total_trades=10, winning_trades=6)
    assert portfolio.win_rate == 0.6


def test_portfolio_win_rate_zero_trades() -> None:
    portfolio = Portfolio()
    assert portfolio.win_rate == 0.0
