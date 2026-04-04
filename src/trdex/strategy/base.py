"""Abstract base class for trading strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trdex.market.models import OHLCV
    from trdex.strategy.models import Signal, StrategyConfig


class Strategy(ABC):
    """Base interface for all trading strategies.

    Each strategy evaluates a window of candles and optionally
    produces a Signal (BUY/SELL). Configuration is via a typed
    Pydantic StrategyConfig subclass.
    """

    @abstractmethod
    async def evaluate(self, candles: list[OHLCV]) -> Signal | None:
        """Evaluate candles and return a signal, or None if no action."""
        ...

    @abstractmethod
    def configure(self, config: StrategyConfig) -> None:
        """Apply typed configuration."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy identifier."""
        ...
