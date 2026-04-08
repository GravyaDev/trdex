"""Read-only observability dashboard for a running trdex scheduler.

Gives you a single-shot view of what the agent scheduler has done over a
time window, without opening psql or remembering any SQL. Read-only:
never writes, never creates sessions for modification, safe to run at
any time on a live DB (won't disturb the scheduler).

Sections printed in order, top-down from infra to business:

    1. Scheduler health      - rows in agent_runs, per symbol, last run
    2. Intent distribution   - open_long/close_long/hold counts in the window
    3. Risk gate decisions   - approved vs blocked with reasons
    4. Trades executed       - recent trade fills, broken down by closed_by
    5. Equity curve          - seed / current / peak / drawdown
    6. Open positions        - live positions if any
    7. Readiness snapshot    - evaluate_readiness() verdict
    8. Entity graph          - latest volatility_regime / last_signal facts

Usage::

    uv run python -m trdex.scripts.inspect_runs
    uv run python -m trdex.scripts.inspect_runs --hours 72
    uv run python -m trdex.scripts.inspect_runs --hours 24 --symbols BTC/USDT,ETH/USDT
    uv run python -m trdex.scripts.inspect_runs --all
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("inspect")
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s | %(message)s")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _section(title: str) -> None:
    bar = "=" * max(len(title), 24)
    print(f"\n{bar}\n{title}\n{bar}")


def _redact(url: str) -> str:
    import re

    return re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", url)


def _fmt_ts(dt: datetime | None) -> str:
    if dt is None:
        return "never"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(tz=timezone.utc) - dt
    if delta.total_seconds() < 60:
        return f"{int(delta.total_seconds())}s ago"
    if delta.total_seconds() < 3600:
        return f"{int(delta.total_seconds() / 60)}m ago"
    if delta.total_seconds() < 86400:
        return f"{int(delta.total_seconds() / 3600)}h ago"
    return f"{int(delta.total_seconds() / 86400)}d ago"


def _fmt_pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def _fmt_money(x: float) -> str:
    return f"${x:,.2f}"


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


@dataclass
class InspectArgs:
    hours: int
    symbols: list[str] | None
    show_all: bool


def _since_cutoff(args: InspectArgs) -> datetime | None:
    """Return the lower bound for time-filtered queries, naive UTC."""
    if args.show_all:
        return None
    return (
        datetime.now(tz=timezone.utc).replace(tzinfo=None)
        - timedelta(hours=args.hours)
    )


def _symbol_clause(args: InspectArgs, col: str = "symbol") -> tuple[str, dict]:
    """Build an optional ``AND <col> IN (:s1, :s2, ...)`` clause with params."""
    if not args.symbols:
        return "", {}
    names = {f"s{i}": s for i, s in enumerate(args.symbols)}
    placeholders = ", ".join(f":{k}" for k in names)
    return f" AND {col} IN ({placeholders})", names


async def section_1_scheduler_health(engine, args: InspectArgs) -> None:
    from sqlalchemy import text

    _section("1. Scheduler health")
    since = _since_cutoff(args)
    sym_clause, sym_params = _symbol_clause(args)
    where = "WHERE 1 = 1"
    params: dict[str, object] = {}
    if since is not None:
        where += " AND ran_at >= :since"
        params["since"] = since
    where += sym_clause
    params.update(sym_params)

    async with engine.connect() as conn:
        total = (
            await conn.execute(text(f"SELECT COUNT(*) FROM agent_runs {where}"), params)
        ).scalar_one()
        per_symbol = (
            await conn.execute(
                text(
                    f"SELECT symbol, COUNT(*) AS n, MAX(ran_at) AS last_ran "
                    f"FROM agent_runs {where} "
                    f"GROUP BY symbol ORDER BY symbol"
                ),
                params,
            )
        ).fetchall()
        grand_total = (
            await conn.execute(text("SELECT COUNT(*) FROM agent_runs"))
        ).scalar_one()
        latest = (
            await conn.execute(
                text("SELECT MAX(ran_at) FROM agent_runs")
            )
        ).scalar()

    window_label = "all-time" if args.show_all else f"last {args.hours}h"
    print(f"  window             : {window_label}")
    print(f"  agent_runs (window): {total}")
    print(f"  agent_runs (total) : {grand_total}")
    print(f"  last cycle at      : {_fmt_ts(latest)}")
    if per_symbol:
        print("  per symbol:")
        for sym, n, last_ran in per_symbol:
            print(f"    {sym:<12}  cycles={n:<5}  last={_fmt_ts(last_ran)}")
    else:
        print("  (no cycles in window)")


async def section_2_intent_distribution(engine, args: InspectArgs) -> None:
    """D22: intent distribution. The column is still named ``signal`` in
    the DB (historical, see D11/D24) but stores Intent string values
    since the 2026-04-08 refactor (``open_long``, ``close_long``,
    ``hold``, ``open_short``, ``close_short``)."""
    from sqlalchemy import text

    _section("2. Intent distribution")
    since = _since_cutoff(args)
    sym_clause, sym_params = _symbol_clause(args)
    where = "WHERE 1 = 1"
    params: dict[str, object] = {}
    if since is not None:
        where += " AND ran_at >= :since"
        params["since"] = since
    where += sym_clause
    params.update(sym_params)

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    f"SELECT signal, COUNT(*) AS n FROM agent_runs {where} "
                    f"GROUP BY signal ORDER BY signal"
                ),
                params,
            )
        ).fetchall()

    if not rows:
        print("  (no intents in window)")
        return
    total = sum(r[1] for r in rows)
    for intent, n in rows:
        pct = n / total * 100
        bar = "#" * int(pct / 2)  # each # = 2%
        print(f"  {intent:<12}  {n:<6} {pct:5.1f}%  {bar}")


async def section_3_risk_decisions(engine, args: InspectArgs) -> None:
    from sqlalchemy import text

    _section("3. Risk gate decisions")
    since = _since_cutoff(args)
    sym_clause, sym_params = _symbol_clause(args)
    # Filter out HOLD intents (case-insensitive). Pre-2026-04-08 rows
    # used 'HOLD' uppercase; post-refactor rows use 'hold' lowercase.
    where = "WHERE LOWER(signal) != 'hold'"
    params: dict[str, object] = {}
    if since is not None:
        where += " AND ran_at >= :since"
        params["since"] = since
    where += sym_clause
    params.update(sym_params)

    async with engine.connect() as conn:
        approved = (
            await conn.execute(
                text(
                    f"SELECT COUNT(*) FROM agent_runs {where} AND risk_approved = true"
                ),
                params,
            )
        ).scalar_one()
        blocked = (
            await conn.execute(
                text(
                    f"SELECT COUNT(*) FROM agent_runs {where} AND risk_approved = false"
                ),
                params,
            )
        ).scalar_one()
        top_reasons = (
            await conn.execute(
                text(
                    f"SELECT risk_reason, COUNT(*) AS n FROM agent_runs {where} "
                    f"AND risk_approved = false "
                    f"GROUP BY risk_reason ORDER BY n DESC LIMIT 5"
                ),
                params,
            )
        ).fetchall()

    print(f"  non-HOLD intents  : {approved + blocked}")
    print(f"  approved          : {approved}")
    print(f"  blocked           : {blocked}")
    if top_reasons:
        print("  top block reasons :")
        for reason, n in top_reasons:
            short = (reason or "")[:64]
            print(f"    [{n:>3}] {short}")


def _parse_closed_by(note: str | None) -> str:
    """Extract the ``closed_by=<value>;`` tag from a trade_fill note.

    The PortfolioService writes notes of the form
    ``closed_by=agent_signal; close BUY BTC/USDT position 42 @ ...``.
    Legacy rows from before the 2026-04-08 refactor have no such tag
    and are bucketed as ``"legacy"`` so they remain visible in reports.
    """
    if not note:
        return "legacy"
    # Cheap parse — avoids pulling in re for a 1-tag format.
    prefix = "closed_by="
    if prefix not in note:
        return "legacy"
    start = note.index(prefix) + len(prefix)
    end = note.find(";", start)
    if end == -1:
        end = len(note)
    return note[start:end].strip() or "legacy"


async def section_4_trades(engine, args: InspectArgs) -> None:
    from sqlalchemy import text

    _section("4. Recent trades (account_balance trade_fills)")
    since = _since_cutoff(args)
    where = "WHERE event_type = 'trade_fill'"
    params: dict[str, object] = {}
    if since is not None:
        where += " AND recorded_at >= :since"
        params["since"] = since

    async with engine.connect() as conn:
        agg = (
            await conn.execute(
                text(
                    f"SELECT COUNT(*) AS n, "
                    f"SUM(CASE WHEN amount > 0 THEN 1 ELSE 0 END) AS wins, "
                    f"SUM(CASE WHEN amount < 0 THEN 1 ELSE 0 END) AS losses, "
                    f"SUM(amount) AS pnl_sum, "
                    f"AVG(amount) AS pnl_avg "
                    f"FROM account_balance {where}"
                ),
                params,
            )
        ).first()

        recent = (
            await conn.execute(
                text(
                    f"SELECT recorded_at, amount, balance_after, note "
                    f"FROM account_balance {where} "
                    f"ORDER BY recorded_at DESC LIMIT 10"
                ),
                params,
            )
        ).fetchall()

        # D22: closed_by breakdown across the whole window.
        all_notes = (
            await conn.execute(
                text(
                    f"SELECT note, amount FROM account_balance {where}"
                ),
                params,
            )
        ).fetchall()

    if not agg or agg[0] == 0:
        print("  (no trade fills in window)")
        return

    n, wins, losses, pnl_sum, pnl_avg = agg
    decisive = (wins or 0) + (losses or 0)
    win_rate = ((wins or 0) / decisive) if decisive > 0 else 0.0
    print(f"  trades            : {n}")
    print(f"  wins              : {wins or 0}  ({win_rate * 100:.1f}% of decisive)")
    print(f"  losses            : {losses or 0}")
    print(f"  break-even        : {n - decisive}")
    print(f"  total pnl         : {_fmt_money(float(pnl_sum or 0))}")
    print(f"  avg pnl / trade   : {_fmt_money(float(pnl_avg or 0))}")

    # Per-trigger aggregation (agent_signal / stop_loss / take_profit / trailing_stop / kill_switch / legacy)
    by_trigger: dict[str, tuple[int, float]] = {}
    for note, amount in all_notes:
        trigger = _parse_closed_by(note)
        count, pnl = by_trigger.get(trigger, (0, 0.0))
        by_trigger[trigger] = (count + 1, pnl + float(amount or 0))
    if by_trigger:
        print("  closed_by breakdown:")
        for trigger, (count, pnl) in sorted(by_trigger.items(), key=lambda kv: -kv[1][0]):
            print(f"    {trigger:<14} {count:>4} trades  pnl={_fmt_money(pnl)}")

    print("  last 10 fills:")
    for recorded_at, amount, balance_after, note in recent:
        marker = "+" if float(amount) >= 0 else ""
        trigger = _parse_closed_by(note)
        note_short = (note or "")[:40]
        print(
            f"    {_fmt_ts(recorded_at):<10} "
            f"[{trigger:<13}] "
            f"{marker}{float(amount):>9.4f}  "
            f"balance={float(balance_after):>11.2f}  "
            f"{note_short}"
        )


async def section_5_equity(engine, args: InspectArgs) -> None:
    from sqlalchemy import text

    _section("5. Equity curve")

    async with engine.connect() as conn:
        latest = (
            await conn.execute(
                text(
                    "SELECT balance_after FROM account_balance "
                    "ORDER BY recorded_at DESC, id DESC LIMIT 1"
                )
            )
        ).scalar()
        peak = (
            await conn.execute(
                text("SELECT MAX(balance_after) FROM account_balance")
            )
        ).scalar()
        seed = (
            await conn.execute(
                text(
                    "SELECT balance_after FROM account_balance "
                    "WHERE event_type = 'deposit' "
                    "ORDER BY recorded_at ASC, id ASC LIMIT 1"
                )
            )
        ).scalar()
        first_ts = (
            await conn.execute(
                text(
                    "SELECT MIN(recorded_at) FROM account_balance "
                    "WHERE event_type = 'trade_fill'"
                )
            )
        ).scalar()

    if latest is None:
        print("  (no ledger entries — run smoke_level3 or start the scheduler)")
        return

    latest_f = float(latest)
    peak_f = float(peak) if peak is not None else latest_f
    seed_f = float(seed) if seed is not None else 10_000.0
    pnl_abs = latest_f - seed_f
    pnl_pct = pnl_abs / seed_f if seed_f > 0 else 0.0
    dd_from_peak = (peak_f - latest_f) / peak_f if peak_f > 0 else 0.0

    print(f"  seed deposit      : {_fmt_money(seed_f)}")
    print(f"  current balance   : {_fmt_money(latest_f)}")
    print(f"  peak balance      : {_fmt_money(peak_f)}")
    print(f"  total P&L         : {_fmt_money(pnl_abs)}  ({_fmt_pct(pnl_pct)})")
    print(f"  drawdown vs peak  : {_fmt_pct(dd_from_peak)}")
    print(f"  first trade at    : {_fmt_ts(first_ts)}")


async def section_6_open_positions(engine, args: InspectArgs) -> None:
    from sqlalchemy import text

    _section("6. Open positions")
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT symbol, side, amount, entry_price, opened_at "
                    "FROM positions WHERE status = 'open' "
                    "ORDER BY opened_at DESC"
                )
            )
        ).fetchall()

    if not rows:
        print("  (no open positions)")
        return
    print(f"  {len(rows)} open position(s):")
    for sym, side, amount, entry_price, opened_at in rows:
        print(
            f"    {sym:<12} {side:<5} qty={float(amount):>10.6f} "
            f"entry={float(entry_price):>10.2f}  opened {_fmt_ts(opened_at)}"
        )


async def section_7_readiness(engine, args: InspectArgs) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from trdex.config import get_settings
    from trdex.risk.readiness import evaluate_readiness

    _section("7. Readiness gate snapshot")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            report = await evaluate_readiness(session, get_settings())
    except Exception as exc:
        print(f"  ERROR evaluating readiness: {exc!r}")
        return

    print(f"  sim_days          : {report.sim_days}")
    print(f"  total_trades      : {report.total_trades}")
    print(f"  win_rate          : {report.win_rate * 100:.1f}%")
    sharpe_str = f"{report.sharpe:.2f}" if report.sharpe is not None else "n/a"
    print(f"  sharpe            : {sharpe_str}")
    print(f"  max_drawdown      : {report.max_drawdown_pct * 100:.1f}%")
    verdict = "READY" if report.ready else "NOT READY"
    print(f"  verdict           : {verdict}")
    if report.failures:
        print("  failures:")
        for f in report.failures:
            print(f"    - {f}")


async def section_8_entity_graph(engine, args: InspectArgs) -> None:
    from sqlalchemy import text

    _section("8. Entity graph (active facts)")
    params: dict[str, object] = {}
    where = "WHERE valid_until IS NULL AND subject_type = 'symbol'"
    if args.symbols:
        names = {f"s{i}": s for i, s in enumerate(args.symbols)}
        placeholders = ", ".join(f":{k}" for k in names)
        where += f" AND subject_id IN ({placeholders})"
        params.update(names)

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    f"SELECT subject_id, predicate, object_value, valid_from "
                    f"FROM trdex_entity_graph {where} "
                    f"ORDER BY subject_id, predicate"
                ),
                params,
            )
        ).fetchall()

    if not rows:
        print("  (no active facts for the selected symbols)")
        return

    current_subject = None
    for subject_id, predicate, object_value, valid_from in rows:
        if subject_id != current_subject:
            if current_subject is not None:
                print()
            print(f"  {subject_id}:")
            current_subject = subject_id
        value_str = str(object_value)[:80] if object_value is not None else "null"
        print(f"    {predicate:<20} = {value_str}  ({_fmt_ts(valid_from)})")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="time window for 'recent' queries in hours (default: 24)",
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="comma-separated symbol filter (default: no filter)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="ignore --hours and show all-time data for time-filtered sections",
    )
    parsed = parser.parse_args()

    args = InspectArgs(
        hours=parsed.hours,
        symbols=(
            [s.strip() for s in parsed.symbols.split(",") if s.strip()]
            if parsed.symbols
            else None
        ),
        show_all=parsed.all,
    )

    from sqlalchemy.ext.asyncio import create_async_engine

    from trdex.config import get_settings

    settings = get_settings()
    print()
    print("=" * 64)
    print("trdex inspect_runs — read-only observability dashboard")
    print(f"db: {_redact(settings.database_url)}")
    window = "all-time" if args.show_all else f"last {args.hours}h"
    print(f"window: {window}   symbols: {args.symbols or 'all'}")
    print("=" * 64)

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        await section_1_scheduler_health(engine, args)
        await section_2_intent_distribution(engine, args)
        await section_3_risk_decisions(engine, args)
        await section_4_trades(engine, args)
        await section_5_equity(engine, args)
        await section_6_open_positions(engine, args)
        await section_7_readiness(engine, args)
        await section_8_entity_graph(engine, args)
    finally:
        await engine.dispose()

    print()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
