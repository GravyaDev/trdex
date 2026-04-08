"""Smoke level 3 - backtest end-to-end on BTC/USDT.

Goal: validate the full *trading + valuation* loop. Fetches 90 days of
hourly OHLCV from Binance public API, persists them in TimescaleDB, runs
the BacktestSMACross strategy through the polars-vectorised backtest
engine, replays each closed trade into the account_balance ledger AND
into agent_runs (so the readiness gate sees them), evaluates the
readiness gate, and runs three coherence checks across the three data
sources.

This script is the first thing that exercises:
    - the OHLCV write path (TimescaleDB hypertable + unique constraint)
    - the backtest engine end-to-end with real data
    - the BacktestSMACross strategy on a non-synthetic dataset
    - the BalanceRepository historic ledger writes
    - the readiness gate against a populated DB
    - the coherence between backtest, ledger, and agent_runs

It deliberately uses a long-only SMA(9,21) crossover strategy with no
stop-loss / take-profit (the engine does not support intra-bar exits).
The expected outcome on a first run is NOT READY when judged on the true
backtest metrics: SMA cross naked is mediocre by design. The point is to
get a baseline number, not to find alpha.

Usage::

    uv run python -m trdex.scripts.smoke_level3
    uv run python -m trdex.scripts.smoke_level3 --days 90
    uv run python -m trdex.scripts.smoke_level3 --reset
    uv run python -m trdex.scripts.smoke_level3 --reset --yes  # CI safe

Pre-requisites:
    - docker compose up -d (db, qdrant, redis)
    - uv run python -m trdex.scripts.apply_migrations (idempotent)

Exit codes:
    0 = OK (overall verdict, READY or NOT-READY: no error)
    1 = generic failure
    2 = 0 trades from backtest (cannot validate pipeline)
    3 = step 3 db replay error
    4 = step 1 external feed failure (binance unreachable)

Recently fixed (do not re-introduce):
    - readiness.win_rate now reads PnL from account_balance.amount
      (was approving every filled run as a win). See risk/readiness.py.
    - readiness.sharpe is now computed from the EoD ledger equity curve
      and annualised with sqrt(252). See risk/readiness.py.
    - backtest.sharpe is now annualised with the correct bars-per-year
      factor for the timeframe (8760 for 1h, 365 for 1d, ...).
      See backtest/engine.py.

Modifies (in separate commits, not by this file directly):
    - src/trdex/backtest/engine.py: adds entry_idx/exit_idx to trades
      and timeframe-aware sharpe annualisation
    - src/trdex/market/feeds/binance.py: adds since param to get_ohlcv
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

logger = logging.getLogger("smoke.l3")
# D24: suppress noisy library logging during the smoke run; only show
# WARNING+. Our own print() statements stay visible.
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s | %(message)s")

REPO_ROOT = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Tables that --reset will TRUNCATE (D9, D22).
RESET_TABLES = ("ohlcv", "account_balance", "agent_runs", "positions")
# Tables that --reset will PRESERVE - listed for the user prompt (D22).
PRESERVED_TABLES = (
    "trdex_entity_graph (live entity facts)",
    "trdex_agent_memory (Tier 2 memory)",
    "kill_switch_state  (singleton)",
    "signal_outcomes    (Telegram outcomes)",
)
INITIAL_BALANCE = Decimal("10000")
# Constant marker stored in agent_runs.risk_reason to identify backtest
# replay rows. We use a *text* column (not run_id, which is UUID-typed and
# rejects LIKE/prefix matches) so D17 / D21 idempotency checks can run as
# plain equality queries.
BACKTEST_REPLAY_MARKER = "backtest replay"
MAX_FETCH_ITERATIONS = 5  # D20 - guard against infinite Binance pagination


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class TableCounts:
    ohlcv: int
    account_balance: int
    agent_runs: int
    positions: int


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------


def _section(title: str) -> None:
    bar = "=" * max(len(title), 20)
    print(f"\n{bar}\n{title}\n{bar}")


def _redact(url: str) -> str:
    import re

    return re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", url)


def _ms(dt: datetime) -> int:
    """Convert a UTC datetime to a millisecond epoch."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


