"""Execution gateway — routes orders to simulator or live executor."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trdex.execution.models import ExecutionResult, Order


class ExecutionGateway(ABC):
    """Abstract gateway for low-level order execution (Simulator, LiveExecutor)."""

    @abstractmethod
    async def execute(self, order: Order) -> ExecutionResult:
        """Execute a low-level Order and return a raw ExecutionResult."""
        ...

    @abstractmethod
    async def cancel(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if cancelled."""
        ...
