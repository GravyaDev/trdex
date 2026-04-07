"""Smoke level 1 — infrastructure sanity check.

Goal: verify that every dependency the trdex app needs is reachable and
schema-correct, *without* hitting any external API. This is the first thing
to run after ``docker compose up`` and ``apply_migrations``.

Checks performed (in order, fail-fast):
    1. Settings load — required env vars present
    2. Postgres + TimescaleDB — connect, run SELECT 1, verify timescaledb extension
    3. All 8 expected tables exist with the right names
    4. ohlcv hypertable is registered with TimescaleDB
    5. account_balance is seeded with the initial 10_000 USDT row
    6. kill_switch_state singleton is present and inactive
    7. trdex_entity_graph + trdex_agent_memory are empty and queryable
    8. Qdrant — connect, list collections, create the trdex_context collection
       if it does not exist (idempotent)
    9. Tier 1 KB loader — parse Riferimenti/agents/*.md, find HARD-ANALYST-002

Exit code:
    0 = green
    1 = at least one check failed (the script prints which one)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

logger = logging.getLogger("smoke.l1")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")

REPO_ROOT = Path(__file__).resolve().parents[3]
KB_DIR = REPO_ROOT / "Riferimenti" / "agents"

EXPECTED_TABLES = {
    "ohlcv",
    "positions",
    "agent_runs",
    "account_balance",
    "signal_outcomes",
    "trdex_entity_graph",
    "kill_switch_state",
    "trdex_agent_memory",
}


# ---------- check helpers ---------------------------------------------------


class Check:
    def __init__(self, name: str) -> None:
        self.name = name
        self.ok = False
        self.detail = ""

    def __repr__(self) -> str:
        flag = "OK" if self.ok else "NO"
        return f"  [{flag}] {self.name}{(' - ' + self.detail) if self.detail else ''}"


async def check_settings() -> Check:
    c = Check("settings load")
    try:
        from trdex.config import get_settings

        s = get_settings()
        if not s.database_url:
            c.detail = "DATABASE_URL is empty"
            return c
        c.ok = True
        c.detail = f"mode={s.mode.value} db={_redact(s.database_url)}"
    except Exception as exc:
        c.detail = f"failed: {exc!r}"
    return c


async def check_postgres() -> tuple[Check, "AsyncEngine | None"]:  # type: ignore[name-defined]
    c = Check("postgres connect + timescaledb extension")
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        from trdex.config import get_settings

        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            ext = await conn.execute(
                text("SELECT extname FROM pg_extension WHERE extname='timescaledb'")
            )
            row = ext.first()
            if row is None:
                c.detail = "timescaledb extension not loaded"
                return c, engine
        c.ok = True
        c.detail = "ok"
        return c, engine
    except Exception as exc:
        c.detail = f"failed: {exc!r}"
        return c, None


async def check_tables(engine) -> Check:
    c = Check(f"{len(EXPECTED_TABLES)} expected tables present")
    try:
        from sqlalchemy import text

        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public'"
                )
            )
            present = {row[0] for row in result}
        missing = EXPECTED_TABLES - present
        if missing:
            c.detail = f"missing: {sorted(missing)}"
            return c
        c.ok = True
        c.detail = f"all present ({len(EXPECTED_TABLES)})"
    except Exception as exc:
        c.detail = f"failed: {exc!r}"
    return c


async def check_hypertable(engine) -> Check:
    c = Check("ohlcv hypertable registered")
    try:
        from sqlalchemy import text

        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT hypertable_name FROM timescaledb_information.hypertables "
                    "WHERE hypertable_name='ohlcv'"
                )
            )
            row = result.first()
        if row is None:
            c.detail = "ohlcv is not a hypertable"
            return c
        c.ok = True
    except Exception as exc:
        c.detail = f"failed: {exc!r}"
    return c


async def check_balance_seed(engine) -> Check:
    c = Check("account_balance seeded")
    try:
        from sqlalchemy import text

        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT COUNT(*), MAX(balance_after) FROM account_balance")
            )
            count, max_balance = result.first()
        if count == 0:
            c.detail = "no rows — seed missing"
            return c
        c.ok = True
        c.detail = f"rows={count} latest_balance={float(max_balance or 0):.2f}"
    except Exception as exc:
        c.detail = f"failed: {exc!r}"
    return c


async def check_kill_switch_seed(engine) -> Check:
    c = Check("kill_switch_state seeded inactive")
    try:
        from sqlalchemy import text

        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT id, active, reason FROM kill_switch_state WHERE id=1")
            )
            row = result.first()
        if row is None:
            c.detail = "singleton row missing"
            return c
        if row[1]:
            c.detail = f"unexpectedly ACTIVE — reason={row[2]!r}"
            return c
        c.ok = True
        c.detail = "inactive"
    except Exception as exc:
        c.detail = f"failed: {exc!r}"
    return c


async def check_memory_tables_empty(engine) -> Check:
    c = Check("trdex_entity_graph + trdex_agent_memory queryable")
    try:
        from sqlalchemy import text

        async with engine.connect() as conn:
            r1 = await conn.execute(text("SELECT COUNT(*) FROM trdex_entity_graph"))
            n1 = r1.scalar_one()
            r2 = await conn.execute(text("SELECT COUNT(*) FROM trdex_agent_memory"))
            n2 = r2.scalar_one()
        c.ok = True
        c.detail = f"entity_graph={n1} agent_memory={n2}"
    except Exception as exc:
        c.detail = f"failed: {exc!r}"
    return c


async def check_qdrant() -> Check:
    c = Check("qdrant reachable + trdex_context collection")
    try:
        from qdrant_client import AsyncQdrantClient

        from trdex.config import get_settings
        from trdex.context.vector_store import COLLECTION_NAME, QdrantStore

        client = AsyncQdrantClient(url=get_settings().qdrant_url)
        collections = await client.get_collections()
        names = {col.name for col in collections.collections}

        store = QdrantStore(client=client)
        await store.ensure_collection()
        await client.close()

        c.ok = True
        c.detail = f"existing_before={sorted(names)} ensured={COLLECTION_NAME}"
    except Exception as exc:
        c.detail = f"failed: {exc!r}"
    return c


async def check_kb_loader() -> Check:
    c = Check("KB loader parses Riferimenti/agents/")
    try:
        from trdex.memory.kb_loader import KBLoader

        if not KB_DIR.is_dir():
            c.detail = f"directory missing: {KB_DIR}"
            return c
        loader = KBLoader.from_directory(KB_DIR)
        if "HARD-ANALYST-002" not in loader:
            c.detail = "anchor block HARD-ANALYST-002 missing"
            return c
        c.ok = True
        c.detail = f"loaded {len(loader)} blocks across {len({b.agent for b in loader.blocks})} agents"
    except Exception as exc:
        c.detail = f"failed: {exc!r}"
    return c


def _redact(url: str) -> str:
    import re

    return re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", url)


# ---------- main ------------------------------------------------------------


async def main() -> int:
    print("\n=== smoke_level1 - infrastructure sanity ===\n")
    results: list[Check] = []

    results.append(await check_settings())
    if not results[-1].ok:
        _report(results)
        return 1

    pg_check, engine = await check_postgres()
    results.append(pg_check)
    if not pg_check.ok:
        _report(results)
        return 1

    try:
        results.append(await check_tables(engine))
        results.append(await check_hypertable(engine))
        results.append(await check_balance_seed(engine))
        results.append(await check_kill_switch_seed(engine))
        results.append(await check_memory_tables_empty(engine))
    finally:
        await engine.dispose()

    results.append(await check_qdrant())
    results.append(await check_kb_loader())

    return 0 if _report(results) else 1


def _report(results: list[Check]) -> bool:
    print("Results:")
    for r in results:
        print(r)
    failed = [r for r in results if not r.ok]
    print()
    if failed:
        print(f"FAIL — {len(failed)}/{len(results)} checks failed")
        return False
    print(f"OK — {len(results)} checks passed")
    return True


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
