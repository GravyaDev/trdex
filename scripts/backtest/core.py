"""Backtest engine core — dataclass, metrics, aggregation, quarter split.

The main `run_backtest` entry point is added in Task 4. This file is
loaded first with the data types and pure helpers so tests can lock
them down before engine logic is written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from statistics import mean, pstdev
from typing import Any


@dataclass
class BacktestResult:
    strategy_name: str
    final_equity: float
    total_pnl: float
    return_pct: float
    trades_count: int
    wins: int
    win_rate: float
    sharpe: float
    max_drawdown_pct: float
    exit_reasons: dict[str, int]
    trades: list[dict[str, Any]]
    per_symbol: dict[str, dict[str, Any]]
    per_quarter: dict[str, dict[str, Any]]


def max_drawdown(equity_curve: list[float]) -> float:
    """Return maximum peak-to-trough drawdown as a percentage (0–100)."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        if peak > 0:
            dd = max(dd, (peak - v) / peak * 100.0)
    return dd


def sharpe_ratio(
    equity_curve: list[float],
    bars_per_year: int = 8760,
    risk_free_rate: float = 0.0,
) -> float:
    """Annualised Sharpe from bar-by-bar equity snapshots."""
    if len(equity_curve) < 2:
        return 0.0
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] > 0
    ]
    if len(returns) < 2:
        return 0.0
    std = pstdev(returns)
    if std == 0:
        return 0.0
    bar_sharpe = (mean(returns) - risk_free_rate) / std
    return bar_sharpe * sqrt(bars_per_year)


def aggregate_1h_to_1d(bars: list[list]) -> list[list]:
    """Aggregate 1h OHLCV bars into 1d bars.

    Groups by UTC day (86_400_000 ms). Each output bar:
      [day_start_ts_ms, open=first_bar_open, high=max_highs, low=min_lows,
       close=last_bar_close, volume=sum_volumes]
    """
    if not bars:
        return []
    day_ms = 86_400_000
    out: list[list] = []
    current_day = bars[0][0] // day_ms
    group: list[list] = []
    for bar in bars:
        d = bar[0] // day_ms
        if d != current_day:
            out.append(_daily_bar(group, current_day * day_ms))
            group = []
            current_day = d
        group.append(bar)
    if group:
        out.append(_daily_bar(group, current_day * day_ms))
    return out


def _daily_bar(group: list[list], day_start_ts: int) -> list:
    return [
        day_start_ts,
        group[0][1],                     # open
        max(b[2] for b in group),        # high
        min(b[3] for b in group),        # low
        group[-1][4],                    # close
        sum(b[5] for b in group),        # volume
    ]


def split_trades_by_quarter(trades: list[dict]) -> dict[str, list[dict]]:
    """Split trades into 4 buckets of ~91 days anchored to oldest entry_ts.

    Returns empty dict for empty input. Trades missing 'entry_ts' are skipped.
    """
    if not trades:
        return {}
    sorted_trades = sorted(trades, key=lambda t: t["entry_ts"])
    first_ts = sorted_trades[0]["entry_ts"]
    quarter_ms = 91 * 86_400_000
    buckets: dict[str, list[dict]] = {f"Q{i + 1}": [] for i in range(4)}
    for t in sorted_trades:
        q = min(3, (t["entry_ts"] - first_ts) // quarter_ms)
        buckets[f"Q{int(q) + 1}"].append(t)
    return buckets
