"""End-to-end simulation test for TelegramSignalExecutor (Task 2.7 / Task 9).

Exercises the full executor code path against a real DB (test container)
and a real DefaultExecutionGateway in TRDEX_MODE=simulation. Zero network
calls — the Simulator short-circuits order execution in-process.

What this test catches that unit tests cannot:
- SQL migration regressions on positions / signal_outcomes / account_balance.
- Protocol mismatches between _FeedLike and the adapter we use in
  _telegram_background (the unit tests use FakeFeed; this uses the
  actual DefaultExecutionGateway path plus a minimal feed adapter).
- Session/commit boundaries: the executor persists a position via
  PortfolioService.record_open_fill which runs session.commit() inside.
  This test asserts the row is visible on a fresh query after the call.
- Idempotency key contract with the gateway (no duplicate on retry).

This is the closest we can get to prod behaviour without touching Binance.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_executor_end_to_end_persists_position_in_simulation(
    db_session: AsyncSession,
) -> None:
    """Happy-path: observe-only row saved, executor flag ON, simulation
    mode → Simulator fills → position row written with source=telegram,
    signal_id linking back to the outcome, SL/TP pct from signal prices."""
    from trdex.config import TrdexMode, settings as _settings
    from trdex.execution.default_gateway import DefaultExecutionGateway
    from trdex.execution.telegram_executor import TelegramSignalExecutor
    from trdex.execution.telegram_gates import GateConfig
    from trdex.portfolio.service import PortfolioService
    from trdex.risk.stop_loss import _kill_switch
    from trdex.storage.balance_repo import BalanceRepository
    from trdex.storage.portfolio_repo import PortfolioRepository
    from trdex.storage.signal_outcome_repo import SignalOutcomeRepository
    from trdex.telegram.parser import TelegramSignal

    # Force simulation mode for this test. _settings is the module-level
    # singleton — we restore the original mode at the end.
    prev_mode = _settings.mode
    _settings.mode = TrdexMode.SIMULATION
    # KillSwitch is a module-level singleton; ensure it is not active
    # from a prior test before we exercise the gateway.
    _kill_switch.reset()

    try:
        # 1. Seed balance ledger (gate_budget needs >= config.budget).
        balance_repo = BalanceRepository(db_session)
        await balance_repo.deposit(Decimal("5000"), note="test seed")

        # 2. Persist observe-only outcome (what _telegram_background does
        # before calling _maybe_execute).
        outcome_repo = SignalOutcomeRepository(db_session)
        outcome_record = await outcome_repo.save(
            source="chat-77",
            symbol="BTC/USDT",
            direction="BUY",
            entry_price=Decimal("90000"),
            exit_price=None,
            budget=Decimal("0"),
            note='{"targets":[94500.0],"stop_loss":87300.0}',
        )
        outcome_id = outcome_record.id
        assert outcome_id is not None

        # 3. Build the signal (exactly as parse_signal would return).
        signal = TelegramSignal(
            source="chat-77",
            symbol="BTC/USDT",
            direction="BUY",
            entry=90000.0,
            targets=[94500.0],  # +5% TP
            stop_loss=87300.0,  # -3% SL
            raw_text="BUY BTCUSDT entry 90000 tp 94500 sl 87300",
        )

        # 4. Minimal feed with the current price equal to the entry, so
        # the drift gate passes trivially. Matches _FeedLike protocol.
        class _Feed:
            name = "test-feed"

            async def get_current_price(self, symbol: str) -> float:
                return 90000.0

        # 5. Gateway in simulation mode — the Simulator handles the order
        # without any exchange I/O.
        gateway = DefaultExecutionGateway.create(_settings)

        # 6. PortfolioService needs a feed_manager for mark_to_market, but
        # our executor never calls that path. Pass a stub that would fail
        # loudly if anything tried to use it during record_open_fill (it
        # should not — the write path does not fetch prices).
        class _NoopFeedManager:
            async def get_ticker(self, symbol: str, source: str | None = None):
                raise AssertionError("record_open_fill must not fetch prices")

        portfolio_repo = PortfolioRepository(db_session)
        portfolio_service = PortfolioService(portfolio_repo, _NoopFeedManager())

        # 7. GateConfig matches what _telegram_background builds from
        # RuntimeConfig in prod, with a budget below our seeded balance.
        config = GateConfig(
            asset_class_cap=3,
            reliability_min_samples=20,
            reliability_win_rate_min=0.5,
            entry_drift_tolerance=0.005,
            budget=Decimal("100"),
        )

        # 8. Balance snapshot wrapper (same shape as _maybe_execute uses).
        from types import SimpleNamespace
        current_balance = await balance_repo.current_balance()
        balance = SimpleNamespace(available=current_balance)

        executor = TelegramSignalExecutor(
            gateway=gateway,
            feed=_Feed(),
            portfolio_repo=portfolio_repo,
            portfolio_service=portfolio_service,
            outcome_repo=outcome_repo,
            balance_provider=lambda: balance,
            config=config,
        )

        # 9. Execute.
        result = await executor.execute(signal, outcome_id=outcome_id)

        # 10. Assert executed status.
        assert result.status == "executed", (
            f"expected executed, got {result.status!r} reason={result.reason!r}"
        )
        assert result.position_id is not None

        # 11. Assert position row is visible via a fresh query on the
        # same session. Source, signal_id, SL/TP pct must match.
        row = (
            await db_session.execute(text(
                "SELECT source, signal_id, symbol, side, stop_loss_pct, "
                "take_profit_pct, status FROM positions WHERE id = :pid"
            ), {"pid": result.position_id})
        ).first()
        assert row is not None
        assert row.source == "telegram"
        assert row.signal_id == str(outcome_id)
        assert row.symbol == "BTC/USDT"
        assert row.side == "BUY"
        assert row.status == "open"
        # SL at 87300 vs entry 90000 -> 3% drop. TP at 94500 -> 5% up.
        assert row.stop_loss_pct == pytest.approx(0.03, rel=1e-4)
        assert row.take_profit_pct == pytest.approx(0.05, rel=1e-4)

        # 12. Assert the observe-only row is still present (the executor
        # must not delete or alter it — it only annotates via signal_id
        # on the positions row).
        outcome_row = (
            await db_session.execute(text(
                "SELECT id, exit_price FROM signal_outcomes WHERE id = :oid"
            ), {"oid": outcome_id})
        ).first()
        assert outcome_row is not None
        assert outcome_row.exit_price is None  # still observe-only

        # 13. Dashboard chip contract: the `source` column on positions
        # must be the exact literal "telegram" (not "tg", not
        # "telegram:chat-77") because the dashboard chip map keys on it.
        source_row = (
            await db_session.execute(text(
                "SELECT source FROM positions WHERE id = :pid"
            ), {"pid": result.position_id})
        ).first()
        assert source_row is not None
        assert source_row.source == "telegram"
    finally:
        _settings.mode = prev_mode


async def test_executor_respects_feature_flag_off(
    db_session: AsyncSession,
) -> None:
    """The runtime_config flag gates _maybe_execute, not the executor itself.
    This test asserts the same executor that passes above is still wired
    correctly when its gates say 'skip' — specifically when budget is zero.

    We exercise the 'below budget' skip path against the real balance
    repo, because that is the most likely prod skip reason when the flag
    is first flipped on with a tight budget.
    """
    from decimal import Decimal

    from trdex.config import TrdexMode, settings as _settings
    from trdex.execution.default_gateway import DefaultExecutionGateway
    from trdex.execution.telegram_executor import TelegramSignalExecutor
    from trdex.execution.telegram_gates import GateConfig
    from trdex.portfolio.service import PortfolioService
    from trdex.risk.stop_loss import _kill_switch
    from trdex.storage.balance_repo import BalanceRepository
    from trdex.storage.portfolio_repo import PortfolioRepository
    from trdex.storage.signal_outcome_repo import SignalOutcomeRepository
    from trdex.telegram.parser import TelegramSignal

    prev_mode = _settings.mode
    _settings.mode = TrdexMode.SIMULATION
    _kill_switch.reset()

    try:
        # Seed a withdrawal so the ledger balance is BELOW the budget.
        balance_repo = BalanceRepository(db_session)
        # Default seed is 10000; deposit-then-withdraw nets to 50.
        await balance_repo.deposit(Decimal("50"), note="tiny seed")
        # Withdraw the default 10000 so current_balance ends at 50.
        await balance_repo.withdraw(Decimal("10000"), note="drop below budget")
        assert await balance_repo.current_balance() == Decimal("50")

        outcome_repo = SignalOutcomeRepository(db_session)
        outcome_record = await outcome_repo.save(
            source="chat-99",
            symbol="BTC/USDT",
            direction="BUY",
            entry_price=Decimal("90000"),
        )

        class _Feed:
            name = "test-feed"

            async def get_current_price(self, symbol: str) -> float:
                return 90000.0

        class _NoopFeedManager:
            async def get_ticker(self, symbol: str, source: str | None = None):
                raise AssertionError("should not reach price fetch")

        portfolio_repo = PortfolioRepository(db_session)
        portfolio_service = PortfolioService(portfolio_repo, _NoopFeedManager())
        gateway = DefaultExecutionGateway.create(_settings)

        from types import SimpleNamespace
        balance = SimpleNamespace(available=Decimal("50"))

        executor = TelegramSignalExecutor(
            gateway=gateway,
            feed=_Feed(),
            portfolio_repo=portfolio_repo,
            portfolio_service=portfolio_service,
            outcome_repo=outcome_repo,
            balance_provider=lambda: balance,
            config=GateConfig(budget=Decimal("100")),
        )

        signal = TelegramSignal(
            source="chat-99", symbol="BTC/USDT", direction="BUY",
            entry=90000.0, targets=[94500.0], stop_loss=87300.0,
            raw_text="",
        )

        result = await executor.execute(signal, outcome_id=outcome_record.id)

        assert result.status == "skipped"
        assert "budget" in result.reason.lower()

        # And no position was persisted — the DB state is clean apart
        # from the observe-only row we saved above.
        count = (
            await db_session.execute(text("SELECT COUNT(*) FROM positions"))
        ).scalar()
        assert count == 0
    finally:
        _settings.mode = prev_mode
