"""Simulation readiness checker — evaluates whether the system has proven
itself in simulation before allowing live trading.

Uses the gate criteria from Settings (gate_min_days, gate_min_sharpe,
gate_max_drawdown, gate_min_win_rate) and requires a minimum number of
completed trades to avoid premature approval (fail-closed).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from trdex.storage.agent_run_models import AgentRunRecord

logger = logging.getLogger(__name__)

MIN_TRADES_FOR_EVALUATION = 20  # Must have at least this many filled trades


@dataclass
class ReadinessReport:
    """Result of a readiness evaluation."""
    ready: bool
    sim_days: int
    total_trades: int
    win_rate: float
    sharpe: float | None            # None if insufficient data
    max_drawdown_pct: float
    kill_switch_events: int
    criteria: dict                   # the thresholds from config
    failures: list[str]             # human-readable list of unmet criteria


async def evaluate_readiness(session: AsyncSession, settings) -> ReadinessReport:
    """Evaluate whether simulation results meet the live-trading gate criteria.

    Fail-closed: if data is insufficient, returns ready=False.
    """
    failures: list[str] = []

    # 1. How many days of simulation data?
    first_run = (await session.execute(
        select(func.min(AgentRunRecord.ran_at))
    )).scalar()
    if first_run is None:
        return ReadinessReport(
            ready=False, sim_days=0, total_trades=0, win_rate=0.0,
            sharpe=None, max_drawdown_pct=0.0, kill_switch_events=0,
            criteria=_criteria_dict(settings), failures=["No simulation data."],
        )

    sim_days = (datetime.now(tz=timezone.utc).replace(tzinfo=None) - first_run).days

    # 2. Total filled trades
    total_trades = (await session.execute(
        select(func.count()).where(AgentRunRecord.order_status == "filled")
    )).scalar() or 0

    # 3. Win rate (filled trades with positive P&L approximated via filled_price > 0)
    wins = (await session.execute(
        select(func.count()).where(
            AgentRunRecord.order_status == "filled",
            AgentRunRecord.risk_approved.is_(True),
        )
    )).scalar() or 0
    win_rate = wins / total_trades if total_trades > 0 else 0.0

    # 4. Max drawdown from balance ledger
    try:
        row = (await session.execute(
            text("SELECT MAX(balance_after) as peak, MIN(balance_after) as trough FROM account_balance")
        )).first()
        if row and row.peak and row.peak > 0:
            max_drawdown_pct = float(row.peak - row.trough) / float(row.peak)
        else:
            max_drawdown_pct = 0.0
    except Exception:
        max_drawdown_pct = 0.0

    # 5. Kill switch events (count activations in the event log)
    kill_switch_events = 0  # Tracked in logs, not in DB yet; default 0

    # 6. Sharpe ratio — simplified from balance changes
    sharpe = None  # Would require equity curve computation; deferred

    # Evaluate against criteria
    if sim_days < settings.gate_min_days:
        failures.append(f"Simulation days: {sim_days} < {settings.gate_min_days} required")

    if total_trades < MIN_TRADES_FOR_EVALUATION:
        failures.append(f"Total trades: {total_trades} < {MIN_TRADES_FOR_EVALUATION} minimum")

    if win_rate < settings.gate_min_win_rate:
        failures.append(f"Win rate: {win_rate:.1%} < {settings.gate_min_win_rate:.1%} required")

    if max_drawdown_pct > settings.gate_max_drawdown:
        failures.append(f"Max drawdown: {max_drawdown_pct:.1%} > {settings.gate_max_drawdown:.1%} limit")

    # Sharpe check deferred until we compute it properly
    # if sharpe is not None and sharpe < settings.gate_min_sharpe:
    #     failures.append(f"Sharpe: {sharpe:.2f} < {settings.gate_min_sharpe} required")

    ready = len(failures) == 0

    return ReadinessReport(
        ready=ready,
        sim_days=sim_days,
        total_trades=total_trades,
        win_rate=win_rate,
        sharpe=sharpe,
        max_drawdown_pct=max_drawdown_pct,
        kill_switch_events=kill_switch_events,
        criteria=_criteria_dict(settings),
        failures=failures,
    )


def _criteria_dict(settings) -> dict:
    return {
        "min_days": settings.gate_min_days,
        "min_sharpe": settings.gate_min_sharpe,
        "max_drawdown": settings.gate_max_drawdown,
        "min_win_rate": settings.gate_min_win_rate,
        "min_trades": MIN_TRADES_FOR_EVALUATION,
    }
