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
import math
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
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
        # 0. Normalise direction up-front. Defence-in-depth: TelegramSignal
        # from parse_signal() is already Literal["BUY", "SELL"], but a
        # future path that reads raw rows from signal_outcomes or an
        # external caller could pass "buy", " BUY ", etc. Normalising once
        # here guarantees the dedup gate, the gateway call, and the
        # persisted position all agree on the canonical casing.
        direction = signal.direction.strip().upper()
        if direction not in ("BUY", "SELL"):
            logger.info("[telegram-exec] skip %s %s: invalid direction %r",
                        signal.direction, signal.symbol, signal.direction)
            return ExecuteOutcome(
                status="skipped",
                reason=f"invalid direction: {signal.direction!r}",
            )
        if direction != signal.direction:
            signal = replace(signal, direction=direction)  # type: ignore[arg-type]

        # 1. Route
        try:
            feed, gateway = route(signal.symbol, feed=self._feed, gateway=self._gateway)
        except SymbolNotRoutable as exc:
            logger.info("[telegram-exec] skip %s %s: not routable — %s",
                        direction, signal.symbol, exc)
            return ExecuteOutcome(status="skipped", reason=f"symbol not routable: {exc}")

        # 2. Fetch price
        try:
            current_price = await feed.get_current_price(signal.symbol)
        except Exception as exc:
            logger.exception("[telegram-exec] price fetch failed for %s", signal.symbol)
            return ExecuteOutcome(status="error", reason=f"price fetch failed: {exc}")

        # 2b. Reject non-positive / non-finite prices BEFORE the gates and
        # sizing. Without this a stale feed returning 0.0 would raise
        # ZeroDivisionError at step 4, and a NaN would silently poison
        # drift-gate math and qty. Fail skipped with an explicit reason so
        # telemetry can distinguish this from ordinary gate skips.
        if not math.isfinite(current_price) or current_price <= 0.0:
            logger.warning("[telegram-exec] skip %s %s: invalid current_price=%r",
                           direction, signal.symbol, current_price)
            return ExecuteOutcome(
                status="skipped",
                reason=f"invalid current_price: {current_price!r}",
            )

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
                        direction, signal.symbol, signal.source, gate_result.reason)
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
                direction=direction,
                qty=qty,
                price=current_price,
                idempotency_key=f"telegram:{outcome_id}",
            )
        except Exception as exc:
            logger.exception("[telegram-exec] gateway failed for %s %s",
                             direction, signal.symbol)
            return ExecuteOutcome(status="error", reason=f"gateway error: {exc}")

        # 6b. Phantom-fill guard. A gateway that returns a result WITHOUT a
        # status attribute must NOT be treated as filled — the previous
        # default of "filled" would persist a position for an order that
        # may have been rejected, cancelled, or partially filled. Require
        # the attribute to exist and equal "filled" explicitly.
        status = getattr(order_result, "status", None)
        if status != "filled":
            msg = getattr(order_result, "message", "unknown rejection")
            logger.warning("[telegram-exec] order rejected for %s %s: status=%r msg=%s",
                           direction, signal.symbol, status, msg)
            return ExecuteOutcome(
                status="error",
                reason=f"order not filled (status={status!r}): {msg}",
            )

        # 6c. Validated fee extraction. A gateway returning NaN, inf, a
        # negative number, or a non-numeric fee must NOT be Decimal()-cast
        # blindly: that corrupts the P&L ledger and, for very large
        # values, the balance ledger. Fail the persistence step instead
        # with a clear reason; the position is not yet persisted, so the
        # fill is recorded in logs only and has to be reconciled manually.
        fee_value: Decimal
        raw_fee = getattr(order_result, "fee", Decimal("0"))
        if isinstance(raw_fee, Decimal):
            fee_value = raw_fee
        elif isinstance(raw_fee, (int, float)):
            if not math.isfinite(raw_fee):
                logger.error("[telegram-exec] rejecting non-finite fee=%r from gateway for %s %s",
                             raw_fee, direction, signal.symbol)
                return ExecuteOutcome(
                    status="error",
                    reason=f"invalid fee from gateway: {raw_fee!r}",
                )
            fee_value = Decimal(str(raw_fee))
        else:
            try:
                fee_value = Decimal(str(raw_fee))
            except (InvalidOperation, ValueError, TypeError):
                logger.error("[telegram-exec] rejecting non-numeric fee=%r from gateway for %s %s",
                             raw_fee, direction, signal.symbol)
                return ExecuteOutcome(
                    status="error",
                    reason=f"invalid fee from gateway: {raw_fee!r}",
                )
        if fee_value < 0:
            logger.error("[telegram-exec] rejecting negative fee=%s from gateway for %s %s",
                         fee_value, direction, signal.symbol)
            return ExecuteOutcome(
                status="error",
                reason=f"negative fee from gateway: {fee_value}",
            )

        # 7. Persist position
        try:
            position = await self._portfolio_service.record_open_fill(
                symbol=signal.symbol,
                side=direction,
                entry_price=Decimal(str(order_result.filled_price)),
                amount=Decimal(str(order_result.filled_qty)),
                budget=self._config.budget,
                fee=fee_value,
                source="telegram",
                signal_id=str(outcome_id),
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
            )
        except Exception as exc:
            logger.exception("[telegram-exec] persistence failed after fill")
            return ExecuteOutcome(status="error", reason=f"persistence failed: {exc}")

        # 7b. PortfolioService.record_open_fill returns None for SELL fills
        # because trdex is long-only today. The gateway still executed the
        # order — this is an operational gap (position untracked) until
        # multi-asset / short-support lands. Surface as error rather than
        # AttributeError, so telemetry shows the signal + reason.
        if position is None:
            logger.warning(
                "[telegram-exec] fill accepted by gateway but portfolio rejected %s %s "
                "(long-only system, SELL signals untracked) — signal_id=%s",
                direction, signal.symbol, outcome_id,
            )
            return ExecuteOutcome(
                status="error",
                reason=f"portfolio rejected {direction} (long-only)",
            )

        logger.info("[telegram-exec] executed %s %s qty=%.6f from %s (pos=%s)",
                    direction, signal.symbol, qty, signal.source, position.id)
        return ExecuteOutcome(status="executed", reason="", position_id=position.id)