# ---------------------------------------------------------------------------
# Step 0: --reset confirmation + truncate
# ---------------------------------------------------------------------------


async def _table_counts(engine) -> TableCounts:
    from sqlalchemy import text

    async with engine.connect() as conn:
        results = {}
        for tbl in RESET_TABLES:
            n = (await conn.execute(text(f"SELECT COUNT(*) FROM {tbl}"))).scalar_one()
            results[tbl] = n
    return TableCounts(**results)


async def _truncate(engine) -> None:
    """TRUNCATE the four reset-tables.

    Note: we deliberately do NOT re-seed account_balance here. The seed
    deposit row is inserted as the *first* event of the backtest replay
    (Step 3), with a ``recorded_at`` strictly before the first trade
    fill, so that the chronological order of the ledger matches reality
    and ``current_balance()`` returns the post-replay value rather than
    a present-day re-seed event.
    """
    from sqlalchemy import text

    async with engine.begin() as conn:
        # Postgres: TRUNCATE ... RESTART IDENTITY resets BIGSERIAL counters too.
        await conn.execute(
            text(
                "TRUNCATE TABLE "
                + ", ".join(RESET_TABLES)
                + " RESTART IDENTITY CASCADE"
            )
        )


async def step0_handle_reset(engine, reset: bool, yes: bool) -> bool:
    """Handle --reset flag. Returns True if the script should continue."""
    if not reset:
        return True

    counts = await _table_counts(engine)
    print("\nWARNING: --reset will TRUNCATE these tables:")
    print(f"  ohlcv          : {counts.ohlcv} rows")
    print(
        f"  account_balance: {counts.account_balance} rows"
        f"  -> Step 3 will then write a fresh seed deposit of {INITIAL_BALANCE} USDT"
        " dated before the first trade"
    )
    print(f"  agent_runs     : {counts.agent_runs} rows")
    print(f"  positions      : {counts.positions} rows")
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
    print("Tables truncated. account_balance will be seeded by Step 3.\n")
    return True


# ---------------------------------------------------------------------------
# Step 1: ensure OHLCV (paginated fetch with dedup, D15 / D20 / S7)
# ---------------------------------------------------------------------------


@dataclass
class Step1Result:
    candle_count: int
    cache_hit: bool
    fetched_new: int
    range_start: datetime | None
    range_end: datetime | None


