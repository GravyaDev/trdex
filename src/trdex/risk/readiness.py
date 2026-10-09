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

Volatility-regime bounds
------------------------
Live entries are gated on thresholds.regime_cv_min / regime_cv_max
(Risk Gate 4c). The in-app regime refresher (``trdex.research.
regime_refresh``) sets them every week once the live rules pass
revalidation; ``scripts/backtest/regime_range.py`` is the manual
fallback. The gate is not ready until the bounds are set, coherent, and
derived from data ending no more than ``regime_max_age_days`` ago
(regime_data_end). If the regime gate has been on for less than
``gate_min_days`` the report carries a warning: most of the simulation
being judged ran without it.

Fail-closed: any data gap or computation error returns ``ready=False``.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trdex.storage.agent_run_models import AgentRunRecord
from trdex.storage.balance_models import BalanceRecord

logger = logging.getLogger(__name__)

MIN_TRADES_FOR_EVALUATION = 20  # Must have at least this many filled trades
TRADING_DAYS_PER_YEAR = 252      # Standard equity-market annualisation factor
REGIME_MAX_AGE_DAYS = 90         # default for thresholds.regime_max_age_days

_REGIME_HOWTO = (
    "the weekly regime refresher sets them once the live rules pass revalidation "
    "(see its status in the dashboard); manual fallback: "
    "`python -m scripts.backtest.regime_range`"
)


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
    warnings: list[str] = field(default_factory=list)  # do not block, shown to the operator


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


def _parse_bound(name: str, raw: Any) -> tuple[float | None, str | None]:
    """(value, error) for a regime bound. Blank or <= 0 means unset."""
    if raw is None or str(raw).strip() == "":
        return None, None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, f"Regime bounds: {name} {raw!r} is not a number"
    if not math.isfinite(value):
        return None, f"Regime bounds: {name} {raw!r} is not a number"
    return (value if value > 0 else None), None


def _parse_timestamp(raw: Any) -> datetime | None:
    """ISO date or datetime -> naive UTC datetime; None if blank or invalid."""
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return _to_naive_utc(datetime.fromisoformat(str(raw).strip()))
    except ValueError:
        return None


def regime_criteria(
    *,
    cv_min: Any,
    cv_max: Any,
    data_end: Any,
    set_at: Any,
    max_age_days: int,
    min_days: int,
    now: datetime,
) -> tuple[list[str], list[str]]:
    """Readiness failures and warnings for the volatility-regime bounds.

    Takes the raw Runtime Config values (strings or None) and ``now`` as
    naive UTC; pure so the rules are testable without a DB.

    Failures: bounds unset, not numbers, min >= max; regime_data_end
    missing, malformed, in the future, or older than ``max_age_days``.
    Warnings: regime_set_at (when the gate turned on) unknown, or more
    recent than ``min_days`` (the judged simulation mostly ran without it).
    """
    failures: list[str] = []
    warnings: list[str] = []
    max_age = max_age_days if max_age_days and max_age_days > 0 else REGIME_MAX_AGE_DAYS

    lo, lo_err = _parse_bound("regime_cv_min", cv_min)
    hi, hi_err = _parse_bound("regime_cv_max", cv_max)
    errors = [e for e in (lo_err, hi_err) if e]
    if errors:
        return errors, warnings
    if lo is None or hi is None:
        return [f"Regime bounds: not set — {_REGIME_HOWTO}"], warnings
    if lo >= hi:
        failures.append(f"Regime bounds: regime_cv_min {lo:g} >= regime_cv_max {hi:g}")

    if data_end is None or str(data_end).strip() == "":
        failures.append(f"Regime bounds: regime_data_end not set — {_REGIME_HOWTO}")
    else:
        end = _parse_timestamp(data_end)
        if end is None:
            failures.append(
                f"Regime bounds: regime_data_end {data_end!r} is not a YYYY-MM-DD date"
            )
        else:
            age = (now.date() - end.date()).days
            if age < -1:  # one day of slack for time zones
                failures.append(f"Regime bounds: regime_data_end {end.date()} is in the future")
            elif age > max_age:
                failures.append(
                    f"Regime bounds: derived from data ending {end.date()} "
                    f"({age} days ago > {max_age}) — the regime refresher has not renewed "
                    "them: check its status (or re-run scripts/backtest/regime_range.py)"
                )

    changed = _parse_timestamp(set_at)
    if changed is None:
        warnings.append(
            "Regime gate: activation date unknown — cannot verify that the "
            "simulation ran with it"
        )
    else:
        days_with = (now - changed).days
        if days_with < min_days:
            warnings.append(
                f"Regime gate on for {days_with} days (< {min_days} gate days): "
                "most of the simulation being judged ran without it"
            )
    return failures, warnings


