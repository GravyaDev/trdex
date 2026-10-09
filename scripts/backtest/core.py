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

from trdex.risk.sizing import risk_position_fraction


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
    equity_curve: list[float] = field(default_factory=list)


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
    """Split trades into four equal sub-periods ("quarters" of the sample).

    The buckets span oldest → newest entry_ts, so every bucket covers a
    quarter of the tested period whatever its length. (The previous
    version used fixed 91-day buckets and put everything after day 273
    into Q4 — on 5 years of data Q4 held ~85% of the trades.)

    Returns empty dict for empty input. Trades missing 'entry_ts' are skipped.
    """
    dated = [t for t in trades if "entry_ts" in t]
    if not dated:
        return {}
    sorted_trades = sorted(dated, key=lambda t: t["entry_ts"])
    first_ts = sorted_trades[0]["entry_ts"]
    span = sorted_trades[-1]["entry_ts"] - first_ts + 1
    buckets: dict[str, list[dict]] = {f"Q{i + 1}": [] for i in range(4)}
    for t in sorted_trades:
        q = min(3, (t["entry_ts"] - first_ts) * 4 // span)
        buckets[f"Q{int(q) + 1}"].append(t)
    return buckets


from typing import Literal, Protocol
from scripts.backtest.indicators import (
    bollinger_bands,
    is_squeezing,
    sma,
    volume_ma,
    wilder_rsi,
)


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
    # Risk-based sizing (same rule as the live Risk node): commit
    # risk_per_trade_pct / stop of equity, capped at position_size_pct.
    # None = fixed notional sizing at position_size_pct.
    risk_per_trade_pct: float | None = None


_BARS_PER_YEAR = {"1h": 8760, "1d": 365}


@dataclass
class _Account:
    """Shared cash account. ``committed`` is the budget locked in open positions."""

    cash: float
    committed: float = 0.0


@dataclass
class _SymbolState:
    symbol: str
    bars: list[list]
    indicators: dict
    position_state: str = "flat"
    entry_price: float = 0.0
    entry_qty: float = 0.0
    entry_ts: int = 0
    budget: float = 0.0
    extreme: float = 0.0        # best price seen since entry (high for long, low for short)
    stop: float = 0.0           # current stop (initial, then trailed)
    initial_stop: float = 0.0
    tp_pct: float = 0.0
    trail_pct: float = 0.0
    last_close: float | None = None


def run_backtest(
    strategy: Strategy,
    ohlcv_by_symbol: dict[str, list[list]],
    params: EngineParams,
) -> BacktestResult:
    """Run the strategy across all symbols on ONE shared timeline.

    Bars of every symbol are merged by timestamp and processed in time
    order (symbols in dict order within a timestamp), so positions on
    different symbols are open at the same time and share one account.
    One equity point is recorded per timestamp. Positions still open at
    the end of the data are closed at the last close (reason ``"EOD"``).

    Optional strategy hooks:
      - ``sl_pct_override`` / ``tp_pct_override`` / ``trail_pct_override``
        class attributes (static exit params);
      - ``exit_pcts(bar_index, indicators, params) -> (sl, tp, trail)``
        evaluated at entry, for exits that depend on market state.
    A trail of 0 disables the trailing stop.
    """
    effective = EngineParams(
        initial_equity=params.initial_equity,
        position_size_pct=params.position_size_pct,
        fee_pct=params.fee_pct,
        sl_pct=getattr(strategy, "sl_pct_override", params.sl_pct),
        tp_pct=getattr(strategy, "tp_pct_override", params.tp_pct),
        trail_pct=getattr(strategy, "trail_pct_override", params.trail_pct),
        risk_per_trade_pct=getattr(strategy, "risk_per_trade_pct_override", params.risk_per_trade_pct),
    )
    account = _Account(cash=effective.initial_equity)
    trades: list[dict[str, Any]] = []

    states: list[_SymbolState] = []
    for symbol, bars in ohlcv_by_symbol.items():
        working = aggregate_1h_to_1d(bars) if strategy.timeframe == "1d" else bars
        states.append(_SymbolState(
            symbol=symbol, bars=working, indicators=_precompute_indicators(working),
        ))

    timeline = sorted(
        (bar[0], k, i) for k, st in enumerate(states) for i, bar in enumerate(st.bars)
    )
    equity_curve = [effective.initial_equity]
    current_ts: int | None = None
    stepped = False
    for ts, k, i in timeline:
        if ts != current_ts:
            if stepped:
                equity_curve.append(_mark_to_market(account, states))
            current_ts, stepped = ts, False
        st = states[k]
        if i >= 1:  # bar 0 has no previous bar to read a signal from
            _step(st, i, strategy, effective, account, trades)
            stepped = True
        st.last_close = st.bars[i][4]
    if stepped:
        equity_curve.append(_mark_to_market(account, states))

    # Close whatever is still open at the last available close, so its
    # budget is not silently lost from the final equity.
    closed_any = False
    for st in states:
        if st.position_state != "flat" and st.last_close is not None:
            _close(st, ts=st.bars[-1][0], exit_price=st.last_close, reason="EOD",
                   params=effective, account=account, trades=trades)
            closed_any = True
    if closed_any:
        equity_curve[-1] = account.cash  # same timestamp, exit fees deducted

    return _build_result(
        strategy.name, trades, equity_curve, effective,
        bars_per_year=_BARS_PER_YEAR.get(strategy.timeframe, 8760),
    )


def _precompute_indicators(bars: list[list]) -> dict:
    closes = [b[4] for b in bars]
    highs = [b[2] for b in bars]
    lows = [b[3] for b in bars]
    volumes = [b[5] for b in bars]
    bb_upper, bb_mid, bb_lower = bollinger_bands(closes, period=20, std_dev=2.0)

    # 4h SMA(20): aggregate 1h bars to 4h closes, compute SMA, broadcast back.
    sma20_4h = _compute_4h_sma_broadcast(bars, period=20)

    return {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
        "rsi14": wilder_rsi(closes, period=14),
        "sma9": sma(closes, 9),
        "sma21": sma(closes, 21),
        "sma50": sma(closes, 50),
        "sma20_1d": sma(closes, 20),
        "sma20_4h": sma20_4h,
        "bb_upper": bb_upper,
        "bb_mid": bb_mid,
        "bb_lower": bb_lower,
        "vol_ma24": volume_ma(volumes, period=24),
        "squeeze": is_squeezing(closes, bb_period=20, std_dev=2.0, lookback=100, pct=0.3),
    }


def _compute_4h_sma_broadcast(bars: list[list], period: int) -> list[float | None]:
    """Compute SMA(period) on 4h closes built from 1h bars, broadcast to each 1h bar.

    1h bar i belongs to the 4h window ending at the last-completed 4h close.
    We use the last completed 4h close so the value at bar i does not peek into
    the future of its own 4h window.
    """
    n = len(bars)
    out: list[float | None] = [None] * n
    # Group bars into 4h chunks (4 consecutive 1h bars each).
    # A 4h bar completes at bar index (k+1)*4 - 1.
    # For 1h bar i, the "last completed 4h close" is bars[((i // 4)) * 4 - 1] if i >= 4.
    fourh_closes: list[float] = []
    for k in range(n // 4):
        end_idx = (k + 1) * 4 - 1
        fourh_closes.append(bars[end_idx][4])
    sma_4h = sma(fourh_closes, period)
    for i in range(n):
        # Index into sma_4h based on how many completed 4h chunks are visible at bar i.
        completed = i // 4
        if completed == 0:
            out[i] = None
        else:
            idx = completed - 1
            out[i] = sma_4h[idx] if idx < len(sma_4h) else None
    return out


def _step(
    st: _SymbolState,
    i: int,
    strategy: Strategy,
    params: EngineParams,
    account: _Account,
    trades: list,
) -> None:
    ts, o, h, l, _c, _v = st.bars[i]

    # 1) Exits for a position carried into this bar (gap-aware).
    exited_intrabar = False
    if st.position_state != "flat":
        exited_intrabar = _check_exits(st, ts, o, h, l, params, account, trades)

    # 2) Strategy reads data up to bar i-1 and acts at bar i's open.
    sig = strategy.generate_signal(
        bar_index=i,
        candles=st.bars,
        indicators=st.indicators,
        position_state=st.position_state,
    )

    # 3) Execute at the open. No re-entry on a bar where a stop/target
    # already closed the position intrabar: the open precedes that exit.
    opened = False
    if sig == "BUY":
        if st.position_state == "short":
            _close(st, ts, o, "FLIP", params, account, trades)
        if st.position_state == "flat" and not exited_intrabar:
            _open(st, "long", o, ts, strategy, i, params, account)
            opened = True
    elif sig == "SELL":
        if st.position_state == "long":
            _close(st, ts, o, "FLIP", params, account, trades)
        if st.position_state == "flat" and not exited_intrabar:
            _open(st, "short", o, ts, strategy, i, params, account)
            opened = True
    elif sig == "CLOSE_LONG" and st.position_state == "long":
        _close(st, ts, o, "SIGNAL", params, account, trades)
    elif sig == "CLOSE_SHORT" and st.position_state == "short":
        _close(st, ts, o, "SIGNAL", params, account, trades)

    # 4) A position opened at the open lives through the rest of this bar.
    if opened:
        _check_exits(st, ts, o, h, l, params, account, trades)


def _check_exits(st, ts, o, h, l, params, account, trades) -> bool:
    """Stop (initial or trailed) first, then take-profit, then trail update.

    Returns True if the position was closed. A gap through the stop fills
    at the open, not at the stop price.
    """
    if st.position_state == "long":
        if l <= st.stop:
            reason = "TRAIL" if st.stop > st.initial_stop else "SL"
            _close(st, ts, min(o, st.stop), reason, params, account, trades)
            return True
        tp_price = st.entry_price * (1 + st.tp_pct)
        if h >= tp_price:
            _close(st, ts, tp_price, "TP", params, account, trades)
            return True
        if st.trail_pct > 0 and h > st.extreme:
            st.extreme = h
            st.stop = max(st.stop, h * (1 - st.trail_pct))
        return False

    if st.position_state == "short":
        if h >= st.stop:
            reason = "TRAIL" if st.stop < st.initial_stop else "SL"
            _close(st, ts, max(o, st.stop), reason, params, account, trades)
            return True
        tp_price = st.entry_price * (1 - st.tp_pct)
        if l <= tp_price:
            _close(st, ts, tp_price, "TP", params, account, trades)
            return True
        if st.trail_pct > 0 and l < st.extreme:
            st.extreme = l
            st.stop = min(st.stop, l * (1 + st.trail_pct))
        return False

    return False


def _open(st, side, o, ts, strategy, i, params, account) -> None:
    sl, tp, trail = params.sl_pct, params.tp_pct, params.trail_pct
    hook = getattr(strategy, "exit_pcts", None)
    if hook is not None:
        sl, tp, trail = hook(bar_index=i, indicators=st.indicators, params=params)
    fraction = params.position_size_pct
    if params.risk_per_trade_pct is not None:
        fraction = risk_position_fraction(
            risk_per_trade=params.risk_per_trade_pct,
            stop_pct=sl,
            max_fraction=params.position_size_pct,
        )
    # Size on realised equity (cash + budget locked in open positions),
    # like the live executor sizes on portfolio equity.
    budget = (account.cash + account.committed) * fraction
    account.cash -= budget
    account.committed += budget
    st.position_state = side
    st.entry_price = o
    st.entry_qty = (budget / o) * (1 - params.fee_pct)
    st.entry_ts = ts
    st.budget = budget
    st.tp_pct = tp
    st.trail_pct = trail
    st.extreme = o
    st.initial_stop = o * (1 - sl) if side == "long" else o * (1 + sl)
    st.stop = st.initial_stop


def _close(st, ts, exit_price, reason, params, account, trades) -> None:
    qty, entry = st.entry_qty, st.entry_price
    exit_fee = qty * exit_price * params.fee_pct
    if st.position_state == "long":
        proceeds = qty * exit_price - exit_fee
    else:
        proceeds = qty * entry + (entry - exit_price) * qty - exit_fee
    account.cash += proceeds
    account.committed -= st.budget
    trades.append({
        "symbol": st.symbol,
        "side": st.position_state,
        "entry_ts": st.entry_ts,
        "exit_ts": ts,
        "entry_price": entry,
        "exit_price": exit_price,
        "qty": qty,
        # Cash P&L of the round trip: includes BOTH fees (the entry fee is
        # the budget not converted into qty), so per-symbol/quarter sums
        # and win rate match the change in equity.
        "net_pnl": proceeds - st.budget,
        "reason": reason,
    })
    st.position_state = "flat"
    st.budget = 0.0


def _mark_to_market(account: _Account, states: list[_SymbolState]) -> float:
    equity = account.cash
    for st in states:
        if st.position_state == "flat" or st.last_close is None:
            continue
        if st.position_state == "long":
            equity += st.entry_qty * st.last_close
        else:  # short: collateral returned + P&L (the old curve forgot the collateral)
            equity += st.entry_qty * st.entry_price + (st.entry_price - st.last_close) * st.entry_qty
    return equity


def _build_result(
    strategy_name: str,
    trades: list[dict],
    equity_curve: list[float],
    params: EngineParams,
    bars_per_year: int = 8760,
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
        sharpe=sharpe_ratio(equity_curve, bars_per_year=bars_per_year),
        max_drawdown_pct=max_drawdown(equity_curve),
        exit_reasons=reasons,
        trades=trades,
        per_symbol=per_sym,
        per_quarter=per_q,
        equity_curve=equity_curve,
    )
