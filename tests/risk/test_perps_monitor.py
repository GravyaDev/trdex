"""Simulated perpetuals in the StopLossMonitor: funding and liquidation."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.risk.test_stop_loss_kill_switch import _filled_gateway, _monitor, _reasons
from trdex.risk.funding import accrue_funding
from trdex.risk.stop_loss import StopReason

NOW = datetime(2026, 10, 12, 0, 30, tzinfo=UTC)


class _Session:
    def __init__(self, live):
        self.live = live
        self.added = []
        self.commits = 0

    async def execute(self, stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: self.live)

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1


def _position(side="BUY", **kw):
    base = dict(
        id=1,
        symbol="BTC/USDT",
        side=side,
        amount=Decimal("2"),
        entry_price=Decimal("100"),
        status="open",
        opened_at=datetime(2026, 10, 11, 7, 30),
        funding_paid_until=None,
        source="agent",
        leverage=3.0,
        venue="usdm",
    )
    return SimpleNamespace(**{**base, **kw})


def _factory(session):
    @asynccontextmanager
    async def factory():
        yield session

    return factory


@pytest.mark.asyncio
@pytest.mark.parametrize(("side", "sign"), [("BUY", -1), ("SELL", 1)])
async def test_funding_is_booked_once_per_8h_boundary(monkeypatch, side, sign):
    pos = _position(side)
    session = _Session(_position(side))
    bal = MagicMock(current_balance=AsyncMock(return_value=Decimal("10000")))
    monkeypatch.setattr(
        "trdex.storage.balance_repo.BalanceRepository", MagicMock(return_value=bal)
    )

    total = await accrue_funding(_factory(session), [pos], {"BTC/USDT": 100.0}, 0.0001, NOW)
    # 08:00, 16:00, 00:00 -> 3 x 2 x 100 x 0.01%
    assert total == pytest.approx(sign * 0.06)
    (row,) = session.added
    assert row.event_type == "funding" and float(row.amount) == pytest.approx(sign * 0.06)
    assert session.live.funding_paid_until == datetime(2026, 10, 12, 0, 0)
    # a second check working from a stale snapshot (e.g. /risk/check_now
    # overlapping the loop) reads the row and books nothing
    stale = _position(side)
    assert await accrue_funding(_factory(session), [stale], {"BTC/USDT": 100.0}, 0.0001, NOW) == 0
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_spot_positions_and_rows_from_before_perps_pay_no_funding(monkeypatch):
    bal = MagicMock(current_balance=AsyncMock(return_value=Decimal("10000")))
    monkeypatch.setattr(
        "trdex.storage.balance_repo.BalanceRepository", MagicMock(return_value=bal)
    )
    session = _Session(_position(venue="spot"))
    old_long = _position(venue="spot", opened_at=datetime(2026, 9, 1))
    assert (
        await accrue_funding(_factory(session), [old_long], {"BTC/USDT": 100.0}, 0.0001, NOW) == 0
    )
    assert session.added == []


@pytest.mark.asyncio
async def test_closed_or_unpriced_positions_pay_nothing(monkeypatch):
    bal = MagicMock(current_balance=AsyncMock(return_value=Decimal("10000")))
    monkeypatch.setattr(
        "trdex.storage.balance_repo.BalanceRepository", MagicMock(return_value=bal)
    )
    closed = _Session(_position(status="closed"))
    assert (
        await accrue_funding(_factory(closed), [_position()], {"BTC/USDT": 100.0}, 0.0001, NOW)
        == 0
    )
    assert await accrue_funding(_factory(closed), [_position()], {}, 0.0001, NOW) == 0
    assert closed.added == []


def _leveraged(side, entry="10000"):
    return SimpleNamespace(
        id=9,
        symbol="BTC/USDT",
        side=side,
        amount=Decimal("0.1"),
        entry_price=Decimal(entry),
        source="agent",
        leverage=3.0,
        stop_loss_pct=0.5,
        take_profit_pct=None,
        venue="usdm",
    )


@pytest.mark.asyncio
async def test_a_gap_beyond_liquidation_closes_at_the_liquidation_price(monkeypatch):
    monkeypatch.setattr("trdex.risk.funding.accrue_funding", AsyncMock(return_value=0.0))
    gw = _filled_gateway()
    # short at 10_000, 3x: liquidated at +32.83%; price gaps to 14_000
    monitor = _monitor(monkeypatch, positions=[_leveraged("SELL")], price=14_000.0, gateway=gw)
    events = await monitor.check_now()
    assert StopReason.LIQUIDATION in _reasons(events)
    kwargs = gw.place.await_args.kwargs
    assert kwargs["direction"] == "BUY" and kwargs["reduce_only"] is True
    assert kwargs["price"] == pytest.approx(10_000 * (1 + 1 / 3))  # bankruptcy: margin gone
    assert kwargs["venue"] == "usdm"


@pytest.mark.asyncio
async def test_no_simulated_liquidation_in_live_mode(monkeypatch):
    from trdex.config import TrdexMode, get_settings

    live = get_settings().model_copy(update={"mode": TrdexMode.LIVE})
    monkeypatch.setattr("trdex.config.get_settings", lambda: live)
    gw = _filled_gateway()
    monitor = _monitor(monkeypatch, positions=[_leveraged("SELL")], price=14_000.0, gateway=gw)
    events = await monitor.check_now()
    assert StopReason.LIQUIDATION not in _reasons(events)


@pytest.mark.asyncio
async def test_widened_stop_is_capped_inside_the_liquidation_buffer(monkeypatch):
    """Volatility rose after entry: the 50% stop would sit past liquidation (32.8%)."""
    monkeypatch.setattr("trdex.risk.funding.accrue_funding", AsyncMock(return_value=0.0))
    gw = _filled_gateway()
    # short at 10_000, price 11_700: +17% > 0.5 x 32.83% -> stop fires, not liquidation
    monitor = _monitor(monkeypatch, positions=[_leveraged("SELL")], price=11_700.0, gateway=gw)
    events = await monitor.check_now()
    assert StopReason.POSITION_STOP_LOSS in _reasons(events)
    assert StopReason.LIQUIDATION not in _reasons(events)


@pytest.mark.asyncio
async def test_spot_positions_are_never_capped_or_liquidated(monkeypatch):
    monkeypatch.setattr("trdex.risk.funding.accrue_funding", AsyncMock(return_value=0.0))
    gw = _filled_gateway()
    pos = _leveraged("BUY")
    pos.venue, pos.leverage = "spot", 1.0
    monitor = _monitor(monkeypatch, positions=[pos], price=4_000.0, gateway=gw)  # -60%
    events = await monitor.check_now()
    assert StopReason.LIQUIDATION not in _reasons(events)
    assert gw.place.await_args.kwargs["venue"] == "spot"
