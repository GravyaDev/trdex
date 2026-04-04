"""Strategy models — signals and configuration."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class SignalAction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class Signal(BaseModel):
    """Trading signal produced by a strategy."""

    action: SignalAction
    symbol: str
    confidence: float = Field(ge=0.0, le=1.0, description="Signal confidence 0-1")
    reason: str
    timestamp: datetime


class StrategyConfig(BaseModel):
    """Base config for strategies. Subclass for per-strategy params."""

    name: str
    symbols: list[str] = Field(default_factory=list)
    timeframe: str = "1h"
    enabled: bool = True
