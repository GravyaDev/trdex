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


from typing import Literal, Protocol


Signal = Literal["BUY", "SELL", "CLOSE_LONG", "CLOSE_SHORT", "HOLD"]


class Strategy(Protocol):
    name: str
    timeframe: str

    def generate_signal(
        self,
        bar_index: int,
        candles: list,
        indicators: dict,
        position_state: str,
    ) -> Signal: ...


@dataclass
class EngineParams:
    initial_equity: float = 10_000.0
    position_size_pct: float = 0.05
    fee_pct: float = 0.001
    sl_pct: float = 0.02
    tp_pct: float = 0.04
    trail_pct: float = 0.015


def run_backtest(
    strategy: Strategy,
    ohlcv_by_symbol: dict[str, list[list]],
    params: EngineParams,
) -> BacktestResult:
    """Run the given strategy across all symbols with shared equity.

    Iteration order: symbols are processed sequentially. Within each symbol
    we loop bar-by-bar. Equity withdrawn at open is restored at close.
    """
    equity = [params.initial_equity]  # mutable cell for closures
    trades: list[dict[str, Any]] = []
    equity_curve = [params.initial_equity]

    for symbol, bars in ohlcv_by_symbol.items():
        if strategy.timeframe == "1d":
            working_bars = aggregate_1h_to_1d(bars)
        else:
            working_bars = bars

        indicators = _precompute_indicators(working_bars)
        _simulate_symbol(
            symbol=symbol,
            bars=working_bars,
            indicators=indicators,
            strategy=strategy,
            params=params,
            equity_cell=equity,
            trades=trades,
            equity_curve=equity_curve,
        )

    return _build_result(strategy.name, trades, equity_curve, params)


def _precompute_indicators(bars: list[list]) -> dict:
    """Placeholder — filled in Task 5 once strategies are concrete."""
    return {}


def _simulate_symbol(
    *,
    symbol: str,
    bars: list[list],
    indicators: dict,
    strategy: Strategy,
    params: EngineParams,
    equity_cell: list[float],
    trades: list,
    equity_curve: list[float],
) -> None:
    """Per-symbol simulation. In the skeleton, only handles HOLD.

    Task 5 adds open_long / exit_long.
    Task 6 adds open_short / exit_short / flip.
    """
    for i in range(1, len(bars)):
        # Skeleton: consult strategy but never act (HOLD-only test coverage).
        _ = strategy.generate_signal(
            bar_index=i,
            candles=bars,
            indicators=indicators,
            position_state="flat",
        )
        # Mark-to-market equity (no open position → unchanged)
        equity_curve.append(equity_cell[0])


def _build_result(
    strategy_name: str,
    trades: list[dict],
    equity_curve: list[float],
    params: EngineParams,
) -> BacktestResult:
    final_equity = equity_curve[-1] if equity_curve else params.initial_equity
    total_pnl = final_equity - params.initial_equity
    return_pct = total_pnl / params.initial_equity * 100.0
    wins = sum(1 for t in trades if t.get("net_pnl", 0) > 0)
    win_rate = wins / len(trades) if trades else 0.0

    reasons: dict[str, int] = {}
    for t in trades:
        r = t.get("reason", "UNKNOWN")
        reasons[r] = reasons.get(r, 0) + 1

    per_sym: dict[str, dict[str, Any]] = {}
    for t in trades:
        sym = t.get("symbol", "UNKNOWN")
        d = per_sym.setdefault(sym, {"trades": 0, "wins": 0, "net_pnl": 0.0})
        d["trades"] += 1
        if t.get("net_pnl", 0) > 0:
            d["wins"] += 1
        d["net_pnl"] += t.get("net_pnl", 0.0)

    per_q: dict[str, dict[str, Any]] = {}
    for q, q_trades in split_trades_by_quarter(trades).items():
        q_wins = sum(1 for t in q_trades if t["net_pnl"] > 0)
        per_q[q] = {
            "trades": len(q_trades),
            "wins": q_wins,
            "win_rate": q_wins / len(q_trades) if q_trades else 0.0,
            "net_pnl": sum(t["net_pnl"] for t in q_trades),
        }

    return BacktestResult(
        strategy_name=strategy_name,
        final_equity=final_equity,
        total_pnl=total_pnl,
        return_pct=return_pct,
        trades_count=len(trades),
        wins=wins,
        win_rate=win_rate,
        sharpe=sharpe_ratio(equity_curve),
        max_drawdown_pct=max_drawdown(equity_curve),
        exit_reasons=reasons,
        trades=trades,
        per_symbol=per_sym,
        per_quarter=per_q,
    )
