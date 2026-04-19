"""TelegramSignalExecutor — orchestrates gate → fetch → place → persist.

Zero business logic here. This file is a sequencer:
  1. Route the symbol (may raise SymbolNotRoutable → skip).
  2. Fetch current price from the routed feed.
  3. Run all gates in order. First failure → skip with reason.
  4. Compute qty = budget / current_price.
  5. Compute SL/TP percentages relative to entry (or current if at-market).
  6. Place order via gateway. Any raise → error outcome.
  7. Persist position with source='telegram', signal_id, SL/TP pct.

Returns an ExecuteOutcome describing what happened. Callers log the
outcome; no exception propagates out of execute().
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Literal, Protocol

from trdex.execution.symbol_router import SymbolNotRoutable, route
from trdex.execution.telegram_gates import GateConfig, run_all_gates
from trdex.telegram.parser import TelegramSignal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecuteOutcome:
    """Result of attempting to execute a signal.

    status:
        - "executed" — position opened, persisted.
        - "skipped"  — a gate or the router blocked execution.
        - "error"    — gateway or persistence failed unexpectedly.
    """
    status: Literal["executed", "skipped", "error"]
    reason: str
    position_id: int | None = None


class _FeedLike(Protocol):
    name: str
    async def get_current_price(self, symbol: str) -> float: ...


class _GatewayLike(Protocol):
    async def place(
        self, *, symbol: str, direction: str, qty: float, price: float,
        idempotency_key: str | None = None,
    ) -> Any: ...


class _BalanceLike(Protocol):
    available: Decimal


class TelegramSignalExecutor:
    def __init__(
        self,
        *,
        gateway: _GatewayLike,
        feed: _FeedLike,
        portfolio_repo: Any,            # PortfolioRepository
        portfolio_service: Any,         # PortfolioService with record_open_fill
        outcome_repo: Any,              # SignalOutcomeRepository
        balance_provider: Callable[[], _BalanceLike],
        config: GateConfig,
    ) -> None:
        self._gateway = gateway
        self._feed = feed
        self._portfolio_repo = portfolio_repo
        self._portfolio_service = portfolio_service
        self._outcome_repo = outcome_repo
        self._balance_provider = balance_provider
        self._config = config

    async def execute(self, signal: TelegramSignal, *, outcome_id: int) -> ExecuteOutcome:
        # 1. Route
        try:
            feed, gateway = route(signal.symbol, feed=self._feed, gateway=self._gateway)
        except SymbolNotRoutable as exc:
            logger.info("[telegram-exec] skip %s %s: not routable — %s",
                        signal.direction, signal.symbol, exc)
            return ExecuteOutcome(status="skipped", reason=f"symbol not routable: {exc}")

        # 2. Fetch price
        try:
            current_price = await feed.get_current_price(signal.symbol)
        except Exception as exc:
            logger.exception("[telegram-exec] price fetch failed for %s", signal.symbol)
            return ExecuteOutcome(status="error", reason=f"price fetch failed: {exc}")

        # 3. Gates
        gate_result = await run_all_gates(
            signal,
            current_price=current_price,
            portfolio_repo=self._portfolio_repo,
            outcome_repo=self._outcome_repo,
            balance=self._balance_provider(),
            config=self._config,
        )
        if not gate_result.passed:
            logger.info("[telegram-exec] skip %s %s from %s: %s",
                        signal.direction, signal.symbol, signal.source, gate_result.reason)
            return ExecuteOutcome(status="skipped", reason=gate_result.reason)

        # 4. Sizing
        qty = float(self._config.budget) / current_price

        # 5. SL/TP percentages — always positive, relative to entry price.
        # StopLossMonitor reads pos.stop_loss_pct / pos.take_profit_pct and
        # applies them by side. A SELL with sl=90000→92700 (+3%) produces
        # the same 0.03 percent as a BUY with sl=92000→89240 (-3%).
        reference_price = signal.entry if signal.entry is not None else current_price
        stop_loss_pct = (
            abs(signal.stop_loss - reference_price) / reference_price
            if signal.stop_loss is not None else None
        )
        take_profit_pct = (
            abs(signal.targets[0] - reference_price) / reference_price
            if signal.targets else None
        )

        # 6. Place order
        try:
            order_result = await gateway.place(
                symbol=signal.symbol,
                direction=signal.direction,
                qty=qty,
                price=current_price,
                idempotency_key=f"telegram:{outcome_id}",
            )
        except Exception as exc:
            logger.exception("[telegram-exec] gateway failed for %s %s",
                             signal.direction, signal.symbol)
            return ExecuteOutcome(status="error", reason=f"gateway error: {exc}")

        if getattr(order_result, "status", "filled") != "filled":
            msg = getattr(order_result, "message", "unknown rejection")
            logger.warning("[telegram-exec] order rejected for %s %s: %s",
                           signal.direction, signal.symbol, msg)
            return ExecuteOutcome(status="error", reason=f"order rejected: {msg}")

        # 7. Persist position
        try:
            position = await self._portfolio_service.record_open_fill(
                symbol=signal.symbol,
                side=signal.direction,
                entry_price=Decimal(str(order_result.filled_price)),
                amount=Decimal(str(order_result.filled_qty)),
                budget=self._config.budget,
                fee=Decimal(str(getattr(order_result, "fee", 0.0))),
                source="telegram",
                signal_id=str(outcome_id),
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
            )
        except Exception as exc:
            logger.exception("[telegram-exec] persistence failed after fill")
            return ExecuteOutcome(status="error", reason=f"persistence failed: {exc}")

        logger.info("[telegram-exec] executed %s %s qty=%.6f from %s (pos=%s)",
                    signal.direction, signal.symbol, qty, signal.source, position.id)
        return ExecuteOutcome(status="executed", reason="", position_id=position.id)
