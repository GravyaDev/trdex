"""Market data models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class Ticker(BaseModel):
    """Real-time price for a single symbol."""

    symbol: str
    price: Decimal
    timestamp: datetime
    source: str = Field(description="Feed source identifier (e.g. 'binance', 'coingecko')")


class OHLCV(BaseModel):
    """Single candlestick data point."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class OrderBookEntry(BaseModel):
    """Single level in the order book."""

    price: Decimal
    amount: Decimal


class OrderBook(BaseModel):
    """Order book snapshot."""

    symbol: str
    bids: list[OrderBookEntry] = Field(default_factory=list)
    asks: list[OrderBookEntry] = Field(default_factory=list)
    timestamp: datetime
    source: str
