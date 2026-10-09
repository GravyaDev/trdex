"""Fetch 5 years of 1h Binance OHLCV for the 10 live symbols; cache locally.

Idempotent: if a cache file exists and its tail is within 24h of now,
fetch is skipped. Otherwise, tail is updated append-only.

Run:
    .venv/Scripts/python.exe scripts/backtest/fetch_ohlcv.py
"""

from __future__ import annotations

import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ccxt


SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "POL/USDT", "ATOM/USDT",
]
LOOKBACK_DAYS = 1825  # 5 years
TIMEFRAME = "1h"
DATA_DIR = Path(__file__).parent.parent / "data" / "ohlcv_5y"


def _cache_path(symbol: str) -> Path:
    return DATA_DIR / f"{symbol.replace('/', '_')}_{TIMEFRAME}_5y.csv"


def _fetch_range(ex: ccxt.binance, symbol: str, since_ms: int, until_ms: int) -> list:
    out = []
    cursor = since_ms
    while cursor < until_ms:
        batch = ex.fetch_ohlcv(symbol, TIMEFRAME, since=cursor, limit=1000)
        if not batch:
            break
        for row in batch:
            if row[0] <= until_ms:
                out.append(row)
        last_t = batch[-1][0]
        if last_t >= until_ms or len(batch) < 2:
            break
        cursor = last_t + 3_600_000
    return out


def _load_cache(path: Path) -> list:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        return [
            [int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])]
            for r in reader
        ]


def _write_cache(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for r in rows:
            w.writerow(r)


def fetch_symbol(ex: ccxt.binance, symbol: str, until_ms: int) -> int:
    """Return number of bars now cached for the symbol."""
    path = _cache_path(symbol)
    since_ms = until_ms - LOOKBACK_DAYS * 86_400_000
    if path.exists():
        existing = _load_cache(path)
        if existing and existing[-1][0] >= until_ms - 86_400_000:
            return len(existing)  # fresh enough, skip
        # Append-only top-up
        cursor = existing[-1][0] + 3_600_000 if existing else since_ms
        new_rows = _fetch_range(ex, symbol, cursor, until_ms)
        merged = existing + new_rows
        _write_cache(path, merged)
        return len(merged)
    # Full fetch
    rows = _fetch_range(ex, symbol, since_ms, until_ms)
    _write_cache(path, rows)
    return len(rows)


def main() -> None:
    until = datetime.now(tz=timezone.utc).replace(minute=0, second=0, microsecond=0)
    until_ms = int(until.timestamp() * 1000)
    ex = ccxt.binance({"enableRateLimit": True})
    print(f"Fetching {len(SYMBOLS)} symbols, {LOOKBACK_DAYS}d lookback, {TIMEFRAME}")
    start = time.monotonic()
    for sym in SYMBOLS:
        n = fetch_symbol(ex, sym, until_ms)
        print(f"  {sym:10} -> {n:>6} bars")
    print(f"Done in {time.monotonic() - start:.1f}s")


if __name__ == "__main__":
    main()
