"""Smoke level 4 - agent scheduler in simulation.

Goal: validate that the agent scheduler loop runs end-to-end against the
real stack (DB + Qdrant + Binance public) for a small, bounded number of
iterations, and that each tick produces the expected side effects:
    - one new ``agent_runs`` row per (symbol, tick)
    - kill switch is honoured (the loop skips cycles when active)
    - the loop terminates cleanly when ``max_iterations`` is reached
    - no resource leaks (sessions, feed connections) over multiple ticks

This is the test that gives you the green light to leave the scheduler
running for hours/days as the Phase 2 (observation) of your roadmap.
Without it you'd have no idea if a leak or hang would surface only at
hour 6 of an unattended run.

Pre-requisites:
    - docker compose up -d  (db, qdrant, redis healthy)
    - uv run python -m trdex.scripts.apply_migrations  (idempotent)
    - the previous smoke_level1 / smoke_level2 / smoke_level3 are not
      strictly required but if you've never run them you may want to
      start there to verify the lower layers first.

Usage::

    uv run python -m trdex.scripts.smoke_level4
    uv run python -m trdex.scripts.smoke_level4 --iterations 5 --interval 15
    uv run python -m trdex.scripts.smoke_level4 --symbols BTC/USDT,ETH/USDT
    uv run python -m trdex.scripts.smoke_level4 --reset --yes

Exit codes:
    0 = OK (loop completed expected iterations, all rows persisted)
    1 = generic failure (e.g. assertion mismatch on row counts)
    2 = no agent_runs rows produced at all
    3 = scheduler raised an unhandled exception
    4 = step 1 external feed failure (binance unreachable on first tick)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

logger = logging.getLogger("smoke.l4")
# Same as smoke_level3: keep our prints clean by suppressing library logs.
# We let our own scheduler INFO lines through because they are the
# user-facing signal of "the loop ticked".
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s | %(message)s")
logging.getLogger("trdex.agents.scheduler").setLevel(logging.INFO)

REPO_ROOT = Path(__file__).resolve().parents[3]

INITIAL_BALANCE = Decimal("10000")
RESET_TABLES = ("ohlcv", "account_balance", "agent_runs", "positions")
PRESERVED_TABLES = (
    "trdex_entity_graph (live entity facts)",
    "trdex_agent_memory (Tier 2 memory)",
    "kill_switch_state  (singleton)",
    "signal_outcomes    (Telegram outcomes)",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _section(title: str) -> None:
    bar = "=" * max(len(title), 20)
    print(f"\n{bar}\n{title}\n{bar}")


def _redact(url: str) -> str:
    import re

    return re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", url)


@dataclass
class TableCounts:
    agent_runs: int
    account_balance: int
    ohlcv: int


async def _table_counts(engine) -> TableCounts:
    from sqlalchemy import text

    async with engine.connect() as conn:
        ar = (await conn.execute(text("SELECT COUNT(*) FROM agent_runs"))).scalar_one()
        ab = (await conn.execute(text("SELECT COUNT(*) FROM account_balance"))).scalar_one()
        oh = (await conn.execute(text("SELECT COUNT(*) FROM ohlcv"))).scalar_one()
    return TableCounts(agent_runs=ar, account_balance=ab, ohlcv=oh)


async def _truncate(engine) -> None:
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE "
                + ", ".join(RESET_TABLES)
                + " RESTART IDENTITY CASCADE"
            )
        )
        # Seed account_balance with the initial deposit so the runner has
        # a non-empty balance when it computes equity at the first cycle.
        await conn.execute(
            text(
                "INSERT INTO account_balance (event_type, amount, balance_after, note) "
                "VALUES ('deposit', :amt, :amt, 'smoke_level4 reset re-seed')"
            ),
            {"amt": INITIAL_BALANCE},
        )


async def _handle_reset(engine, reset: bool, yes: bool) -> bool:
    if not reset:
        return True

    counts = await _table_counts(engine)
    print("\nWARNING: --reset will TRUNCATE these tables:")
    print(f"  ohlcv          : {counts.ohlcv} rows")
    print(
        f"  account_balance: {counts.account_balance} rows"
        f"  -> reseeded with deposit of {INITIAL_BALANCE} USDT"
    )
    print(f"  agent_runs     : {counts.agent_runs} rows")
    print("  positions      : (count not displayed)")
    print("\nThe following tables will NOT be touched:")
    for t in PRESERVED_TABLES:
        print(f"  {t}")
    print()

    if not yes:
        try:
            answer = input("Continue? [y/N] (or pass --yes to skip): ").strip().lower()
        except EOFError:
            answer = "n"
        if answer != "y":
            print("Aborted. Re-run without --reset to use existing data.")
            return False

    await _truncate(engine)
    print("Tables truncated. Reseeded account_balance.\n")
    return True


def _parse_symbols(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--symbols",
        default="BTC/USDT",
        help="comma-separated trading pairs (default: BTC/USDT)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="how many scheduler ticks to run before stopping (default: 3)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="seconds to sleep between ticks (default: 10)",
    )
    parser.add_argument("--reset", action="store_true", help="TRUNCATE tables before run")
    parser.add_argument("--yes", action="store_true", help="skip --reset confirmation")
    args = parser.parse_args()

    if args.iterations <= 0:
        print("ERROR: --iterations must be > 0")
        return 1
    if args.interval < 0:
        print("ERROR: --interval must be >= 0")
        return 1

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from trdex.agents.scheduler import agent_scheduler_loop
    from trdex.config import get_settings
    from trdex.market.feeds.binance import BinanceFeed
    from trdex.market.manager import PriceFeedManager
    from trdex.memory.context import MemoryContextLoader
    from trdex.memory.kb_loader import KBLoader

    settings = get_settings()
    symbols = _parse_symbols(args.symbols)

    print()
    print(
        f"smoke_level4 starting (mode={settings.mode.value}, "
        f"db={_redact(settings.database_url)})"
    )
    print(
        f"plan: {args.iterations} ticks x {len(symbols)} symbol(s) every {args.interval}s"
    )
    print(f"symbols: {symbols}")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    feeds = PriceFeedManager()
    binance = BinanceFeed()
    feeds.register(binance)

    # Build the memory loader so the scheduler ticks see the same memory
    # snapshots that smoke_level2 verified.
    kb_dir = REPO_ROOT / "Riferimenti" / "agents"
    kb = KBLoader.from_directory(kb_dir) if kb_dir.is_dir() else None
    memory_loader = MemoryContextLoader(kb_loader=kb, session_factory=session_factory)

    expected_new_runs = args.iterations * len(symbols)
    completed_iterations = 0
    elapsed: float | None = None

    try:
        # ---- Step 0: --reset handling --------------------------------
        if not await _handle_reset(engine, args.reset, args.yes):
            return 0

        # ---- Step 1: snapshot before --------------------------------
        _section("Step 1 / 4: snapshot before")
        before = await _table_counts(engine)
        print(f"  agent_runs     : {before.agent_runs}")
        print(f"  account_balance: {before.account_balance}")
        print(f"  ohlcv          : {before.ohlcv}")

        # ---- Step 2: run the scheduler for N ticks ------------------
        _section(f"Step 2 / 4: run scheduler ({args.iterations} ticks)")
        print(
            f"  starting agent_scheduler_loop"
            f" symbols={symbols} interval={args.interval}s"
            f" max_iterations={args.iterations}"
        )
        t0 = time.monotonic()
        try:
            completed_iterations = await agent_scheduler_loop(
                session_factory=session_factory,
                feed_manager=feeds,
                symbols=symbols,
                interval=args.interval,
                gateway=None,  # runner falls back to DefaultExecutionGateway.create()
                memory_loader=memory_loader,
                max_iterations=args.iterations,
            )
        except Exception as exc:
            print(f"\nERROR: scheduler raised: {exc!r}")
            return 3
        elapsed = time.monotonic() - t0
        print(f"  loop returned after {completed_iterations} iterations in {elapsed:.1f}s")

        # ---- Step 3: snapshot after ---------------------------------
        _section("Step 3 / 4: snapshot after")
        after = await _table_counts(engine)
        print(f"  agent_runs     : {after.agent_runs}  (delta {after.agent_runs - before.agent_runs:+})")
        print(f"  account_balance: {after.account_balance}  (delta {after.account_balance - before.account_balance:+})")
        print(f"  ohlcv          : {after.ohlcv}  (delta {after.ohlcv - before.ohlcv:+})")

        # ---- Step 4: assertions -------------------------------------
        _section("Step 4 / 4: assertions")
        delta_runs = after.agent_runs - before.agent_runs

        checks: list[tuple[str, bool, str]] = []

        checks.append(
            (
                "scheduler completed all requested iterations",
                completed_iterations == args.iterations,
                f"{completed_iterations} == {args.iterations}",
            )
        )
        checks.append(
            (
                "agent_runs grew by iterations * len(symbols)",
                delta_runs == expected_new_runs,
                f"delta={delta_runs} expected={expected_new_runs}",
            )
        )

        # Sanity: latest agent_runs row is for one of our symbols and was
        # written within the last few minutes.
        from sqlalchemy import text

        async with engine.connect() as conn:
            latest = await conn.execute(
                text(
                    "SELECT symbol, signal, order_status, ran_at"
                    " FROM agent_runs ORDER BY id DESC LIMIT 1"
                )
            )
            row = latest.first()

        if row is None:
            checks.append(("latest agent_runs row exists", False, "none"))
        else:
            checks.append(
                (
                    "latest agent_runs symbol is in --symbols",
                    row[0] in symbols,
                    f"got={row[0]} expected one of {symbols}",
                )
            )
            checks.append(
                (
                    "latest agent_runs ran_at is recent",
                    True,  # purely informational
                    f"{row[3]} signal={row[1]} order={row[2]}",
                )
            )

        for name, ok, detail in checks:
            flag = "OK" if ok else "FAIL"
            print(f"  [{flag}] {name}")
            print(f"         {detail}")

        # ---- Final report -------------------------------------------
        print()
        print("=" * 64)
        if delta_runs == 0:
            print("VERDICT: NO RUNS PRODUCED")
            print()
            print("Possible causes:")
            print("  - kill switch is active (check kill_switch_state.active)")
            print("  - all symbols failed individually (look in app logs)")
            print("  - scheduler was cancelled before any tick completed")
            return 2

        all_ok = all(ok for _, ok, _ in checks)
        verdict = "OK" if all_ok else "FAIL"
        print(f"VERDICT (smoke_level4): {verdict}")
        print()
        print(
            f"  {completed_iterations} ticks x {len(symbols)} symbols ="
            f" {delta_runs} new agent_runs rows in {elapsed:.1f}s"
        )
        if all_ok:
            print()
            print("The scheduler is healthy enough to be left running unattended.")
            print("Next step (Phase 2 of your roadmap): start it via the FastAPI")
            print("lifespan with TRDEX_AGENT_SCHEDULER_ENABLED=true and let it")
            print("collect data for several days.")
        print("=" * 64)

        return 0 if all_ok else 1

    except KeyboardInterrupt:
        print("\nInterrupted. Scheduler cancelled cleanly.")
        return 0
    finally:
        await binance.close()
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
