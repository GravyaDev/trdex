"""Polars-based vectorised backtest engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import polars as pl

from trdex.backtest.indicators import add_indicators


class Strategy(Protocol):
    """Strategy interface for the backtest engine.

    A strategy receives an enriched OHLCV DataFrame and returns
    a Series of signals: 1 (BUY), -1 (SELL), 0 (HOLD).
    """

    def generate_signals(self, df: pl.DataFrame) -> pl.Series:
        """Return a Series named 'signal' with values in {-1, 0, 1}."""
        ...


@dataclass
class BacktestResult:
    """Output of a single backtest run."""

    symbol: str
    initial_capital: float
    final_capital: float
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    total_trades: int
    equity_curve: pl.Series
    trades: pl.DataFrame = field(default_factory=pl.DataFrame)


def run_backtest(
    ohlcv: pl.DataFrame,
    strategy: Strategy,
    symbol: str = "UNKNOWN",
    initial_capital: float = 10_000.0,
    position_size_pct: float = 0.02,
    fee_rate: float = 0.001,
) -> BacktestResult:
    """Run a vectorised backtest on OHLCV data.

    Args:
        ohlcv: DataFrame with columns [timestamp, open, high, low, close, volume].
        strategy: Strategy that produces signals from the enriched DataFrame.
        symbol: Trading pair label.
        initial_capital: Starting capital in quote currency.
        position_size_pct: Fraction of capital per trade.
        fee_rate: Fee per trade (both entry and exit).

    Returns:
        BacktestResult with performance metrics and equity curve.
    """
    # Enrich with indicators
    df = add_indicators(ohlcv)

    # Generate signals
    signals = strategy.generate_signals(df)
    df = df.with_columns(signals.alias("signal"))

    # Vectorised P&L simulation
    closes = df["close"].to_list()
    sigs = df["signal"].to_list()

    capital = initial_capital
    equity: list[float] = [capital]
    in_position = False
    entry_price = 0.0
    entry_qty = 0.0
    wins = losses = total_trades = 0
    trade_rows: list[dict] = []

    for i in range(1, len(closes)):
        price = closes[i]
        sig = sigs[i - 1]  # signal from previous bar → execute at this bar's open

        if sig == 1 and not in_position:
            # BUY
            cost = capital * position_size_pct
            entry_qty = (cost / price) * (1 - fee_rate)
            entry_price = price
            capital -= cost
            in_position = True

        elif sig == -1 and in_position:
            # SELL
            proceeds = entry_qty * price * (1 - fee_rate)
            pnl = proceeds - (entry_qty * entry_price)
            capital += proceeds
            in_position = False
            total_trades += 1
            (wins if pnl >= 0 else losses).__class__  # just to avoid walrus
            if pnl >= 0:
                wins += 1
            else:
                losses += 1
            trade_rows.append({
                "entry_price": entry_price,
                "exit_price": price,
                "qty": entry_qty,
                "pnl": pnl,
            })
            entry_price = 0.0
            entry_qty = 0.0

        # Mark-to-market equity
        mtm = capital + (entry_qty * price if in_position else 0.0)
        equity.append(mtm)

    final_capital = equity[-1]
    total_return_pct = (final_capital - initial_capital) / initial_capital * 100

    equity_series = pl.Series("equity", equity)
    max_drawdown_pct = _max_drawdown(equity_series)
    sharpe = _sharpe_ratio(equity_series)
    win_rate = wins / total_trades if total_trades > 0 else 0.0

    trades_df = pl.DataFrame(trade_rows) if trade_rows else pl.DataFrame(
        {"entry_price": [], "exit_price": [], "qty": [], "pnl": []}
    )

    return BacktestResult(
        symbol=symbol,
        initial_capital=initial_capital,
        final_capital=final_capital,
        total_return_pct=total_return_pct,
        sharpe_ratio=sharpe,
        max_drawdown_pct=max_drawdown_pct,
        win_rate=win_rate,
        total_trades=total_trades,
        equity_curve=equity_series,
        trades=trades_df,
    )


def _max_drawdown(equity: pl.Series) -> float:
    """Maximum peak-to-trough drawdown as a percentage."""
    values = equity.to_list()
    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _sharpe_ratio(equity: pl.Series, risk_free_rate: float = 0.0) -> float:
    """Annualised Sharpe ratio from equity curve (assumes daily bars)."""
    returns = equity.pct_change().drop_nulls()
    if len(returns) < 2:
        return 0.0
    mean_r = returns.mean() or 0.0
    std_r = returns.std() or 0.0
    if std_r == 0:
        return 0.0
    daily_sharpe = (mean_r - risk_free_rate) / std_r
    return daily_sharpe * (252 ** 0.5)  # annualise
