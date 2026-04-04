"""SMA Crossover strategy — simple example.

BUY when short SMA crosses above long SMA.
SELL when short SMA crosses below long SMA.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import Field

from trdex.strategy.base import Strategy
from trdex.strategy.models import Signal, SignalAction, StrategyConfig

if TYPE_CHECKING:
    from trdex.market.models import OHLCV


class SMACrossConfig(StrategyConfig):
    """Configuration for SMA Crossover strategy."""

    short_period: int = Field(default=10, gt=0)
    long_period: int = Field(default=30, gt=0)
    min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)


class SMACrossStrategy(Strategy):
    """Simple Moving Average crossover strategy."""

    def __init__(self) -> None:
        self._config = SMACrossConfig(name="sma_cross")

    def configure(self, config: StrategyConfig) -> None:
        if isinstance(config, SMACrossConfig):
            self._config = config

    @property
    def name(self) -> str:
        return "sma_cross"

    async def evaluate(self, candles: list[OHLCV]) -> Signal | None:
        if len(candles) < self._config.long_period + 1:
            return None

        closes = [float(c.close) for c in candles]

        # Current SMAs
        short_sma = sum(closes[-self._config.short_period :]) / self._config.short_period
        long_sma = sum(closes[-self._config.long_period :]) / self._config.long_period

        # Previous SMAs (one candle back)
        prev_closes = closes[:-1]
        prev_short = sum(prev_closes[-self._config.short_period :]) / self._config.short_period
        prev_long = sum(prev_closes[-self._config.long_period :]) / self._config.long_period

        # Detect crossover
        if prev_short <= prev_long and short_sma > long_sma:
            return Signal(
                action=SignalAction.BUY,
                symbol=self._config.symbols[0] if self._config.symbols else "BTC/USDT",
                confidence=self._config.min_confidence,
                reason=f"SMA{self._config.short_period} crossed above SMA{self._config.long_period}",
                timestamp=datetime.now(UTC),
            )

        if prev_short >= prev_long and short_sma < long_sma:
            return Signal(
                action=SignalAction.SELL,
                symbol=self._config.symbols[0] if self._config.symbols else "BTC/USDT",
                confidence=self._config.min_confidence,
                reason=f"SMA{self._config.short_period} crossed below SMA{self._config.long_period}",
                timestamp=datetime.now(UTC),
            )

        return None
