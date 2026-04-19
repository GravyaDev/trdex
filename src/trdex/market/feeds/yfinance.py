"""Yahoo Finance feed for forex, commodities, and indices OHLCV.

Uses the `yfinance` library (already a project dependency) to fetch
historical candles for symbols that Binance and other crypto feeds
do not support: XAU/USD (gold), GBP/NZD, NAS100, US30, etc.

This feed is registered as a fallback in the PriceFeedManager so
the evaluator can score Telegram signals on non-crypto pairs.

Symbol mapping:
  XAU/USD  → GC=F      (gold futures)
  XAG/USD  → SI=F      (silver futures)
  WTI/USD  → CL=F      (crude oil futures)
  BRENT/USD → BZ=F     (Brent crude futures)
  NATGAS/USD → NG=F    (natural gas futures)
  EUR/USD  → EURUSD=X  (forex)
  GBP/NZD  → GBPNZD=X (forex)
  NAS100/USD → NQ=F    (Nasdaq futures)
  US30/USD → YM=F      (Dow futures)
  SPX500/USD → ES=F    (S&P futures)
  GER40/EUR → ^GDAXI   (DAX index)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from trdex.market.feeds.base import PriceFeed
from trdex.market.models import OHLCV, Ticker

logger = logging.getLogger(__name__)

# Maps our normalized symbol → yfinance ticker.
_SYMBOL_MAP: dict[str, str] = {
    # Commodities
    "XAU/USD": "GC=F",
    "XAG/USD": "SI=F",
    "WTI/USD": "CL=F",
    "BRENT/USD": "BZ=F",
    "NATGAS/USD": "NG=F",
    # Indices
    "NAS100/USD": "NQ=F",
    "US30/USD": "YM=F",
    "SPX500/USD": "ES=F",
    "GER40/EUR": "^GDAXI",
    "UK100/GBP": "^FTSE",
}

# Fiat currencies that appear as the quote side of a Forex pair.
# A symbol whose quote is NOT in this set is treated as crypto (or other
# non-Forex) and skipped by supports_symbol — avoids yfinance producing
# "possibly delisted" noise for e.g. LINK/USDT → LINKUSDT=X.
_FIAT_QUOTES: frozenset[str] = frozenset({
    "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD",
    "SEK", "NOK", "DKK", "HKD", "SGD", "MXN", "ZAR", "CNY",
    "PLN", "TRY", "CZK", "HUF",
})

# Timeframe map: our standard → yfinance interval
_TIMEFRAME_MAP: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "1h",  # yfinance doesn't have 4h — use 1h and caller aggregates
    "1d": "1d",
}


def _to_yf_ticker(symbol: str) -> str:
    """Convert our normalized symbol to a yfinance ticker.

    Explicit map for commodities/indices, auto-convert for forex
    pairs: EUR/USD → EURUSD=X.
    """
    if symbol in _SYMBOL_MAP:
        return _SYMBOL_MAP[symbol]
    # Forex pair: EUR/USD → EURUSD=X
    base_quote = symbol.replace("/", "")
    return f"{base_quote}=X"


class YFinanceFeed(PriceFeed):
    """Yahoo Finance feed — forex, commodities, indices.

    No API key required. Rate limits are generous (~2000 req/hour)
    but responses are slower than dedicated APIs (~500ms-2s per call).
    Best used as a fallback when no specialized feed is available.
    """

    @property
    def name(self) -> str:
        return "yfinance"

    def supports_symbol(self, symbol: str) -> bool:
        """True only for explicit commodities/indices or Forex pairs with
        a fiat quote. Crypto symbols (quote in USDT, BTC, etc.) are
        skipped so the cascade does not log "possibly delisted" noise
        for every crypto tick handed through this fallback feed.
        """
        if symbol in _SYMBOL_MAP:
            return True
        if "/" not in symbol:
            return False
        quote = symbol.split("/", 1)[1].upper()
        return quote in _FIAT_QUOTES

    async def get_ticker(self, symbol: str) -> Ticker:
        """Get current price via yfinance fast_info."""
        import asyncio
        import yfinance as yf

        ticker_id = _to_yf_ticker(symbol)

        def _fetch():
            t = yf.Ticker(ticker_id)
            price = t.fast_info.get("lastPrice") or t.fast_info.get("last_price", 0)
            return float(price)

        try:
            price = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(None, _fetch),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            raise ValueError(f"yfinance ticker timeout for {symbol} ({ticker_id})")
        if not price or price <= 0:
            raise ValueError(f"yfinance returned no price for {symbol} ({ticker_id})")

        return Ticker(
            symbol=symbol,
            price=Decimal(str(price)),
            timestamp=datetime.now(tz=timezone.utc),
            source=self.name,
        )

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 100,
        since: int | None = None,
    ) -> list[OHLCV]:
        """Fetch historical candles via yfinance.

        yfinance is synchronous — runs in a thread executor to avoid
        blocking the event loop.
        """
        import asyncio
        import yfinance as yf

        ticker_id = _to_yf_ticker(symbol)
        interval = _TIMEFRAME_MAP.get(timeframe, "5m")
        logger.info("[yfinance] fetching OHLCV %s → %s interval=%s", symbol, ticker_id, interval)

        # yfinance uses 'period' (e.g. "5d") or 'start'/'end'.
        # For the evaluator we need recent data. Map limit to a
        # reasonable period.
        if interval in ("1m", "5m"):
            period = "5d"  # max for intraday 1m/5m
        elif interval in ("15m", "30m"):
            period = "30d"
        elif interval == "1h":
            period = "60d"
        else:
            period = "60d"

        def _fetch():
            t = yf.Ticker(ticker_id)
            df = t.history(period=period, interval=interval)
            return df

        try:
            df = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(None, _fetch),
                timeout=30.0,  # yfinance can hang on first call in containers
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[yfinance] TIMEOUT fetching OHLCV for %s (%s) — 30s exceeded",
                symbol, ticker_id,
            )
            raise ValueError(f"yfinance timeout for {symbol} ({ticker_id})")
        except Exception as exc:
            logger.warning(
                "[yfinance] failed to fetch OHLCV for %s (%s): %s",
                symbol, ticker_id, exc,
            )
            raise

        if df is None or df.empty:
            raise ValueError(f"yfinance returned no data for {symbol} ({ticker_id})")

        candles: list[OHLCV] = []
        for ts, row in df.iterrows():
            dt = ts.to_pydatetime()
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            candles.append(OHLCV(
                timestamp=dt,
                open=Decimal(str(row["Open"])),
                high=Decimal(str(row["High"])),
                low=Decimal(str(row["Low"])),
                close=Decimal(str(row["Close"])),
                volume=Decimal(str(row.get("Volume", 0))),
            ))

        # Apply since filter if provided
        if since is not None:
            since_dt = datetime.fromtimestamp(since / 1000, tz=timezone.utc)
            candles = [c for c in candles if c.timestamp >= since_dt]

        # Apply limit
        candles = candles[-limit:]

        logger.debug(
            "[yfinance] %s (%s) → %d candles, interval=%s",
            symbol, ticker_id, len(candles), interval,
        )
        return candles

    async def subscribe_ticker(
        self, symbol: str, callback: Callable[[Ticker], Any],
    ) -> None:
        raise NotImplementedError("YFinanceFeed has no WebSocket feed.")

    async def close(self) -> None:
        pass  # yfinance uses no persistent connections
