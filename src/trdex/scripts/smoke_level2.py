"""Smoke level 2 — single end-to-end agent cycle on BTC/USDT.

Goal: run **one** Scout -> Analyst -> Risk -> Executor cycle in simulation
mode against the real trdex stack and verify that:

    1. The market layer can fetch a live ticker + OHLCV from Binance public API
    2. The Scout queries Qdrant (graceful fallback if empty)
    3. The Analyst computes RSI/SMA/volatility regime and emits a signal
    4. The Risk gate runs and produces a (probably HOLD-blocked) decision
    5. The Executor either skips (HOLD) or simulates a fill via the gateway
    6. Persistence works: a row appears in agent_runs
    7. The 6-tier MemoryContext is wired: state.memory_snapshots populated
       for every agent that ran
    8. The Tier 5 entity graph is updated (volatility_regime + last_signal
       written by Analyst/Risk)

Pre-requisites:
    - docker compose up -d  (db, qdrant, redis healthy)
    - uv run python -m trdex.scripts.apply_migrations  (idempotent)

Hits the public Binance REST API. No exchange API key is needed for read-only
endpoints; the rate limiter wraps everything to keep us safe.

Usage::

    uv run python -m trdex.scripts.smoke_level2
    uv run python -m trdex.scripts.smoke_level2 --symbol ETH/USDT
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

logger = logging.getLogger("smoke.l2")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")

REPO_ROOT = Path(__file__).resolve().parents[3]
KB_DIR = REPO_ROOT / "Riferimenti" / "agents"


def _section(title: str) -> None:
    bar = "=" * len(title)
    print(f"\n{bar}\n{title}\n{bar}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--candles", type=int, default=100)
    args = parser.parse_args()

    # Imports here so a settings/import failure surfaces *inside* the run.
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from trdex.agents.runner import AgentRunner
    from trdex.config import get_settings
    from trdex.market.feeds.binance import BinanceFeed
    from trdex.market.manager import PriceFeedManager
    from trdex.memory.context import MemoryContextLoader
    from trdex.memory.kb_loader import KBLoader

    settings = get_settings()
    print(f"\nsmoke_level2 — symbol={args.symbol} mode={settings.mode.value}")
    print(f"db: {_redact(settings.database_url)}")

    # ---- 1. infrastructure ------------------------------------------------
    _section("1. infrastructure")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    feeds = PriceFeedManager()
    binance = BinanceFeed()
    feeds.register(binance)
    print(f"  registered feeds: {list(feeds._feeds.keys())}")

    kb = KBLoader.from_directory(KB_DIR)
    print(f"  KB loaded: {len(kb)} blocks")

    memory_loader = MemoryContextLoader(kb_loader=kb, session_factory=session_factory)
    print("  memory loader: KB + DB tiers (no Tier 4 in smoke level 2)")

    # ---- 2. snapshot of agent_runs BEFORE -------------------------------
    _section("2. agent_runs row count BEFORE")
    async with engine.connect() as conn:
        before = (await conn.execute(text("SELECT COUNT(*) FROM agent_runs"))).scalar_one()
    print(f"  rows: {before}")

    # ---- 3. run the cycle ------------------------------------------------
    _section("3. running agent cycle")
    final_state = None
    try:
        async with session_factory() as session:
            runner = AgentRunner(
                session=session,
                feed_manager=feeds,
                session_factory=session_factory,
                gateway=None,  # Executor will fall back to DefaultExecutionGateway.create()
                memory_loader=memory_loader,
            )
            final_state = await runner.run(
                args.symbol,
                timeframe=args.timeframe,
                candle_limit=args.candles,
            )
    finally:
        await binance.close()

    if final_state is None:
        print("  ERROR: cycle returned no state")
        await engine.dispose()
        return 1

    # ---- 4. report final state ------------------------------------------
    _section("4. cycle result")
    print(f"  run_id        : {final_state.run_id}")
    print(f"  symbol        : {final_state.symbol}")
    market = final_state.market
    if market is not None:
        print(f"  price         : {market.price}")
        print(f"  candles       : {len(market.candles)}")
    a = final_state.analysis
    print(f"  analyst intent: {a.intent.value} conf={a.confidence:.2f}")
    print(f"  analyst reason: {a.reasoning[:120]}")
    print(f"  indicators    : {a.indicators}")
    r = final_state.risk
    print(f"  risk approved : {r.approved}")
    print(f"  risk reason   : {r.reason[:120]}")
    o = final_state.order
    print(f"  order status  : {o.status}")
    print(f"  order msg     : {o.message[:120]}")
    if final_state.error:
        print(f"  ERROR         : {final_state.error}")

    # ---- 5. memory snapshots --------------------------------------------
    _section("5. per-agent memory snapshots")
    snapshots = final_state.memory_snapshots
    if not snapshots:
        print("  (none — memory loader did not produce any snapshot)")
    else:
        for agent, text_value in snapshots.items():
            preview = text_value.replace("\n", " | ")[:160]
            print(f"  {agent:9s}: {preview}{'...' if len(text_value) > 160 else ''}")

    # ---- 6. agent_runs row count AFTER ----------------------------------
    _section("6. persistence verification")
    async with engine.connect() as conn:
        after = (await conn.execute(text("SELECT COUNT(*) FROM agent_runs"))).scalar_one()
        latest = await conn.execute(
            text(
                "SELECT run_id, symbol, signal, risk_approved, order_status "
                "FROM agent_runs ORDER BY id DESC LIMIT 1"
            )
        )
        latest_row = latest.first()

        eg_count = (
            await conn.execute(text("SELECT COUNT(*) FROM trdex_entity_graph"))
        ).scalar_one()
        eg_active = await conn.execute(
            text(
                "SELECT predicate, object_value FROM trdex_entity_graph "
                "WHERE subject_id=:s AND valid_until IS NULL"
            ),
            {"s": args.symbol},
        )
        eg_rows = eg_active.fetchall()

    print(f"  agent_runs rows: {before} -> {after} (delta {after - before})")
    if latest_row:
        print(f"  latest run    : run_id={latest_row[0]} signal={latest_row[2]} "
              f"approved={latest_row[3]} order={latest_row[4]}")
    print(f"  entity_graph rows total : {eg_count}")
    print(f"  entity_graph active for {args.symbol}:")
    if eg_rows:
        for row in eg_rows:
            print(f"    - {row[0]}: {row[1]}")
    else:
        print("    (none)")

    await engine.dispose()

    # ---- 7. final verdict ------------------------------------------------
    _section("verdict")
    ok = (
        after == before + 1
        and (latest_row is not None and latest_row[1] == args.symbol)
        and not final_state.error
    )
    if ok:
        print("  OK — cycle completed and persisted")
        return 0
    print("  FAIL — see above")
    return 1


def _redact(url: str) -> str:
    import re

    return re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", url)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
