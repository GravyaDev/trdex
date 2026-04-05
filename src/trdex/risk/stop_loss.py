"""External stop-loss engine — operates independently of the AI agent layer.

This module is intentionally separated from the AI agent graph. It runs as a
background monitor that can forcibly close positions and halt trading without
consulting any LLM or agent. It is the hard safety net.

Design principles:
- Rule-based only. No AI. No exceptions.
- Reads positions from DB, prices from feed manager.
- Emits StopLossEvent when a trigger fires.
- Can be hooked into a kill switch that blocks all future orders.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

logger = logging.getLogger(__name__)


class StopReason(StrEnum):
    POSITION_STOP_LOSS = "position_stop_loss"    # single position hit SL %
    POSITION_TAKE_PROFIT = "position_take_profit"  # single position hit TP %
    DAILY_DRAWDOWN = "daily_drawdown"             # total portfolio daily loss exceeded
    MAX_DRAWDOWN = "max_drawdown"                 # all-time drawdown exceeded config limit
    KILL_SWITCH = "kill_switch"                   # manual override via API


@dataclass
class StopLossEvent:
    """Fired when a stop condition is triggered."""
    reason: StopReason
    symbol: str | None          # None = portfolio-level event
    position_id: int | None
    trigger_price: float | None
    entry_price: float | None
    loss_pct: float | None
    fired_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    message: str = ""


class KillSwitch:
    """Global trading halt. Once activated, blocks all new orders.

    This is the last-resort safety gate: if triggered, no order can pass
    through regardless of AI agent approval. Must be manually reset.

    Thread/async-safe: all state mutations are protected by an asyncio.Lock.
    """

    def __init__(self) -> None:
        self._active = False
        self._reason: str = ""
        self._activated_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def activate_async(self, reason: str) -> None:
        async with self._lock:
            if not self._active:
                self._active = True
                self._reason = reason
                self._activated_at = datetime.now(tz=timezone.utc)
                logger.critical("[KillSwitch] ACTIVATED — %s", reason)

    def activate(self, reason: str) -> None:
        """Synchronous activate for use outside async context (e.g. startup)."""
        if not self._active:
            self._active = True
            self._reason = reason
            self._activated_at = datetime.now(tz=timezone.utc)
            logger.critical("[KillSwitch] ACTIVATED — %s", reason)

    async def reset_async(self) -> None:
        async with self._lock:
            self._active = False
            self._reason = ""
            self._activated_at = None
            logger.warning("[KillSwitch] reset — trading re-enabled")

    def reset(self) -> None:
        """Synchronous reset for use outside async context."""
        self._active = False
        self._reason = ""
        self._activated_at = None
        logger.warning("[KillSwitch] reset — trading re-enabled")

    @property
    def active(self) -> bool:
        return self._active

    @property
    def status(self) -> dict:
        return {
            "active": self._active,
            "reason": self._reason,
            "activated_at": self._activated_at.isoformat() if self._activated_at else None,
        }


# Module-level singleton — shared across the app
_kill_switch = KillSwitch()


def get_kill_switch() -> KillSwitch:
    return _kill_switch


class StopLossMonitor:
    """Background monitor: checks all open positions against stop conditions.

    Runs on a configurable interval. Fires StopLossEvent callbacks when a
    condition is met. Activates the kill switch on portfolio-level breaches.

    Usage:
        monitor = StopLossMonitor(session_factory, feed_manager)
        monitor.on_event(my_handler)   # async callback
        await monitor.start()
        ...
        await monitor.stop()
    """

    def __init__(
        self,
        session_factory,
        feed_manager,
        check_interval: float = 30.0,
        position_sl_pct: float = 0.05,       # 5% loss per position → close
        position_tp_pct: float = 0.10,       # 10% gain per position → close
        daily_drawdown_pct: float = 0.10,    # 10% portfolio daily loss → kill switch
        max_drawdown_pct: float = 0.20,      # 20% all-time drawdown → kill switch
    ) -> None:
        self._session_factory = session_factory
        self._feeds = feed_manager
        self._interval = check_interval
        self._sl_pct = position_sl_pct
        self._tp_pct = position_tp_pct
        self._daily_dd_pct = daily_drawdown_pct
        self._max_dd_pct = max_drawdown_pct
        self._task: asyncio.Task[None] | None = None
        self._callbacks: list = []
        self._events: list[StopLossEvent] = []
        self._peak_equity: float | None = None
        self._last_check: datetime | None = None

    def on_event(self, callback) -> None:
        """Register an async callback fired on every StopLossEvent."""
        self._callbacks.append(callback)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="stoploss-monitor")
        logger.info(
            "[StopLoss] monitor started — interval=%.0fs sl=%.1f%% tp=%.1f%% daily_dd=%.1f%% max_dd=%.1f%%",
            self._interval, self._sl_pct * 100, self._tp_pct * 100,
            self._daily_dd_pct * 100, self._max_dd_pct * 100,
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def check_now(self) -> list[StopLossEvent]:
        """Run a single check cycle. Returns any events fired."""
        new_events: list[StopLossEvent] = []

        # Skip all checks if kill switch is already active
        if _kill_switch.active:
            return new_events

        from trdex.storage.portfolio_repo import PortfolioRepository

        async with self._session_factory() as session:
            repo = PortfolioRepository(session)
            open_positions = await repo.get_open_positions()

        if not open_positions:
            self._last_check = datetime.now(tz=timezone.utc)
            return new_events

        # Fetch current prices for all unique symbols
        prices: dict[str, float] = {}
        for sym in {p.symbol for p in open_positions}:
            try:
                ticker = await self._feeds.get_ticker(sym)
                prices[sym] = float(ticker.price)
            except Exception:
                logger.warning("[StopLoss] could not fetch price for %s", sym)

        total_unrealized = 0.0
        total_cost = 0.0

        for pos in open_positions:
            price = prices.get(pos.symbol)
            if price is None:
                continue

            entry = float(pos.entry_price)
            amount = float(pos.amount)
            cost = entry * amount

            if pos.side == "BUY":
                pnl_pct = (price - entry) / entry
            else:
                pnl_pct = (entry - price) / entry

            unrealized = pnl_pct * cost
            total_unrealized += unrealized
            total_cost += cost

            # Per-position stop-loss
            if pnl_pct <= -self._sl_pct:
                event = StopLossEvent(
                    reason=StopReason.POSITION_STOP_LOSS,
                    symbol=pos.symbol,
                    position_id=pos.id,
                    trigger_price=price,
                    entry_price=entry,
                    loss_pct=pnl_pct,
                    message=(
                        f"{pos.symbol} position {pos.id} hit stop-loss: "
                        f"{pnl_pct:.2%} loss (limit: {-self._sl_pct:.2%})"
                    ),
                )
                new_events.append(event)
                logger.warning("[StopLoss] POSITION SL: %s", event.message)

            # Per-position take-profit
            elif pnl_pct >= self._tp_pct:
                event = StopLossEvent(
                    reason=StopReason.POSITION_TAKE_PROFIT,
                    symbol=pos.symbol,
                    position_id=pos.id,
                    trigger_price=price,
                    entry_price=entry,
                    loss_pct=pnl_pct,
                    message=(
                        f"{pos.symbol} position {pos.id} hit take-profit: "
                        f"{pnl_pct:.2%} gain (limit: {self._tp_pct:.2%})"
                    ),
                )
                new_events.append(event)
                logger.info("[StopLoss] POSITION TP: %s", event.message)

        # Portfolio-level: daily drawdown
        if total_cost > 0:
            portfolio_pnl_pct = total_unrealized / total_cost
            if portfolio_pnl_pct <= -self._daily_dd_pct:
                event = StopLossEvent(
                    reason=StopReason.DAILY_DRAWDOWN,
                    symbol=None,
                    position_id=None,
                    trigger_price=None,
                    entry_price=None,
                    loss_pct=portfolio_pnl_pct,
                    message=(
                        f"Daily drawdown {portfolio_pnl_pct:.2%} exceeded limit "
                        f"{-self._daily_dd_pct:.2%} — KILL SWITCH activated"
                    ),
                )
                new_events.append(event)
                await _kill_switch.activate_async(event.message)
                logger.critical("[StopLoss] PORTFOLIO DD: %s", event.message)

        # Portfolio-level: all-time max drawdown (peak-to-trough)
        equity = total_cost + total_unrealized
        if self._peak_equity is None or equity > self._peak_equity:
            self._peak_equity = equity
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity
            if drawdown >= self._max_dd_pct:
                event = StopLossEvent(
                    reason=StopReason.MAX_DRAWDOWN,
                    symbol=None,
                    position_id=None,
                    trigger_price=None,
                    entry_price=None,
                    loss_pct=-drawdown,
                    message=(
                        f"Max drawdown {drawdown:.2%} exceeded limit "
                        f"{self._max_dd_pct:.2%} — KILL SWITCH activated"
                    ),
                )
                new_events.append(event)
                await _kill_switch.activate_async(event.message)
                logger.critical("[StopLoss] MAX DRAWDOWN: %s", event.message)

        # Store and dispatch
        self._events.extend(new_events)
        self._last_check = datetime.now(tz=timezone.utc)

        for event in new_events:
            for cb in self._callbacks:
                try:
                    await cb(event)
                except Exception:
                    logger.exception("[StopLoss] callback error")

        return new_events

    async def _loop(self) -> None:
        while True:
            try:
                events = await self.check_now()
                if events:
                    logger.info("[StopLoss] cycle fired %d event(s)", len(events))
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("[StopLoss] unexpected error in monitor loop")
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break

    @property
    def status(self) -> dict:
        return {
            "running": self._task is not None and not self._task.done(),
            "kill_switch": _kill_switch.status,
            "last_check": self._last_check.isoformat() if self._last_check else None,
            "events_fired": len(self._events),
            "thresholds": {
                "position_sl_pct": self._sl_pct,
                "position_tp_pct": self._tp_pct,
                "daily_drawdown_pct": self._daily_dd_pct,
                "max_drawdown_pct": self._max_dd_pct,
            },
        }

    @property
    def recent_events(self) -> list[dict]:
        return [
            {
                "reason": e.reason,
                "symbol": e.symbol,
                "position_id": e.position_id,
                "loss_pct": e.loss_pct,
                "message": e.message,
                "fired_at": e.fired_at.isoformat(),
            }
            for e in self._events[-50:]
        ]
