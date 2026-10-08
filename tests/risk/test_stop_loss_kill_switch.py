"""StopLossMonitor safety with the kill switch active, and real equity drawdowns.

Fix 1: a tripped kill switch must not leave open positions unmanaged —
per-position SL/TP/trailing keep running and their closes are
reduce-only orders the gateway lets through.

Fix 6: the daily limit is measured on equity (realised balance at the
start of the UTC day vs realised + unrealised now) and max drawdown is
mark-to-market. The old open-positions check (unrealised loss over the
cost of the open book) is kept under its honest name.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from trdex.risk.stop_loss import StopLossMonitor, StopReason, _kill_switch


@pytest.fixture(autouse=True)
def _reset_kill_switch():
    for attr, value in (
        ("_active", False),
        ("_reason", ""),
        ("_activated_at", None),
        ("_session_factory", None),
    ):
        setattr(_kill_switch, attr, value)
    yield
    for attr, value in (
        ("_active", False),
        ("_reason", ""),
        ("_activated_at", None),
        ("_session_factory", None),
    ):
        setattr(_kill_switch, attr, value)


def _factory():
    session = MagicMock(name="session")

    @asynccontextmanager
    async def factory():
        yield session

    return factory


def _pos(pos_id=1, symbol="BTC/USDT", amount="1", entry="10000", source="agent"):
    return SimpleNamespace(
        id=pos_id,
        symbol=symbol,
        side="BUY",
        amount=Decimal(amount),
        entry_price=Decimal(entry),
        source=source,
    )


def _monitor(
    monkeypatch,
    *,
    positions,
    price,
    balance="10000",
    peak="10000",
    day_start="10000",
    gateway=None,
    daily_dd=0.05,
    open_loss=0.10,
    max_dd=0.20,
):
    feeds = MagicMock()
    feeds.get_ticker = AsyncMock(return_value=SimpleNamespace(price=price))

    portfolio_repo = MagicMock()
    portfolio_repo.get_open_positions = AsyncMock(return_value=positions)
    monkeypatch.setattr(
        "trdex.storage.portfolio_repo.PortfolioRepository",
        MagicMock(return_value=portfolio_repo),
    )
    balance_repo = MagicMock()
    balance_repo.current_balance = AsyncMock(return_value=Decimal(balance))
    balance_repo.peak_balance = AsyncMock(return_value=Decimal(peak))
    balance_repo.balance_at = AsyncMock(
        return_value=Decimal(day_start) if day_start is not None else None
    )
    monkeypatch.setattr(
        "trdex.storage.balance_repo.BalanceRepository",
        MagicMock(return_value=balance_repo),
    )
    return StopLossMonitor(
        session_factory=_factory(),
        feed_manager=feeds,
        gateway=gateway,
        position_sl_pct=0.05,
        position_tp_pct=0.10,
        trailing_stop_pct=0.03,
        daily_drawdown_pct=daily_dd,
        open_positions_loss_pct=open_loss,
        max_drawdown_pct=max_dd,
    )


def _filled_gateway():
    gw = MagicMock()
    gw.place = AsyncMock(
        return_value=SimpleNamespace(
            status="filled",
            filled_price=9400.0,
            message="ok",
        )
    )
    return gw


def _reasons(events):
    return {e.reason for e in events}


# ── Fix 1: kill switch must not switch off position protection ────────────


@pytest.mark.asyncio
async def test_stop_loss_still_fires_when_kill_switch_is_active(monkeypatch):
    _kill_switch._active = True
    _kill_switch._reason = "manual"
    gw = _filled_gateway()
    monitor = _monitor(monkeypatch, positions=[_pos()], price=9400.0, gateway=gw)

    events = await monitor.check_now()

    assert StopReason.POSITION_STOP_LOSS in _reasons(events)
    gw.place.assert_awaited_once()
    assert gw.place.await_args.kwargs["reduce_only"] is True
    assert gw.place.await_args.kwargs["direction"] == "SELL"


@pytest.mark.asyncio
async def test_portfolio_events_not_refired_while_kill_switch_active(monkeypatch):
    _kill_switch._active = True
    monitor = _monitor(
        monkeypatch,
        positions=[],
        price=1.0,
        balance="5000",
        peak="10000",
        day_start="10000",
    )

    events = await monitor.check_now()

    assert events == []


# ── Fix 6: real daily drawdown on equity ──────────────────────────────────


@pytest.mark.asyncio
async def test_daily_drawdown_counts_realised_and_unrealised_loss(monkeypatch):
    # Day start 10_000; realised now 9_800; open position -300 → equity 9_500 (-5%).
    monitor = _monitor(
        monkeypatch,
        positions=[_pos(amount="0.1", entry="10000")],
        price=7000.0,  # 0.1 x (7000 - 10000) = -300
        balance="9800",
        day_start="10000",
        daily_dd=0.05,
        open_loss=0.99,  # isolate the daily check
    )

    events = await monitor.check_now()

    assert StopReason.DAILY_DRAWDOWN in _reasons(events)
    assert _kill_switch.active


@pytest.mark.asyncio
async def test_daily_drawdown_below_limit_does_not_trip(monkeypatch):
    monitor = _monitor(
        monkeypatch,
        positions=[],
        price=1.0,
        balance="9700",
        day_start="10000",
        daily_dd=0.05,
    )

    events = await monitor.check_now()

    assert StopReason.DAILY_DRAWDOWN not in _reasons(events)
    assert not _kill_switch.active


@pytest.mark.asyncio
async def test_daily_drawdown_fires_with_no_open_positions(monkeypatch):
    # Losses already realised today: the old code returned early with no positions.
    monitor = _monitor(
        monkeypatch,
        positions=[],
        price=1.0,
        balance="9400",
        day_start="10000",
        daily_dd=0.05,
    )

    events = await monitor.check_now()

    assert StopReason.DAILY_DRAWDOWN in _reasons(events)


@pytest.mark.asyncio
async def test_daily_baseline_falls_back_to_current_balance_without_history(monkeypatch):
    monitor = _monitor(
        monkeypatch,
        positions=[],
        price=1.0,
        balance="9000",
        day_start=None,
        daily_dd=0.05,
        max_dd=0.50,
    )

    events = await monitor.check_now()

    assert StopReason.DAILY_DRAWDOWN not in _reasons(events)


@pytest.mark.asyncio
async def test_open_positions_loss_keeps_old_semantics_under_new_name(monkeypatch):
    # One position down 12% of its own cost; equity barely moves.
    monitor = _monitor(
        monkeypatch,
        positions=[_pos(amount="0.01", entry="10000")],
        price=8800.0,
        open_loss=0.10,
        daily_dd=0.50,
    )

    events = await monitor.check_now()

    assert StopReason.OPEN_POSITIONS_LOSS in _reasons(events)
    assert StopReason.DAILY_DRAWDOWN not in _reasons(events)


# ── Fix 6: max drawdown is mark-to-market ─────────────────────────────────


@pytest.mark.asyncio
async def test_max_drawdown_includes_unrealised_loss(monkeypatch):
    # Realised balance at peak, but the open book is down 2_100 → equity -21%.
    monitor = _monitor(
        monkeypatch,
        positions=[_pos(amount="1", entry="10000")],
        price=7900.0,
        max_dd=0.20,
        daily_dd=0.50,
        open_loss=0.99,
    )

    events = await monitor.check_now()

    assert StopReason.MAX_DRAWDOWN in _reasons(events)


@pytest.mark.asyncio
async def test_no_double_count_when_position_is_closed_in_the_same_cycle(monkeypatch):
    # Balance is read once at the start of the cycle, so a close persisted
    # mid-cycle is not counted both as realised and as unrealised.
    monitor = _monitor(
        monkeypatch,
        positions=[_pos(amount="0.1", entry="10000")],
        price=9400.0,  # -6% on the position: SL fires, -60 unrealised
        gateway=_filled_gateway(),
        daily_dd=0.05,
    )
    balance_repo_cls = __import__("trdex.storage.balance_repo", fromlist=["x"]).BalanceRepository
    calls = balance_repo_cls.return_value.current_balance

    events = await monitor.check_now()

    assert StopReason.POSITION_STOP_LOSS in _reasons(events)
    assert StopReason.DAILY_DRAWDOWN not in _reasons(events)
    assert calls.await_count == 1
