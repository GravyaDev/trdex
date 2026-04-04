"""Portfolio models — positions, holdings, and risk metrics."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class Position(BaseModel):
    """Open position in a single asset."""

    symbol: str
    side: str  # "long" or "short"
    entry_price: Decimal
    amount: Decimal
    current_price: Decimal = Decimal("0")
    opened_at: datetime

    @property
    def unrealized_pnl(self) -> Decimal:
        if self.side == "long":
            return (self.current_price - self.entry_price) * self.amount
        return (self.entry_price - self.current_price) * self.amount

    @property
    def unrealized_pnl_pct(self) -> Decimal:
        if self.entry_price == 0:
            return Decimal("0")
        return self.unrealized_pnl / (self.entry_price * self.amount)


class Portfolio(BaseModel):
    """Portfolio state snapshot."""

    balance: Decimal = Field(default=Decimal("10000"), description="Cash balance")
    positions: list[Position] = Field(default_factory=list)
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl: Decimal = Decimal("0")

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def equity(self) -> Decimal:
        unrealized = sum(p.unrealized_pnl for p in self.positions)
        return self.balance + unrealized
