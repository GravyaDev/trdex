"""Regression tests for StopLossMonitor max-drawdown kill switch logic.

Focus: Bug 8 (2026-04-08) — the pre-fix ``check_now()`` mixed realised
peak equity (from the balance ledger) with mark-to-market current equity
(``total_cost + total_unrealized``), producing a 98% false-positive
drawdown on the first trade of a fresh deploy.

The fix is to make the max-drawdown check realised-only on both sides:
both ``peak_equity`` and ``current equity`` read from BalanceRepository.
These tests lock that behaviour in.

Daily drawdown is NOT retested here because it remains mark-to-market
by design (``total_unrealized / total_cost``), which is a separate,
symmetric calculation that was not affected by Bug 8.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from trdex.risk.stop_loss import StopLossMonitor, _kill_switch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_kill_switch():
    """The module-level KillSwitch singleton persists across tests; wipe it."""
    _kill_switch._active = False
    _kill_switch._reason = ""
    _kill_switch._activated_at = None
    _kill_switch._session_factory = None  # prevent _persist() hitting real DB
    yield
    _kill_switch._active = False
    _kill_switch._reason = ""
    _kill_switch._activated_at = None
    _kill_switch._session_factory = None


def _make_session_factory():
    """A session_factory that returns an async-context-manager yielding a dummy session."""
    dummy_session = MagicMock(name="session")

    @asynccontextmanager
    async def factory():
        yield dummy_session

    return factory, dummy_session


def _make_position(
    *,
    pos_id: int,
    symbol: str,
    side: str,
    amount: str,
    entry_price: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=pos_id,
        symbol=symbol,
        side=side,
        amount=Decimal(amount),
        entry_price=Decimal(entry_price),
    )


def _make_monitor(
    session_factory,
    *,
    current_balance: Decimal,
    peak_balance: Decimal,
    open_positions: list,
    ticker_price: float,
    max_dd_pct: float = 0.20,
    daily_dd_pct: float = 0.10,
    monkeypatch=None,
) -> StopLossMonitor:
    """Wire up a StopLossMonitor with patched repos and a mock feed_manager."""
    feed_manager = MagicMock()
    feed_manager.get_ticker = AsyncMock(
        return_value=SimpleNamespace(price=ticker_price)
    )

    # Patch PortfolioRepository used inside check_now().
    portfolio_repo_instance = MagicMock()
    portfolio_repo_instance.get_open_positions = AsyncMock(return_value=open_positions)
    monkeypatch.setattr(
        "trdex.storage.portfolio_repo.PortfolioRepository",
        MagicMock(return_value=portfolio_repo_instance),
    )

    # Patch BalanceRepository used inside check_now() and _init_peak_equity().
    balance_repo_instance = MagicMock()
    balance_repo_instance.current_balance = AsyncMock(return_value=current_balance)
    balance_repo_instance.peak_balance = AsyncMock(return_value=peak_balance)
    monkeypatch.setattr(
        "trdex.storage.balance_repo.BalanceRepository",
        MagicMock(return_value=balance_repo_instance),
    )

    return StopLossMonitor(
        session_factory=session_factory,
        feed_manager=feed_manager,
        gateway=None,
        check_interval=30.0,
        max_drawdown_pct=max_dd_pct,
        daily_drawdown_pct=daily_dd_pct,
    )


# ---------------------------------------------------------------------------
# Bug 8 regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bug8_no_false_drawdown_on_fresh_deploy_with_open_position(monkeypatch):
    """Regression for Bug 8 (2026-04-08).

    Scenario: fresh deploy. Seed deposit $10,000. Agent opens one long
    position worth $200 (2% sizing). At the next StopLossMonitor tick
    the balance ledger still reads $10,000 (open fills don't write the
    ledger) so peak_equity=10000 and current equity should *also* be
    10000, giving 0% drawdown. The buggy pre-fix code computed equity
    as ``total_cost + total_unrealized ≈ 200``, giving a 98% drawdown
    and tripping the 20% kill switch on the first trade of a fresh
    deploy. This test locks the fix in.
    """
    factory, _session = _make_session_factory()
    monitor = _make_monitor(
        factory,
        current_balance=Decimal("10000.00"),
        peak_balance=Decimal("10000.00"),
        open_positions=[
            _make_position(
                pos_id=1,
                symbol="BTC/USDT",
                side="BUY",
                amount="0.002804",
                entry_price="71321.54",
            )
        ],
        ticker_price=71321.54,  # equal to entry → unrealized ≈ 0
        monkeypatch=monkeypatch,
    )

    events = await monitor.check_now()

    assert not _kill_switch.active, (
        f"kill switch should NOT trigger on fresh deploy with open position; "
        f"reason={_kill_switch._reason}"
    )
    assert not any(e.reason.value == "max_drawdown" for e in events), (
        "max_drawdown event fired on a ledger that is still at peak"
    )
    assert monitor._peak_equity == 10000.0


@pytest.mark.asyncio
async def test_max_drawdown_triggers_when_realised_cash_drops_enough(monkeypatch):
    """Realised cash below peak by >= 20% MUST trip the kill switch."""
    factory, _ = _make_session_factory()
    monitor = _make_monitor(
        factory,
        current_balance=Decimal("7500.00"),  # -25% from peak
        peak_balance=Decimal("10000.00"),
        open_positions=[
            _make_position(
                pos_id=1,
                symbol="BTC/USDT",
                side="BUY",
                amount="0.001",
                entry_price="70000",
            )
        ],
        ticker_price=70000.0,
        max_dd_pct=0.20,
        monkeypatch=monkeypatch,
    )

    events = await monitor.check_now()

    assert _kill_switch.active, "kill switch must trip on 25% realised drawdown"
    assert "Max drawdown" in _kill_switch._reason
    assert any(e.reason.value == "max_drawdown" for e in events)


@pytest.mark.asyncio
async def test_max_drawdown_below_limit_does_not_trigger(monkeypatch):
    """Realised drawdown below the configured limit must NOT trip the switch."""
    factory, _ = _make_session_factory()
    monitor = _make_monitor(
        factory,
        current_balance=Decimal("8500.00"),  # -15% from peak, below 20% limit
        peak_balance=Decimal("10000.00"),
        open_positions=[
            _make_position(
                pos_id=1,
                symbol="BTC/USDT",
                side="BUY",
                amount="0.001",
                entry_price="70000",
            )
        ],
        ticker_price=70000.0,
        max_dd_pct=0.20,
        monkeypatch=monkeypatch,
    )

    await monitor.check_now()

    assert not _kill_switch.active, (
        "kill switch must NOT trip on 15% drawdown when limit is 20%"
    )


@pytest.mark.asyncio
async def test_peak_equity_updates_upward_on_profit(monkeypatch):
    """When realised cash exceeds the previous peak, peak_equity must advance."""
    factory, _ = _make_session_factory()
    monitor = _make_monitor(
        factory,
        current_balance=Decimal("12000.00"),  # +20% above previous peak
        peak_balance=Decimal("10000.00"),
        open_positions=[
            _make_position(
                pos_id=1,
                symbol="BTC/USDT",
                side="BUY",
                amount="0.001",
                entry_price="70000",
            )
        ],
        ticker_price=70000.0,
        monkeypatch=monkeypatch,
    )

    await monitor.check_now()

    assert monitor._peak_equity == 12000.0, (
        "peak_equity must advance when current realised cash > previous peak"
    )
    assert not _kill_switch.active, "no drawdown should be reported at a new peak"
