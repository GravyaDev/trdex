"""DefaultExecutionGateway — routes orders to Simulator or LiveExecutor based on mode."""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from trdex.agents.state import OrderResult
from trdex.config import TrdexMode, get_settings
from trdex.execution.gateway import ExecutionGateway
from trdex.execution.models import ExecutionResult, Order, OrderType, Side
from trdex.execution.simulator import _FEE_Q, _PRICE_Q, _QTY_Q, Simulator, _fmt

# Idempotency window: reject duplicate keys within this TTL (seconds)
_IDEMPOTENCY_TTL = 300.0  # 5 minutes

if TYPE_CHECKING:
    from trdex.config import Settings
    from trdex.execution.live_executor import LiveExecutor
    from trdex.risk.stop_loss import KillSwitch

logger = logging.getLogger(__name__)


def _to_order_result(result: ExecutionResult) -> OrderResult:
    """Convert a low-level ExecutionResult to an agent-domain OrderResult.

    The human-readable message uses the same quantization helpers as the
    simulator log so logs and downstream messages stay consistent. The
    numeric ``filled_*`` fields keep float precision for the API surface.
    """
    return OrderResult(
        order_id=result.order_id,
        status="filled",
        filled_price=float(result.filled_price),
        filled_qty=float(result.filled_amount),
        fee=result.fee,
        message=(
            f"{'Simulated' if result.simulated else 'Live'} fill: "
            f"{result.side.value.upper()} {_fmt(result.filled_amount, _QTY_Q)} {result.symbol} "
            f"@ {_fmt(result.filled_price, _PRICE_Q)} (fee {_fmt(result.fee, _FEE_Q)})"
        ),
    )


class DefaultExecutionGateway(ExecutionGateway):
    """Orchestrates order routing: kill-switch check → sim or live dispatch.

    This is the single entry point used by the executor agent node.
    Lower-level gateways (Simulator, LiveExecutor) handle the actual execution.
    """

    def __init__(
        self,
        mode: TrdexMode,
        simulator: Simulator,
        live_executor: LiveExecutor | None,
        kill_switch: KillSwitch,
    ) -> None:
        self._mode = mode
        self._simulator = simulator
        self._live_executor = live_executor
        self._kill_switch = kill_switch
        self._idempotency_cache: dict[str, float] = {}  # key → timestamp

    @classmethod
    def create(cls, settings: Settings | None = None) -> DefaultExecutionGateway:
        """Factory: build a DefaultExecutionGateway from Settings.

        Live executor is only instantiated when mode=live AND credentials are present.
        """
        from trdex.risk.stop_loss import get_kill_switch

        s = settings or get_settings()
        simulator = Simulator()
        live_executor = None

        if s.mode == TrdexMode.LIVE:
            if s.binance_api_key and s.binance_api_secret:
                from trdex.execution.live_executor import LiveExecutor
                live_executor = LiveExecutor.from_settings(s)
                logger.info("[Gateway] live executor initialised (Binance testnet)")
            else:
                logger.warning(
                    "[Gateway] mode=live but TRDEX_BINANCE_API_KEY / TRDEX_BINANCE_API_SECRET "
                    "not set — live orders will be rejected."
                )

        return cls(
            mode=s.mode,
            simulator=simulator,
            live_executor=live_executor,
            kill_switch=get_kill_switch(),
        )

    # ── High-level agent interface ──────────────────────────────────────────

    def _check_idempotency(self, key: str) -> bool:
        """Return True if the key was already used within the TTL window."""
        now = time.monotonic()
        # Prune expired entries
        expired = [k for k, ts in self._idempotency_cache.items() if now - ts > _IDEMPOTENCY_TTL]
        for k in expired:
            del self._idempotency_cache[k]
        return key in self._idempotency_cache

    async def place(
        self,
        symbol: str,
        direction: Literal["BUY", "SELL"],
        qty: float,
        price: float,
        idempotency_key: str | None = None,
        reduce_only: bool = False,
    ) -> OrderResult:
        """Entry point for the executor agent node.

        1. Idempotency check — reject duplicate orders within TTL
        2. Kill-switch check — hard block before any I/O, except for
           ``reduce_only`` orders (closing an existing position). The kill
           switch halts new risk; it must never trap the system in the
           positions it already holds.
        3. Build Order from agent-domain params
        4. Route to Simulator or LiveExecutor
        5. Convert result to OrderResult
        """
        # Gate: idempotency
        if idempotency_key and self._check_idempotency(idempotency_key):
            logger.warning("[Gateway] duplicate order blocked — key=%s", idempotency_key)
            return OrderResult(status="rejected", message=f"Duplicate order (key={idempotency_key})")

        # Gate: kill switch
        if self._kill_switch.active:
            reason = self._kill_switch.status.get("reason", "kill switch active")
            if not reduce_only:
                logger.warning("[Gateway] order blocked by kill switch: %s", reason)
                return OrderResult(status="rejected", message=f"Kill switch: {reason}")
            logger.warning(
                "[Gateway] kill switch active (%s) — allowing reduce-only close %s %s",
                reason, direction, symbol,
            )

        order = Order(
            symbol=symbol,
            side=Side(direction.lower()),
            type=OrderType.MARKET,
            amount=Decimal(str(qty)),
            price=Decimal(str(price)),
        )

        try:
            result = await self.execute(order)
            order_result = _to_order_result(result)
            # Record idempotency key on success
            if idempotency_key and order_result.status == "filled":
                self._idempotency_cache[idempotency_key] = time.monotonic()
            return order_result
        except Exception as exc:
            logger.exception("[Gateway] execution failed for %s", symbol)
            return OrderResult(status="rejected", message=f"Execution error: {exc}")

    # ── Low-level ExecutionGateway interface ────────────────────────────────

    async def execute(self, order: Order) -> ExecutionResult:
        """Route to simulator or live executor based on configured mode."""
        if self._mode == TrdexMode.SIMULATION:
            return await self._simulator.execute(order)

        # Live mode
        if self._live_executor is None:
            raise RuntimeError(
                "Live executor not configured. Set TRDEX_BINANCE_API_KEY and "
                "TRDEX_BINANCE_API_SECRET in your .env file."
            )
        return await self._live_executor.execute(order)

    async def cancel(self, order_id: str) -> bool:
        """Route cancellation to the appropriate executor."""
        if self._mode == TrdexMode.SIMULATION:
            return await self._simulator.cancel(order_id)
        if self._live_executor is None:
            return False
        return await self._live_executor.cancel(order_id)