async def step1_ensure_ohlcv(
    engine,
    feeds,
    symbol: str,
    timeframe: str,
    days: int,
) -> Step1Result:
    """Ensure the local DB has at least ``days * 24`` candles for the symbol.

    Cache check: if rows already present cover the requested span, skip the
    fetch entirely (D10). Otherwise paginate forward in time from
    ``now - days``, deduplicating on timestamp (D15), with at most
    ``MAX_FETCH_ITERATIONS`` iterations (D20).
    """
    import polars as pl
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from trdex.storage.ohlcv_repo import OHLCVRepository

    target_candles = days * 24
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # ---- 1. Cache check ---------------------------------------------------
    async with session_factory() as session:
        existing_count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM ohlcv WHERE symbol = :s AND timeframe = :tf"
                ),
                {"s": symbol, "tf": timeframe},
            )
        ).scalar_one()

    if existing_count >= target_candles:
        async with session_factory() as session:
            repo = OHLCVRepository(session)
            df = await repo.fetch_polars(symbol, timeframe, limit=target_candles + 100)
        ts_min = df["timestamp"].min() if len(df) else None
        ts_max = df["timestamp"].max() if len(df) else None
        return Step1Result(
            candle_count=len(df),
            cache_hit=True,
            fetched_new=0,
            range_start=ts_min,
            range_end=ts_max,
        )

    # ---- 2. Paginated fetch ----------------------------------------------
    print(
        f"  cache miss: have {existing_count} candles, need {target_candles}"
        f" - fetching from binance..."
    )
    since_dt = datetime.now(tz=timezone.utc) - timedelta(days=days)
    since_ms = _ms(since_dt)

    collected: list = []
    last_ts_ms: int | None = None
    iterations = 0

    try:
        while len(collected) < target_candles and iterations < MAX_FETCH_ITERATIONS:
            iterations += 1
            batch = await feeds.get_ohlcv(symbol, timeframe, limit=1000, since=since_ms)
            if not batch:
                break
            # Dedup against the last bar of the previous batch (S1 mitigation).
            if last_ts_ms is not None:
                batch = [c for c in batch if _ms(c.timestamp) > last_ts_ms]
            if not batch:
                break
            collected.extend(batch)
            last_ts_ms = _ms(batch[-1].timestamp)
            since_ms = last_ts_ms + 1  # next iteration starts strictly after
    except Exception as exc:
        # G2 / U4: surface the error with concrete next steps.
        print()
        print(f"ERROR step 1: failed to fetch OHLCV from binance: {exc!r}")
        print("Suggested actions:")
        print("  1. Check internet: curl -s https://api.binance.com/api/v3/ping")
        print("  2. Check rate limit: review the trdex-binance feed logs")
        print("  3. Retry in 60s")
        raise SystemExit(4) from exc

    if iterations >= MAX_FETCH_ITERATIONS and len(collected) < target_candles:
        print(
            f"  WARNING: fetch stopped after {iterations} iterations with"
            f" {len(collected)}/{target_candles} candles; proceeding with partial data"
        )

    # ---- 3. Persist ------------------------------------------------------
    async with session_factory() as session:
        repo = OHLCVRepository(session)
        inserted = await repo.upsert(symbol, timeframe, collected)
        df = await repo.fetch_polars(symbol, timeframe, limit=target_candles + 100)

    ts_min = df["timestamp"].min() if len(df) else None
    ts_max = df["timestamp"].max() if len(df) else None
    return Step1Result(
        candle_count=len(df),
        cache_hit=False,
        fetched_new=inserted,
        range_start=ts_min,
        range_end=ts_max,
    )


# ---------------------------------------------------------------------------
# Step 2: run backtest
# ---------------------------------------------------------------------------


def step2_run_backtest(
    df,
    symbol: str,
    position_size_pct: float,
    timeframe: str,
):
    from trdex.backtest.engine import run_backtest
    from trdex.strategy.backtest.sma_cross import BacktestSMACross

    strategy = BacktestSMACross()
    return run_backtest(
        ohlcv=df,
        strategy=strategy,
        symbol=symbol,
        initial_capital=float(INITIAL_BALANCE),
        position_size_pct=position_size_pct,
        fee_rate=0.001,
        timeframe=timeframe,
    )


# ---------------------------------------------------------------------------
# Step 3: replay backtest trades into account_balance + agent_runs
# ---------------------------------------------------------------------------


@dataclass
class Step3Result:
    rows_added_balance: int          # total rows in account_balance (seed + fills)
    rows_added_balance_fills: int    # only trade_fill events
    rows_added_agent_runs: int


