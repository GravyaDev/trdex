"""Apply every SQL file in ``migrations/`` against the configured database.

Usage::

    uv run python -m trdex.scripts.apply_migrations
    uv run python -m trdex.scripts.apply_migrations --dry-run
    uv run python -m trdex.scripts.apply_migrations --only 008

Behaviour:
- Files are discovered by ``migrations/*.sql`` and applied in lexical order
  (which matches the numeric prefix 001, 002, ..., 008).
- Each file is executed inside its own transaction. The migrations are
  authored to be **idempotent** (``CREATE EXTENSION IF NOT EXISTS``,
  ``CREATE TABLE IF NOT EXISTS``, ``CREATE INDEX IF NOT EXISTS``, etc.) so
  re-running this script after success is a no-op.
- ``--dry-run`` prints the plan without executing anything.
- ``--only N`` applies just the migration whose filename starts with ``N``
  (zero-padded match against the prefix). Useful when you add a new file.
- Connection comes from ``Settings.database_url`` (the same the app uses).
- The TimescaleDB-specific statements in 001 (``create_hypertable``,
  ``add_compression_policy``) are executed via raw asyncpg, not SQLAlchemy
  ORM, so the extension is loaded fresh from the file path each time.

Exit code 0 on success, 1 on any failure.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from trdex.config import get_settings

logger = logging.getLogger("trdex.migrations")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"

# Statements that cannot run inside an explicit transaction (Postgres rule).
# Right now we don't have any but the splitter is here in case we add some.
_TX_INCOMPATIBLE_PREFIXES: tuple[str, ...] = ()


def _discover_migrations(only: str | None) -> list[Path]:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        logger.error("no migration files found in %s", MIGRATIONS_DIR)
        return []
    if only:
        prefix = only.zfill(3)
        files = [f for f in files if f.name.startswith(prefix)]
        if not files:
            logger.error("no migration matches prefix %s", prefix)
    return files


def _split_statements(sql: str) -> list[str]:
    """Split SQL on top-level semicolons.

    Honours:
    - line comments ``-- ... \\n`` (passed through verbatim, not parsed)
    - block comments ``/* ... */`` (passed through verbatim, not parsed)
    - single-quoted strings ``'...'``
    - double-quoted identifiers ``"..."``
    - dollar-quoted strings ``$$...$$`` and ``$tag$...$tag$`` (PL/pgSQL bodies)

    The need to recognise comments comes from real-world migration files that
    contain apostrophes inside English prose (``isn't``, ``can't``...): without
    comment skipping, those would flip the parser into single-quote mode and
    eat the rest of the file.
    """
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(sql)
    in_single = False  # inside '...'
    in_double = False  # inside "..."
    dollar_tag: str | None = None  # current dollar-quote tag

    while i < n:
        ch = sql[i]

        # Dollar-quoted bodies have highest priority.
        if dollar_tag is not None:
            close = f"${dollar_tag}$"
            if sql.startswith(close, i):
                buf.append(close)
                i += len(close)
                dollar_tag = None
                continue
            buf.append(ch)
            i += 1
            continue

        # Inside a quoted string we only look for the matching close.
        if in_single:
            buf.append(ch)
            i += 1
            if ch == "'" and (i >= n or sql[i] != "'"):
                in_single = False
            elif ch == "'" and i < n and sql[i] == "'":
                # Escaped apostrophe '' inside a string literal — emit both.
                buf.append(sql[i])
                i += 1
            continue

        if in_double:
            buf.append(ch)
            i += 1
            if ch == '"':
                in_double = False
            continue

        # Line comment: pass through to next newline (or EOF).
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            end = sql.find("\n", i)
            if end == -1:
                end = n
            buf.append(sql[i:end])
            i = end
            continue

        # Block comment: pass through to closing */.
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            if end == -1:
                end = n
            else:
                end += 2
            buf.append(sql[i:end])
            i = end
            continue

        # Dollar-quote opener: $tag$ or $$ (tag may be empty or [A-Za-z_][A-Za-z0-9_]*).
        if ch == "$":
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < n and sql[j] == "$":
                tag = sql[i + 1 : j]
                dollar_tag = tag
                buf.append(sql[i : j + 1])
                i = j + 1
                continue

        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
            continue

        if ch == '"':
            in_double = True
            buf.append(ch)
            i += 1
            continue

        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


async def _apply_file(engine, path: Path, dry_run: bool) -> None:
    sql = path.read_text(encoding="utf-8")
    statements = _split_statements(sql)
    logger.info("apply %s (%d statements)", path.name, len(statements))

    if dry_run:
        for i, stmt in enumerate(statements, 1):
            preview = " ".join(stmt.splitlines())[:120]
            logger.info("  [%02d] %s%s", i, preview, "..." if len(stmt) > 120 else "")
        return

    async with engine.begin() as conn:
        for i, stmt in enumerate(statements, 1):
            try:
                await conn.execute(text(stmt))
            except Exception:
                logger.exception("statement %d failed in %s:\n%s", i, path.name, stmt)
                raise


async def run_migrations(only: str | None = None, dry_run: bool = False) -> int:
    """Apply all migrations (or the one selected by ``only``).

    Callable from non-CLI contexts (e.g. the FastAPI lifespan on app
    startup) so that a fresh deploy against an empty database self-heals
    without an out-of-band init step. Returns 0 on success, 1 on failure.
    """
    files = _discover_migrations(only)
    if not files:
        return 1

    settings = get_settings()
    logger.info("target database: %s", _redact_url(settings.database_url))
    logger.info("migrations dir : %s", MIGRATIONS_DIR)
    logger.info("plan           : %s", ", ".join(f.name for f in files))

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        for path in files:
            await _apply_file(engine, path, dry_run)
    except Exception:
        logger.error("migration run aborted")
        return 1
    finally:
        await engine.dispose()

    logger.info("OK — %d migration file(s) processed", len(files))
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print plan only")
    parser.add_argument("--only", type=str, default=None, help="apply only this prefix (e.g. 008)")
    args = parser.parse_args()

    return await run_migrations(only=args.only, dry_run=args.dry_run)


def _redact_url(url: str) -> str:
    """Hide the password in a database URL for safe logging."""
    return re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", url)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