def _regime_config(cfg: Any) -> dict[str, Any]:
    """Raw regime values from Runtime Config, as ``regime_criteria`` kwargs."""
    return {
        "cv_min": cfg.get("thresholds", "regime_cv_min", ""),
        "cv_max": cfg.get("thresholds", "regime_cv_max", ""),
        "data_end": cfg.get("thresholds", "regime_data_end", ""),
        "set_at": cfg.get("thresholds", "regime_set_at", ""),
        "max_age_days": cfg.get_typed("thresholds", "regime_max_age_days", REGIME_MAX_AGE_DAYS),
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def evaluate_readiness(
    session: AsyncSession, settings, config: Any = None
) -> ReadinessReport:
    """Evaluate whether simulation results meet the live-trading gate criteria.

    Reads time coverage from ``agent_runs``, trade P&L from
    ``account_balance`` and the regime bounds from Runtime Config
    (``config``, default: the process-wide service; CLIs pass one loaded
    from the DB). Fail-closed: missing data → not ready.
    """
    failures: list[str] = []
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)

    # ---- 0. Runtime Config: gate days + regime bounds --------------------
    # Read gate_min_days from Runtime Config if available, else fall back
    # to the static settings value. This allows editing the gate from the
    # dashboard without a redeploy. The regime criteria are evaluated even
    # without simulation data, so the operator sees them from day one and
    # sets the bounds before the simulation that will be judged.
    if config is None:
        from trdex.services.runtime_config import get_config_service
        config = get_config_service()
    _cfg = config
    effective_min_days = (
        _cfg.get_typed("thresholds", "gate_min_days", settings.gate_min_days)
        if _cfg is not None else settings.gate_min_days
    )
    regime: dict[str, Any] = {}
    if _cfg is None:
        regime_failures = ["Regime bounds: Runtime Config unavailable (fail-closed)"]
        regime_warnings: list[str] = []
    else:
        regime = _regime_config(_cfg)
        regime_failures, regime_warnings = regime_criteria(
            **regime, min_days=effective_min_days, now=now
        )

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
            criteria=_criteria_dict(settings, effective_min_days, regime),
            failures=["No simulation data.", *regime_failures],
            warnings=regime_warnings,
        )
    first_run = _to_naive_utc(first_run)
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

    failures.extend(regime_failures)
    ready = len(failures) == 0

    return ReadinessReport(
        ready=ready,
        sim_days=sim_days,
        total_trades=total_trades,
        win_rate=win_rate,
        sharpe=sharpe,
        max_drawdown_pct=max_drawdown_pct,
        kill_switch_events=kill_switch_events,
        criteria=_criteria_dict(settings, effective_min_days, regime),
        failures=failures,
        warnings=regime_warnings,
    )


def _criteria_dict(
    settings, effective_min_days: int | None = None, regime: dict[str, Any] | None = None
) -> dict:
    regime = regime or {}
    return {
        "min_days": effective_min_days if effective_min_days is not None else settings.gate_min_days,
        "min_sharpe": settings.gate_min_sharpe,
        "max_drawdown": settings.gate_max_drawdown,
        "min_win_rate": settings.gate_min_win_rate,
        "min_trades": MIN_TRADES_FOR_EVALUATION,
        "regime_cv_min": regime.get("cv_min") or None,
        "regime_cv_max": regime.get("cv_max") or None,
        "regime_data_end": regime.get("data_end") or None,
        "regime_set_at": regime.get("set_at") or None,
        "regime_max_age_days": regime.get("max_age_days") or REGIME_MAX_AGE_DAYS,
    }