async def step3_replay(
    engine,
    df,
    result,
    symbol: str,
    position_size_pct: float,
) -> Step3Result:
    """Replay every closed trade into account_balance and agent_runs.

    Pre-check (D17 / D21): abort if there are already agent_runs rows
    marked as backtest replays. Use --reset to start clean.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from trdex.storage.agent_run_models import AgentRunRecord
    from trdex.storage.balance_models import BalanceRecord

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # ---- 1. Pre-check for existing replay rows --------------------------
    async with session_factory() as session:
        existing_replays = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM agent_runs WHERE risk_reason = :marker"
                ),
                {"marker": BACKTEST_REPLAY_MARKER},
            )
        ).scalar_one()

    if existing_replays > 0:
        print(
            f"\nERROR step 3: found {existing_replays} existing backtest replay rows in agent_runs."
        )
        print("This script must run on a clean replay slate.")
        print("Re-run with --reset to clear them.")
        raise SystemExit(3)

    # ---- 2. Iterate trades, build ORM objects --------------------------
    if result.total_trades == 0:
        return Step3Result(
            rows_added_balance=0,
            rows_added_balance_fills=0,
            rows_added_agent_runs=0,
        )

    timestamps = df["timestamp"].to_list()
    running_balance = INITIAL_BALANCE
    bal_records: list[BalanceRecord] = []
    run_records: list[AgentRunRecord] = []

    # Seed deposit, dated strictly before the first bar of the dataset.
    # Without this, current_balance() (which orders by recorded_at DESC
    # and limit 1) would return the present-day re-seed deposit instead
    # of the last historical trade fill.
    first_ts = timestamps[0]
    first_ts_naive = first_ts.replace(tzinfo=None) if first_ts.tzinfo else first_ts
    seed_ts = first_ts_naive - timedelta(seconds=1)
    bal_records.append(
        BalanceRecord(
            event_type="deposit",
            amount=INITIAL_BALANCE,
            balance_after=INITIAL_BALANCE,
            note="smoke_level3 backtest replay seed",
            recorded_at=seed_ts,
        )
    )

    for trade in result.trades.iter_rows(named=True):
        entry_idx = int(trade["entry_idx"])
        exit_idx = int(trade["exit_idx"])
        entry_ts = timestamps[entry_idx]
        exit_ts = timestamps[exit_idx]

        # Strip tz (asyncpg + TIMESTAMP requires naive UTC).
        entry_ts_naive = entry_ts.replace(tzinfo=None) if entry_ts.tzinfo else entry_ts
        exit_ts_naive = exit_ts.replace(tzinfo=None) if exit_ts.tzinfo else exit_ts

        pnl = Decimal(str(trade["pnl"])).quantize(Decimal("0.00000001"))
        running_balance = running_balance + pnl

        bal_records.append(
            BalanceRecord(
                event_type="trade_fill",
                amount=pnl,
                balance_after=running_balance,
                note=(
                    f"backtest sma_cross {symbol} entry={entry_ts_naive.isoformat()}"
                ),
                recorded_at=exit_ts_naive,
            )
        )

        run_records.append(
            AgentRunRecord(
                run_id=str(uuid.uuid4()),  # valid UUID; marker lives in risk_reason
                symbol=symbol,
                ran_at=exit_ts_naive,
                signal="open_long",  # backtest replay: one row per closed trade, tagged as the open
                confidence=0.5,
                reasoning="backtest replay sma_cross(9,21)",
                indicators={},
                risk_approved=True,
                risk_reason=BACKTEST_REPLAY_MARKER,
                position_size=position_size_pct,
                stop_loss_pct=0.0,
                take_profit_pct=0.0,
                order_status="filled",
                filled_price=float(trade["exit_price"]),
                filled_qty=float(trade["qty"]),
                order_message=f"backtest fill pnl={float(pnl):+.4f}",
            )
        )

    # ---- 3. Single batch commit (D18) -----------------------------------
    try:
        async with session_factory() as session:
            session.add_all(bal_records)
            session.add_all(run_records)
            await session.commit()
    except Exception as exc:
        print(f"\nERROR step 3: db replay failed during commit: {exc!r}")
        print("Re-run with --reset to start clean.")
        raise SystemExit(3) from exc

    return Step3Result(
        rows_added_balance=len(bal_records),
        rows_added_balance_fills=sum(1 for r in bal_records if r.event_type == "trade_fill"),
        rows_added_agent_runs=len(run_records),
    )


# ---------------------------------------------------------------------------
# Step 4: readiness evaluation
# ---------------------------------------------------------------------------


async def step4_readiness(engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from trdex.config import get_settings
    from trdex.risk.readiness import evaluate_readiness

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        return await evaluate_readiness(session, get_settings())


# ---------------------------------------------------------------------------
# Step 5: coherence checks
# ---------------------------------------------------------------------------


@dataclass
class CoherenceCheck:
    name: str
    ok: bool
    detail: str


async def step5_coherence(engine, result) -> list[CoherenceCheck]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    checks: list[CoherenceCheck] = []

    async with session_factory() as session:
        # Trade count in account_balance
        n_balance_trades = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM account_balance WHERE event_type = 'trade_fill'"
                )
            )
        ).scalar_one()
        checks.append(
            CoherenceCheck(
                name="account_balance trade_fill count == backtest trades",
                ok=n_balance_trades == result.total_trades,
                detail=f"{n_balance_trades} vs {result.total_trades}",
            )
        )

        # Agent_runs filled count (only the backtest replays)
        n_runs_filled = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM agent_runs"
                    " WHERE order_status = 'filled' AND risk_reason = :marker"
                ),
                {"marker": BACKTEST_REPLAY_MARKER},
            )
        ).scalar_one()
        checks.append(
            CoherenceCheck(
                name="agent_runs (backtest) filled count == backtest trades",
                ok=n_runs_filled == result.total_trades,
                detail=f"{n_runs_filled} vs {result.total_trades}",
            )
        )

        # Final balance match
        ledger_final = (
            await session.execute(
                text(
                    "SELECT balance_after FROM account_balance"
                    " ORDER BY recorded_at DESC, id DESC LIMIT 1"
                )
            )
        ).scalar_one()
        expected_final = float(INITIAL_BALANCE) + (
            result.final_capital - result.initial_capital
        )
        diff = abs(float(ledger_final) - expected_final)
        checks.append(
            CoherenceCheck(
                name="ledger final balance == backtest final equity (tol 0.01)",
                ok=diff < 0.01,
                detail=f"ledger={float(ledger_final):.4f} expected={expected_final:.4f} diff={diff:.4f}",
            )
        )

    return checks


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------


def _format_pct(value: float) -> str:
    return f"{value * 100:+.2f}%" if isinstance(value, float) else str(value)


def _gate_line(name: str, value, op: str, threshold, *, note: str = "") -> str:
    """Format a single gate line. ``op`` is one of '>=', '<='."""
    passed = (value >= threshold) if op == ">=" else (value <= threshold)
    flag = "PASS" if passed else "FAIL"
    if note:
        flag = f"{flag}*"
    if isinstance(value, float):
        if value <= 1.0 and "rate" in name.lower():
            value_str = f"{value * 100:.1f}%"
            thr_str = f"{threshold * 100:.0f}%"
        elif "drawdown" in name.lower():
            value_str = f"{value * 100:.1f}%"
            thr_str = f"{threshold * 100:.0f}%"
        else:
            value_str = f"{value:.2f}"
            thr_str = f"{threshold:.2f}"
    else:
        value_str = str(value)
        thr_str = str(threshold)
    line = f"  {name:<18}: {value_str:<7} (gate: {op}{thr_str:<6}) [{flag}]"
    if note:
        line += f"  {note}"
    return line


def print_final_report(
    *,
    args,
    settings,
    step1: Step1Result,
    backtest_result,
    step3: Step3Result,
    readiness_report,
    coherence: list[CoherenceCheck],
    effective_position_size: float,
    position_size_source: str,
) -> int:
    """Print the final structured report. Returns the exit code (0 or 1)."""
    print()
    print("=" * 64)
    print("smoke_level3 - backtest end-to-end")
    print(
        f"symbol: {args.symbol}  timeframe: {args.timeframe}  days: {args.days}  "
        f"strategy: sma_cross(9,21)"
    )
    print(
        f"position_size_pct: {effective_position_size * 100:.1f}% "
        f"(from {position_size_source})"
    )
    print("=" * 64)

    # ---- step 1 ---------------------------------------------------------
    print("\n[1/5] OHLCV data")
    cache_label = "cache hit" if step1.cache_hit else "fresh fetch"
    print(f"  {cache_label}: {step1.candle_count} candles available")
    if not step1.cache_hit:
        print(f"  fetched new   : {step1.fetched_new} rows")
    if step1.range_start and step1.range_end:
        print(
            f"  range         : {step1.range_start.strftime('%Y-%m-%d %H:%M')}"
            f" -> {step1.range_end.strftime('%Y-%m-%d %H:%M')}"
        )

    # ---- step 2 ---------------------------------------------------------
    print("\n[2/5] Backtest")
    print(f"  trades        : {backtest_result.total_trades}")
    print(f"  win rate      : {backtest_result.win_rate * 100:.1f}%   (true, from PnL)")
    print(f"  total return  : {backtest_result.total_return_pct:+.2f}%")
    print(f"  final equity  : ${backtest_result.final_capital:,.2f}")
    print(
        f"  max drawdown  : {backtest_result.max_drawdown_pct:.2f}%"
        f"  (engine, intra-bar mark-to-market)"
    )
    print(
        f"  sharpe        : {backtest_result.sharpe_ratio:.3f}"
        f"   (annualised, {args.timeframe} bars)"
    )

    # ---- step 3 ---------------------------------------------------------
    print("\n[3/5] Replay to DB")
    print(
        f"  account_balance rows added: {step3.rows_added_balance}"
        f"  ({step3.rows_added_balance_fills} trade_fill + 1 seed deposit)"
    )
    print(f"  agent_runs rows added     : {step3.rows_added_agent_runs}")

    # ---- step 4 ---------------------------------------------------------
    print("\n[4/5] Readiness gate")
    print(
        _gate_line(
            "sim_days",
            readiness_report.sim_days,
            ">=",
            readiness_report.criteria["min_days"],
        )
    )
    print(
        _gate_line(
            "total_trades",
            readiness_report.total_trades,
            ">=",
            readiness_report.criteria["min_trades"],
        )
    )
    print(
        _gate_line(
            "win_rate",
            readiness_report.win_rate,
            ">=",
            readiness_report.criteria["min_win_rate"],
        )
    )
    print(
        _gate_line(
            "max_drawdown",
            readiness_report.max_drawdown_pct,
            "<=",
            readiness_report.criteria["max_drawdown"],
            note="(EoD equity peak-to-trough)",
        )
    )
    if readiness_report.sharpe is not None:
        print(
            _gate_line(
                "sharpe",
                readiness_report.sharpe,
                ">=",
                readiness_report.criteria["min_sharpe"],
            )
        )
    else:
        print(
            f"  {'sharpe':<18}: {'n/a':<7} "
            f"(gate: >={readiness_report.criteria['min_sharpe']:.2f}  ) [SKIP]"
            "  insufficient daily returns"
        )
    readiness_verdict = "READY" if readiness_report.ready else "NOT READY"
    print(f"  VERDICT (readiness gate): {readiness_verdict}")
    if readiness_report.failures:
        print(f"  failures: {readiness_report.failures}")

    # ---- step 5 ---------------------------------------------------------
    print("\n[5/5] Coherence checks")
    for c in coherence:
        flag = "OK" if c.ok else "FAIL"
        print(f"  [{flag}] {c.name}")
        print(f"         {c.detail}")

    # ---- overall verdict (D26) ------------------------------------------
    print()
    print("=" * 64)
    backtest_min_win = settings.gate_min_win_rate
    backtest_max_dd = settings.gate_max_drawdown * 100  # backtest dd is in %, gate is 0..1
    backtest_passes = (
        backtest_result.total_return_pct > 0
        and backtest_result.win_rate >= backtest_min_win
        and (backtest_result.max_drawdown_pct / 100) <= settings.gate_max_drawdown
    )
    coherence_passes = all(c.ok for c in coherence)
    overall_ready = readiness_report.ready and backtest_passes and coherence_passes

    overall = "READY" if overall_ready else "NOT READY"
    print(f"OVERALL VERDICT (smoke_level3): {overall}")
    print()
    if not overall_ready:
        print("Why NOT READY (combining readiness gate AND backtest reality):")
        if not readiness_report.ready:
            for f in readiness_report.failures:
                print(f"  - readiness: {f}")
        if backtest_result.total_return_pct <= 0:
            print(
                f"  - backtest: total_return {backtest_result.total_return_pct:+.2f}%"
                " (loss-making)"
            )
        if backtest_result.win_rate < backtest_min_win:
            print(
                f"  - backtest: win_rate {backtest_result.win_rate * 100:.1f}%"
                f" < {backtest_min_win * 100:.0f}% required"
            )
        if (backtest_result.max_drawdown_pct / 100) > settings.gate_max_drawdown:
            print(
                f"  - backtest: max_drawdown {backtest_result.max_drawdown_pct:.1f}%"
                f" > {backtest_max_dd:.0f}% limit"
            )
        if not coherence_passes:
            print("  - coherence: see failed checks above")
        print()
        print(
            "This is the EXPECTED first-baseline outcome on a naked SMA cross."
            " The script's purpose is to validate the pipeline, not to find alpha."
        )
    print("=" * 64)

    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--reset", action="store_true", help="TRUNCATE ohlcv/ledger/agent_runs/positions")
    parser.add_argument("--yes", action="store_true", help="skip --reset confirmation prompt")
    parser.add_argument(
        "--position-size",
        type=float,
        default=None,
        metavar="PCT",
        help=(
            "Override the position size as a fraction in (0, 1]. "
            "Default: read from Settings.max_position_pct (typically 0.02). "
            "Use this to explore how the strategy behaves at higher sizing "
            "(e.g. --position-size 0.95 for near-full equity, which produces "
            "a realistic drawdown signal)."
        ),
    )
    args = parser.parse_args()

    if args.position_size is not None:
        if not (0 < args.position_size <= 1.0):
            print(
                f"ERROR: --position-size must be in (0, 1], got {args.position_size}"
            )
            return 1

    from sqlalchemy.ext.asyncio import create_async_engine

    from trdex.config import get_settings
    from trdex.market.feeds.binance import BinanceFeed
    from trdex.market.manager import PriceFeedManager

    settings = get_settings()

    # Resolve effective position size: CLI override wins over settings.
    effective_position_size = (
        args.position_size if args.position_size is not None else settings.max_position_pct
    )
    position_size_source = (
        "CLI --position-size override"
        if args.position_size is not None
        else "Settings.max_position_pct"
    )

    print(f"\nsmoke_level3 starting (mode={settings.mode.value}, db={_redact(settings.database_url)})")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    feeds = PriceFeedManager()
    binance = BinanceFeed()
    feeds.register(binance)

    try:
        # ---- Step 0: --reset handling --------------------------------
        if not await step0_handle_reset(engine, args.reset, args.yes):
            return 0

        # ---- Step 1: ensure OHLCV ------------------------------------
        _section("Step 1 / 5: ensure OHLCV")
        step1 = await step1_ensure_ohlcv(engine, feeds, args.symbol, args.timeframe, args.days)

        # ---- Step 2: load df + run backtest --------------------------
        _section("Step 2 / 5: run backtest")
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from trdex.storage.ohlcv_repo import OHLCVRepository

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            repo = OHLCVRepository(session)
            df = await repo.fetch_polars(args.symbol, args.timeframe, limit=args.days * 24 + 100)

        backtest_result = step2_run_backtest(
            df, args.symbol, effective_position_size, args.timeframe
        )

        if backtest_result.total_trades == 0:
            print()
            print("ERROR: backtest produced 0 trades. Cannot validate pipeline.")
            print(
                "Suggested actions:"
                f"\n  1. Extend the window: --days {args.days * 2}"
                "\n  2. Try a different timeframe (e.g. 15m)"
                "\n  3. Verify the strategy parameters in BacktestSMACross"
            )
            return 2

        # ---- Step 3: replay to DB ------------------------------------
        _section("Step 3 / 5: replay trades to ledger and agent_runs")
        step3 = await step3_replay(
            engine, df, backtest_result, args.symbol, effective_position_size
        )

        # ---- Step 4: readiness ---------------------------------------
        _section("Step 4 / 5: readiness gate")
        readiness_report = await step4_readiness(engine)

        # ---- Step 5: coherence ---------------------------------------
        _section("Step 5 / 5: coherence checks")
        coherence = await step5_coherence(engine, backtest_result)

        # ---- Final report --------------------------------------------
        return print_final_report(
            args=args,
            settings=settings,
            effective_position_size=effective_position_size,
            position_size_source=position_size_source,
            step1=step1,
            backtest_result=backtest_result,
            step3=step3,
            readiness_report=readiness_report,
            coherence=coherence,
        )
    finally:
        await binance.close()
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
