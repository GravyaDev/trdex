"""Shared test fixtures.

Two fixture families live here:

1. Pure / mock-based fixtures (``sample_candles``, ...) — always loaded,
   used by the 400+ unit tests. No external dependencies.

2. Integration DB fixtures (``test_engine``, ``db_session``, ...) —
   gated by the ``@pytest.mark.integration`` marker. They require a
   live Postgres/TimescaleDB instance, reachable via the URL in
   ``TRDEX_TEST_DATABASE_URL`` (falls back to the docker-compose.test.yaml
   default). If the DB is not reachable, integration tests auto-skip
   with a clear message — they never break the unit suite.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from trdex.market.models import OHLCV


# ── Unit fixtures (always loaded) ──────────────────────────────────────


@pytest.fixture
def sample_candles() -> list[OHLCV]:
    """Generate 50 sample candles with a simple uptrend then downtrend."""
    candles: list[OHLCV] = []
    base_price = 100.0
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    for i in range(50):
        # Uptrend for first 30, downtrend for last 20
        price = base_price + i * 0.5 if i < 30 else base_price + 30 * 0.5 - (i - 30) * 0.8

        candles.append(
            OHLCV(
                timestamp=start + timedelta(hours=i),
                open=Decimal(str(price - 0.2)),
                high=Decimal(str(price + 0.5)),
                low=Decimal(str(price - 0.5)),
                close=Decimal(str(price)),
                volume=Decimal("1000"),
            )
        )
    return candles


# ── Integration DB fixtures (opt-in via -m integration) ────────────────

TEST_DB_URL_DEFAULT = "postgresql+asyncpg://test:test@localhost:5434/trdex_test"


def _test_db_url() -> str:
    return os.environ.get("TRDEX_TEST_DATABASE_URL", TEST_DB_URL_DEFAULT)


async def _db_reachable(url: str) -> bool:
    """Probe the test DB with a 2s timeout. Used to auto-skip integration
    tests when the docker compose stack is not running."""
    engine = create_async_engine(url, pool_pre_ping=False)
    try:
        async with engine.connect() as conn:
            await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=2.0)
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


_migrations_applied = False


@pytest_asyncio.fixture
async def test_engine() -> AsyncEngine:
    """Function-scoped engine against the test DB.

    Why function-scoped (not session-scoped)?
      pytest-asyncio's default event-loop scope is per-function. A
      session-scoped engine would be created in loop A and reused in
      loop B -> "RuntimeError: Event loop is closed" on every test
      after the first. The cleaner fix is to create a fresh engine
      per test; the connect handshake is ~5-10ms against a local
      tmpfs TimescaleDB, negligible next to the test body.

    Migrations are applied only once per test session via the
    ``_migrations_applied`` module-level guard — they are idempotent
    (``CREATE ... IF NOT EXISTS``) but running 18 files per test
    would be real overhead (~400ms/test).

    On first use:
      1. Probes connectivity; if the DB is not up, every test depending
         on this fixture is skipped with a pointer to the compose file.
      2. Applies all SQL migrations once (guarded by the flag).
      3. Yields a fresh engine to the test.
    """
    global _migrations_applied
    url = _test_db_url()
    if not await _db_reachable(url):
        pytest.skip(
            "integration test DB not reachable at "
            f"{url.split('@')[-1]} — start it with "
            "`docker compose -f docker-compose.test.yaml up -d db-test` "
            "or set TRDEX_TEST_DATABASE_URL to point at your own instance",
            allow_module_level=False,
        )

    # Apply migrations only the first time this fixture runs in a
    # session. They are idempotent so re-running would also work, but
    # ~400ms/test adds up over a full integration suite.
    if not _migrations_applied:
        from trdex.scripts.apply_migrations import run_migrations
        from trdex.config import settings as _settings

        prev_url = _settings.database_url
        _settings.database_url = url
        try:
            rc = await run_migrations()
        finally:
            _settings.database_url = prev_url
        if rc != 0:
            pytest.fail("apply_migrations failed against test DB — see logs above")
        _migrations_applied = True

    engine = create_async_engine(url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncSession:
    """Function-scoped session with table-level isolation.

    The production code paths under test (``SignalOutcomeRepository.save``,
    ``BalanceRepository.deposit``, ...) call ``await session.commit()``
    internally. That means the usual "wrap in a transaction, rollback at
    teardown" pattern does not work — the production commit would
    break out of our transaction. Instead, we TRUNCATE every writable
    table after each test. This costs ~5ms per test and guarantees the
    next test starts from a clean slate regardless of what happened in
    the previous one.

    TimescaleDB hypertables (only ``ohlcv`` today) are truncated via
    ``TRUNCATE ... CASCADE`` just like regular tables — Timescale
    overrides ``TRUNCATE`` to drop all chunks.
    """
    factory = async_sessionmaker(
        test_engine, expire_on_commit=False, class_=AsyncSession
    )
    async with factory() as session:
        yield session

    # Cleanup: truncate every application table. We list them explicitly
    # rather than discovering from information_schema so that a new
    # migration that adds a table forces the test author to decide
    # whether it needs truncating (explicit is better than implicit).
    # Authoritative list derived from migrations/*.sql. When adding a
    # new migration that creates a table, append it here explicitly —
    # "explicit is better than implicit" forces the author of the new
    # migration to decide whether the table needs per-test truncation.
    _tables = [
        "account_balance",
        "agent_config",
        "agent_llm_usage",
        "agent_runs",
        "kill_switch_state",
        "ohlcv",
        "positions",
        "runtime_config",
        "signal_outcomes",
        "stop_loss_events",
        "symbol_config",
        "trdex_agent_memory",
        "trdex_entity_graph",
    ]
    async with test_engine.begin() as conn:
        # RESTART IDENTITY resets SERIAL/sequence counters so position.id,
        # signal_outcome.id etc. start at 1 again in the next test.
        # CASCADE handles FK dependencies between the listed tables.
        await conn.execute(text(
            "TRUNCATE " + ", ".join(_tables) + " RESTART IDENTITY CASCADE"
        ))


@pytest_asyncio.fixture
async def session_factory(test_engine: AsyncEngine):
    """An async_sessionmaker bound to the test engine.

    Some production code (telegram_executor wire-up, SL monitor) takes a
    factory rather than a single session because it wants to spawn its
    own short-lived sessions. Tests that exercise those paths use this
    fixture instead of ``db_session``.

    Tables are NOT truncated after a factory-based test — the caller
    is responsible for cleanup, typically by also taking ``db_session``
    so the teardown on that fixture runs.
    """
    return async_sessionmaker(
        test_engine, expire_on_commit=False, class_=AsyncSession
    )
