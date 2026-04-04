"""Execution models — orders and results."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class Order(BaseModel):
    """Order to be executed (simulation or live)."""

    symbol: str
    side: Side
    type: OrderType
    amount: Decimal
    price: Decimal | None = None  # None for market orders


class ExecutionResult(BaseModel):
    """Result of an executed order."""

    order_id: str
    symbol: str
    side: Side
    filled_amount: Decimal
    filled_price: Decimal
    fee: Decimal
    timestamp: datetime
    simulated: bool  # True = paper trading
