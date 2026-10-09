"""Run all strategies on cached 5y OHLCV; print comparison table; save CSV.

Prereq: run scripts/backtest/fetch_ohlcv.py once to populate
scripts/data/ohlcv_5y/.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from scripts.backtest.core import EngineParams, BacktestResult, run_backtest
from scripts.backtest.strategies import (
    BaselineInverse,
    BaselineLive,
    BollingerSqueezeBreakout,
    BreakoutVolume,
    MeanReversionRSI,
    MultiTimeframeConfirm,
    PullbackInUptrend,
    SwingDailyTrend,
    TimeFilterLive,
    ZanniLikeScalp,
)

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "POL/USDT", "ATOM/USDT",
]
DATA_DIR = Path(__file__).parent.parent / "data" / "ohlcv_5y"
RESULTS_DIR = Path(__file__).parent.parent / "data"


def _load_cache(symbol: str) -> list:
    path = DATA_DIR / f"{symbol.replace('/', '_')}_1h_5y.csv"
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        return [
            [int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
            for r in reader
        ]


def _format_quarter_cell(q_data: dict | None) -> str:
    if not q_data:
        return "    n/a"
    return f"${q_data['net_pnl']:>+7.0f}"


def _print_table(results: list[BacktestResult]) -> None:
    print(f"\n{'Strategy':24} {'Trades':>7} {'Win%':>6} {'P&L':>11} {'Sharpe':>7} {'MaxDD':>7}  {'Q1':>9} {'Q2':>9} {'Q3':>9} {'Q4':>9}")
    print("-" * 120)
    for r in results:
        q = r.per_quarter
        print(
            f"{r.strategy_name:24} "
            f"{r.trades_count:>7} "
            f"{r.win_rate * 100:>5.1f}% "
            f"${r.total_pnl:>+9.2f} "
            f"{r.sharpe:>7.2f} "
            f"{r.max_drawdown_pct:>6.1f}%  "
            f"{_format_quarter_cell(q.get('Q1')):>9} "
            f"{_format_quarter_cell(q.get('Q2')):>9} "
            f"{_format_quarter_cell(q.get('Q3')):>9} "
            f"{_format_quarter_cell(q.get('Q4')):>9}"
        )


def _save_results_csv(results: list[BacktestResult]) -> Path:
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H%M%S")
    out = RESULTS_DIR / f"backtest_results_{ts}.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "strategy", "trades", "wins", "win_rate", "total_pnl",
            "return_pct", "sharpe", "max_drawdown_pct", "final_equity",
            "q1_pnl", "q2_pnl", "q3_pnl", "q4_pnl",
        ])
        for r in results:
            q = r.per_quarter
            w.writerow([
                r.strategy_name, r.trades_count, r.wins, r.win_rate,
                r.total_pnl, r.return_pct, r.sharpe, r.max_drawdown_pct, r.final_equity,
                q.get("Q1", {}).get("net_pnl", 0),
                q.get("Q2", {}).get("net_pnl", 0),
                q.get("Q3", {}).get("net_pnl", 0),
                q.get("Q4", {}).get("net_pnl", 0),
            ])
    return out


def main() -> None:
    print("Loading OHLCV cache...")
    ohlcv = {sym: _load_cache(sym) for sym in SYMBOLS}
    total_bars = sum(len(v) for v in ohlcv.values())
    print(f"Loaded {total_bars} bars across {len(SYMBOLS)} symbols")

    strategies = [
        BaselineLive(),
        BaselineInverse(),
        MeanReversionRSI(),
        MultiTimeframeConfirm(),
        BreakoutVolume(),
        BollingerSqueezeBreakout(),
        TimeFilterLive(),
        PullbackInUptrend(),
        ZanniLikeScalp(),
        SwingDailyTrend(),
    ]

    params = EngineParams()
    results: list[BacktestResult] = []
    for s in strategies:
        print(f"  running {s.name}...")
        r = run_backtest(s, ohlcv, params)
        results.append(r)

    # Sort by total_pnl desc
    results.sort(key=lambda r: r.total_pnl, reverse=True)
    _print_table(results)

    out = _save_results_csv(results)
    print(f"\nResults CSV: {out}")

    # Top 3 best + top 3 worst, per-symbol breakdown
    print("\n=== TOP 3 BEST — per-symbol breakdown ===")
    for r in results[:3]:
        print(f"\n{r.strategy_name}  (total ${r.total_pnl:+.2f})")
        for sym, d in sorted(r.per_symbol.items(), key=lambda kv: kv[1]["net_pnl"], reverse=True):
            wr = d["wins"] / d["trades"] * 100 if d["trades"] else 0
            print(f"  {sym:10} {d['trades']:>4} trades {wr:>5.1f}% win ${d['net_pnl']:>+8.2f}")

    print("\n=== TOP 3 WORST — per-symbol breakdown ===")
    for r in results[-3:]:
        print(f"\n{r.strategy_name}  (total ${r.total_pnl:+.2f})")
        for sym, d in sorted(r.per_symbol.items(), key=lambda kv: kv[1]["net_pnl"]):
            wr = d["wins"] / d["trades"] * 100 if d["trades"] else 0
            print(f"  {sym:10} {d['trades']:>4} trades {wr:>5.1f}% win ${d['net_pnl']:>+8.2f}")


if __name__ == "__main__":
    main()
