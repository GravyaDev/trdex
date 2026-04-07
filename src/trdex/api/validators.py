"""Shared API input validators — Annotated types for FastAPI Query/Path params."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Query

# Symbol format: BASE/QUOTE (e.g. BTC/USDT, ETH/BTC, EUR/USD)
# Allows alphanumeric + dots for stocks (e.g. BRK.B/USD)
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9.]{1,20}/[A-Z0-9]{1,10}$")

# Valid OHLCV timeframes
_VALID_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"}


# Annotated types for use in route function signatures
SymbolParam = Annotated[
    str,
    Query(
        description="Trading pair (e.g. BTC/USDT)",
        pattern=r"^[A-Z0-9.]{1,20}/[A-Z0-9]{1,10}$",
    ),
]

SymbolParamOptional = Annotated[
    str | None,
    Query(
        description="Trading pair filter (e.g. BTC/USDT)",
        pattern=r"^[A-Z0-9.]{1,20}/[A-Z0-9]{1,10}$",
    ),
]

TimeframeParam = Annotated[
    str,
    Query(
        description="Candle timeframe (1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w)",
        pattern=r"^(1m|5m|15m|30m|1h|4h|1d|1w)$",
    ),
]

LimitParam = Annotated[
    int,
    Query(
        ge=1,
        le=1000,
        description="Max number of results (1-1000)",
    ),
]

CandleLimitParam = Annotated[
    int,
    Query(
        ge=1,
        le=500,
        description="Number of candles to fetch (1-500)",
    ),
]

DaysParam = Annotated[
    int,
    Query(
        ge=1,
        le=365,
        description="Number of days (1-365)",
    ),
]
