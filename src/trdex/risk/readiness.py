"""Simulation readiness checker — evaluates whether the system has proven
itself in simulation before allowing live trading.

The gate reads from two tables:
    - ``agent_runs`` for the time-coverage signal (sim_days = how long has
      the system been running?)
    - ``account_balance`` for trade-level P&L (the only place a true
      realised PnL is recorded)

Win rate, total trades, Sharpe ratio and max drawdown are all computed
from the ledger so they remain consistent with the cash actually moved.

Sharpe ratio
------------
We resample the ledger equity to daily close-of-day equity, compute
daily returns, and annualise the result with sqrt(252) — the standard
finance convention. With <2 days of activity the Sharpe is left as
``None`` (insufficient data) and the gate is skipped, not failed.

Fail-closed: any data gap or computation error returns ``ready=False``.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trdex.storage.agent_run_models import AgentRunRecord
from trdex.storage.balance_models import BalanceRecord

logger = logging.getLogger(__name__)

MIN_TRADES_FOR_EVALUATION = 20  # Must have at least this many filled trades
TRADING_DAYS_PER_YEAR = 252      # Standard equity-market annualisation factor


@dataclass
class ReadinessReport:
    """Result of a readiness evaluation."""

    ready: bool
    sim_days: int
    total_trades: int
    win_rate: float
    sharpe: float | None            # None if insufficient data (<2 daily returns)
    max_drawdown_pct: float
    kill_switch_events: int
    criteria: dict                   # the thresholds from config
    failures: list[str]             # human-readable list of unmet criteria


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalise a possibly tz-aware datetime to naive UTC."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _eod_equity_curve(ledger_rows: list[BalanceRecord]) -> dict[date, float]:
    """Build an end-of-day equity curve from a ledger.

    Strategy: for each calendar day represented in the ledger, take the
    last ``balance_after`` recorded that day. Days without activity are
    NOT interpolated — they are simply absent from the result. The Sharpe
    calculation downstream uses only days with explicit data points,
    which is the correct behaviour when comparing to a backtest that
    only marks equity at trade events.
    """
    eod: dict[date, float] = {}
    for r in ledger_rows:
        d = _to_naive_utc(r.recorded_at).date()
        eod[d] = float(r.balance_after)  # later writes overwrite earlier ones
    return dict(sorted(eod.items()))


def _daily_returns(eod_equity: dict[date, float]) -> list[float]:
    """Compute daily simple returns from an EoD equity curve.

    Returns a list of (eq_t / eq_{t-1} - 1) over consecutive entries
    of the dict (already sorted by ``_eod_equity_curve``). Days with
    zero or negative equity are skipped to avoid division by zero.
    """
    values = list(eod_equity.values())
    returns: list[float] = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        curr = values[i]
        if prev <= 0:
            continue
        returns.append(curr / prev - 1.0)
    return returns


def _annualised_sharpe(daily_returns: list[float]) -> float | None:
    """Annualised Sharpe ratio from a list of daily simple returns.

    Returns ``None`` when there are fewer than 2 returns or when the
    standard deviation is zero (a flat equity curve has undefined
    risk-adjusted return — refusing to make up a number is the right
    choice for a fail-closed gate).
    """
    n = len(daily_returns)
    if n < 2:
        return None
    mean = sum(daily_returns) / n
    variance = sum((r - mean) ** 2 for r in daily_returns) / (n - 1)
    std = math.sqrt(variance)
    if std == 0:
        return None
    return (mean / std) * math.sqrt(TRADING_DAYS_PER_YEAR)


def _max_drawdown_from_equity(eod_equity: dict[date, float]) -> float:
    """Max peak-to-trough drawdown over an EoD equity curve, as a fraction.

    Returns 0.0 if the curve is empty or never declines. The result is
    in [0.0, 1.0]: 0.20 means a 20% drawdown from the running peak.
    """
    peak = -math.inf
    max_dd = 0.0
    for v in eod_equity.values():
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def evaluate_readiness(session: AsyncSession, settings) -> ReadinessReport:
    """Evaluate whether simulation results meet the live-trading gate criteria.

    Reads time coverage from ``agent_runs`` and trade P&L from
    ``account_balance``. Fail-closed: missing data → not ready.
    """
    failures: list[str] = []

    # ---- 1. Sim days from agent_runs.ran_at -----------------------------
    first_run = (
        await session.execute(select(func.min(AgentRunRecord.ran_at)))
    ).scalar()
    if first_run is None:
        return ReadinessReport(
            ready=False,
            sim_days=0,
            total_trades=0,
            win_rate=0.0,
            sharpe=None,
            max_drawdown_pct=0.0,
            kill_switch_events=0,
            criteria=_criteria_dict(settings),
            failures=["No simulation data."],
        )
    first_run = _to_naive_utc(first_run)
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    sim_days = (now - first_run).days

    # ---- 2. Trades + win rate from account_balance ----------------------
    fills_result = await session.execute(
        select(BalanceRecord)
        .where(BalanceRecord.event_type == "trade_fill")
        .order_by(BalanceRecord.recorded_at.asc())
    )
    fills: list[BalanceRecord] = list(fills_result.scalars().all())

    total_trades = len(fills)
    wins = sum(1 for f in fills if float(f.amount) > 0)
    losses = sum(1 for f in fills if float(f.amount) < 0)
    decisive = wins + losses  # exclude break-even (amount == 0)
    win_rate = wins / decisive if decisive > 0 else 0.0

    # ---- 3. Equity curve, drawdown, Sharpe ------------------------------
    # Use the FULL ledger (deposits + fills) for the equity curve so that
    # the seed deposit anchors the starting equity. Drawdown and Sharpe
    # are then computed off the same curve for internal consistency.
    full_ledger_result = await session.execute(
        select(BalanceRecord).order_by(BalanceRecord.recorded_at.asc())
    )
    full_ledger = list(full_ledger_result.scalars().all())

    eod = _eod_equity_curve(full_ledger)
    daily_rets = _daily_returns(eod)
    sharpe = _annualised_sharpe(daily_rets)
    max_drawdown_pct = _max_drawdown_from_equity(eod)

    # ---- 4. Kill switch events (still in logs, not in DB) ---------------
    kill_switch_events = 0

    # ---- 5. Evaluate against gate criteria ------------------------------
    # Read gate_min_days from Runtime Config if available, else fall back
    # to the static settings value. This allows editing the gate from the
    # dashboard without a redeploy.
    from trdex.services.runtime_config import get_config_service
    _cfg = get_config_service()
    effective_min_days = (
        _cfg.get_typed("thresholds", "gate_min_days", settings.gate_min_days)
        if _cfg is not None else settings.gate_min_days
    )

    if sim_days < effective_min_days:
        failures.append(
            f"Simulation days: {sim_days} < {effective_min_days} required"
        )

    if total_trades < MIN_TRADES_FOR_EVALUATION:
        failures.append(
            f"Total trades: {total_trades} < {MIN_TRADES_FOR_EVALUATION} minimum"
        )

    if win_rate < settings.gate_min_win_rate:
        failures.append(
            f"Win rate: {win_rate:.1%} < {settings.gate_min_win_rate:.1%} required"
        )

    if max_drawdown_pct > settings.gate_max_drawdown:
        failures.append(
            f"Max drawdown: {max_drawdown_pct:.1%} > {settings.gate_max_drawdown:.1%} limit"
        )

    # Sharpe gate is enforced only when we have enough data to compute it.
    # When sharpe is None (less than 2 daily returns), the gate is treated
    # as "insufficient data" and contributes a failure — fail-closed.
    if sharpe is None:
        failures.append(
            f"Sharpe: insufficient data (<2 daily returns), need >= {settings.gate_min_sharpe:.2f}"
        )
    elif sharpe < settings.gate_min_sharpe:
        failures.append(
            f"Sharpe: {sharpe:.2f} < {settings.gate_min_sharpe:.2f} required"
        )

    ready = len(failures) == 0

    return ReadinessReport(
        ready=ready,
        sim_days=sim_days,
        total_trades=total_trades,
        win_rate=win_rate,
        sharpe=sharpe,
        max_drawdown_pct=max_drawdown_pct,
        kill_switch_events=kill_switch_events,
        criteria=_criteria_dict(settings, effective_min_days),
        failures=failures,
    )


def _criteria_dict(settings, effective_min_days: int | None = None) -> dict:
    return {
        "min_days": effective_min_days if effective_min_days is not None else settings.gate_min_days,
        "min_sharpe": settings.gate_min_sharpe,
        "max_drawdown": settings.gate_max_drawdown,
        "min_win_rate": settings.gate_min_win_rate,
        "min_trades": MIN_TRADES_FOR_EVALUATION,
    }
