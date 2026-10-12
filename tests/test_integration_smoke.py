"""Smoke test for the integration fixture stack.

If this file fails, every other @pytest.mark.integration test will
fail with a less informative error — so keep these assertions minimal
and focused on infrastructure only. Do not add business-logic tests here.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_db_session_can_run_a_trivial_query(db_session: AsyncSession) -> None:
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1


async def test_migrations_created_positions_table(db_session: AsyncSession) -> None:
    """If migrations did not run, this query raises UndefinedTable."""
    result = await db_session.execute(text(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'positions'"
    ))
    assert result.scalar() == 1


async def test_timescale_hypertable_exists(db_session: AsyncSession) -> None:
    """Guards against a silent migration failure where the extension
    was loaded but create_hypertable never ran — the OHLCV table would
    exist as a plain table and inserts would be slow but not error."""
    result = await db_session.execute(text(
        "SELECT COUNT(*) FROM timescaledb_information.hypertables "
        "WHERE hypertable_name = 'ohlcv'"
    ))
    assert result.scalar() == 1


async def test_truncate_fixture_isolates_tests_a(db_session: AsyncSession) -> None:
    """Paired with test_b below. Writes one row to account_balance; the
    teardown TRUNCATE must wipe it before test_b runs.

    Note: BalanceRepository.current_balance() returns Decimal('10000')
    on an empty ledger (implicit seed — see balance_repo.py:30), so a
    deposit of 1234.56 brings balance_after to 11234.56. We assert on
    row count too to catch truncation failures directly.
    """
    from decimal import Decimal
    from trdex.storage.balance_repo import BalanceRepository

    repo = BalanceRepository(db_session)
    await repo.deposit(Decimal("1234.56"), note="smoke test seed")

    # Row was persisted (deposit commits internally).
    result = await db_session.execute(text("SELECT COUNT(*) FROM account_balance"))
    assert result.scalar() == 1

    # current_balance = implicit 10000 default + 1234.56 deposit.
    balance = await repo.current_balance()
    assert balance == Decimal("11234.56")


async def test_truncate_fixture_isolates_tests_b(db_session: AsyncSession) -> None:
    """Must see zero rows in account_balance — test_a wrote one and the
    TRUNCATE teardown is expected to have wiped it. If this assertion
    fails, the fixture teardown is broken and every other integration
    test is at risk of cross-contamination."""
    from decimal import Decimal
    from trdex.storage.balance_repo import BalanceRepository

    result = await db_session.execute(text("SELECT COUNT(*) FROM account_balance"))
    assert result.scalar() == 0

    # With no rows, current_balance() falls back to the 10000 default.
    repo = BalanceRepository(db_session)
    assert await repo.current_balance() == Decimal("10000")
