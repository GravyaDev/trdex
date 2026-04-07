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
from enum import StrEnum

logger = logging.getLogger(__name__)


class StopReason(StrEnum):
    POSITION_STOP_LOSS = "position_stop_loss"    # single position hit SL %
    POSITION_TAKE_PROFIT = "position_take_profit"  # single position hit TP %
    TRAILING_STOP = "trailing_stop"              # price retraced from high-water mark
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

    State is persisted to DB (kill_switch_state table) so that a process
    restart does not silently re-enable trading after a drawdown event.
    """

    def __init__(self) -> None:
        self._active = False
        self._reason: str = ""
        self._activated_at: datetime | None = None
        self._lock = asyncio.Lock()
        self._session_factory = None  # Set via configure() at app startup

    def configure(self, session_factory) -> None:
        """Inject the DB session factory for persistence. Called once at app startup."""
        self._session_factory = session_factory

    async def load_from_db(self) -> None:
        """Restore kill switch state from DB. Call at app startup after configure()."""
        if self._session_factory is None:
            return
        try:
            from sqlalchemy import text
            async with self._session_factory() as session:
                row = (await session.execute(
                    text("SELECT active, reason, activated_at FROM kill_switch_state WHERE id = 1")
                )).first()
                if row and row.active:
                    self._active = True
                    self._reason = row.reason or ""
                    self._activated_at = row.activated_at
                    logger.critical(
                        "[KillSwitch] RESTORED from DB — was active since %s: %s",
                        self._activated_at, self._reason,
                    )
        except Exception:
            logger.exception("[KillSwitch] failed to load state from DB — defaulting to inactive")

    async def _persist(self) -> None:
        """Save current state to DB."""
        if self._session_factory is None:
            return
        try:
            from sqlalchemy import text
            async with self._session_factory() as session:
                await session.execute(
                    text(
                        "UPDATE kill_switch_state "
                        "SET active = :active, reason = :reason, "
                        "    activated_at = :activated_at, updated_at = NOW() "
                        "WHERE id = 1"
                    ),
                    {
                        "active": self._active,
                        "reason": self._reason,
                        "activated_at": self._activated_at,
                    },
                )
                await session.commit()
        except Exception:
            logger.exception("[KillSwitch] failed to persist state to DB")

    async def activate_async(self, reason: str) -> None:
        async with self._lock:
            if not self._active:
                self._active = True
                self._reason = reason
                self._activated_at = datetime.now(tz=timezone.utc)
                logger.critical("[KillSwitch] ACTIVATED — %s", reason)
                await self._persist()

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
            await self._persist()

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
        gateway=None,
        check_interval: float = 30.0,
        position_sl_pct: float = 0.05,       # 5% loss per position → close
        position_tp_pct: float = 0.10,       # 10% gain per position → close
        trailing_stop_pct: float = 0.03,     # 3% retrace from high-water mark → close
        daily_drawdown_pct: float = 0.10,    # 10% portfolio daily loss → kill switch
        max_drawdown_pct: float = 0.20,      # 20% all-time drawdown → kill switch
    ) -> None:
        self._session_factory = session_factory
        self._feeds = feed_manager
        self._gateway = gateway  # DefaultExecutionGateway for auto-close
        self._interval = check_interval
        self._sl_pct = position_sl_pct
        self._tp_pct = position_tp_pct
        self._trailing_pct = trailing_stop_pct
        self._daily_dd_pct = daily_drawdown_pct
        self._max_dd_pct = max_drawdown_pct
        self._task: asyncio.Task[None] | None = None
        self._callbacks: list = []
        self._events: list[StopLossEvent] = []
        self._peak_equity: float | None = None  # loaded from DB on first check
        self._last_check: datetime | None = None
        self._trailing_highs: dict[int, float] = {}  # position_id → high-water mark price

    def on_event(self, callback) -> None:
        """Register an async callback fired on every StopLossEvent."""
        self._callbacks.append(callback)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="stoploss-monitor")
        logger.info(
            "[StopLoss] monitor started — interval=%.0fs sl=%.1f%% tp=%.1f%% trailing=%.1f%% daily_dd=%.1f%% max_dd=%.1f%%",
            self._interval, self._sl_pct * 100, self._tp_pct * 100,
            self._trailing_pct * 100, self._daily_dd_pct * 100, self._max_dd_pct * 100,
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _init_peak_equity(self) -> None:
        """Load peak equity from DB balance ledger on first check."""
        try:
            from trdex.storage.balance_repo import BalanceRepository
            async with self._session_factory() as session:
                bal_repo = BalanceRepository(session)
                self._peak_equity = float(await bal_repo.peak_balance())
            logger.info("[StopLoss] peak_equity initialised from DB: %.2f", self._peak_equity)
        except Exception:
            logger.exception("[StopLoss] could not load peak_equity from DB — will derive from current positions")

    async def _auto_close(self, position, price: float, reason: str, price_age: datetime | None = None) -> None:
        """Attempt to close a position via the execution gateway.

        If no gateway is injected, logs a warning with manual close instruction.
        If the close order fails, activates kill switch as fail-safe.
        If price is stale (>60s), refetches before submitting.
        """
        if self._gateway is None:
            logger.warning(
                "[StopLoss] AUTO-CLOSE unavailable (no gateway). "
                "MANUAL CLOSE REQUIRED for %s position %s.",
                position.symbol, position.id,
            )
            return

        # Staleness check: refetch price if older than 60 seconds
        if price_age is not None:
            age_seconds = (datetime.now(tz=timezone.utc) - price_age).total_seconds()
            if age_seconds > 60:
                try:
                    ticker = await self._feeds.get_ticker(position.symbol)
                    fresh_price = float(ticker.price)
                    logger.info(
                        "[StopLoss] refetched stale price for %s: %.4f → %.4f (was %.0fs old)",
                        position.symbol, price, fresh_price, age_seconds,
                    )
                    price = fresh_price
                except Exception:
                    logger.warning("[StopLoss] could not refetch price for %s — using stale price", position.symbol)

        # Determine close direction: opposite of position side
        close_direction = "SELL" if position.side == "BUY" else "BUY"
        qty = float(position.amount)

        logger.info(
            "[StopLoss] auto-closing %s position %s: %s %.6f @ %.4f (%s)",
            position.symbol, position.id, close_direction, qty, price, reason,
        )
        try:
            result = await self._gateway.place(
                symbol=position.symbol,
                direction=close_direction,
                qty=qty,
                price=price,
                idempotency_key=f"close:{position.id}",
            )
            if result.status == "filled":
                logger.info(
                    "[StopLoss] auto-close FILLED for %s position %s: %s",
                    position.symbol, position.id, result.message,
                )
                # Persist the close: update positions.status='closed' and
                # write realised PnL to the account_balance ledger. Best
                # effort — a persistence failure here MUST NOT prevent the
                # fact that the close already happened on the exchange.
                try:
                    from decimal import Decimal

                    from trdex.portfolio.service import PortfolioService
                    from trdex.storage.portfolio_repo import PortfolioRepository

                    fill_price = Decimal(str(result.filled_price)) if result.filled_price is not None else Decimal(str(price))
                    async with self._session_factory() as session:
                        repo = PortfolioRepository(session)
                        service = PortfolioService(repo, self._feeds)
                        await service.record_close_fill(
                            position=position,
                            exit_price=fill_price,
                            fee=Decimal("0"),  # sim fee is cosmetic in log
                        )
                except Exception:
                    logger.exception(
                        "[StopLoss] failed to persist close of %s position %s — "
                        "exchange state and ledger are now out of sync",
                        position.symbol, position.id,
                    )
            else:
                logger.error(
                    "[StopLoss] auto-close FAILED for %s position %s: %s — activating kill switch",
                    position.symbol, position.id, result.message,
                )
                await _kill_switch.activate_async(
                    f"Auto-close failed for {position.symbol} position {position.id}: {result.message}"
                )
        except Exception as exc:
            logger.critical(
                "[StopLoss] auto-close CRASHED for %s position %s: %s — activating kill switch",
                position.symbol, position.id, exc,
            )
            await _kill_switch.activate_async(
                f"Auto-close crashed for {position.symbol}: {exc}"
            )

    async def check_now(self) -> list[StopLossEvent]:
        """Run a single check cycle. Returns any events fired."""
        new_events: list[StopLossEvent] = []

        # Skip all checks if kill switch is already active
        if _kill_switch.active:
            return new_events

        # First run: initialise peak equity from DB rather than current positions
        if self._peak_equity is None:
            await self._init_peak_equity()

        from trdex.storage.portfolio_repo import PortfolioRepository

        async with self._session_factory() as session:
            repo = PortfolioRepository(session)
            open_positions = await repo.get_open_positions()

        if not open_positions:
            self._last_check = datetime.now(tz=timezone.utc)
            return new_events

        # Fetch current prices for all unique symbols (with timestamp for staleness check)
        prices: dict[str, float] = {}
        price_times: dict[str, datetime] = {}
        now = datetime.now(tz=timezone.utc)
        for sym in {p.symbol for p in open_positions}:
            try:
                ticker = await self._feeds.get_ticker(sym)
                prices[sym] = float(ticker.price)
                price_times[sym] = now
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

            # Update trailing stop high-water mark
            pos_id = pos.id
            if pos.side == "BUY":
                hwm = self._trailing_highs.get(pos_id, price)
                if price > hwm:
                    self._trailing_highs[pos_id] = price
                    hwm = price
            else:
                # For SHORT positions, track the low-water mark (lowest price is best)
                hwm = self._trailing_highs.get(pos_id, price)
                if price < hwm:
                    self._trailing_highs[pos_id] = price
                    hwm = price

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
                await self._auto_close(pos, price, "stop_loss", price_age=price_times.get(pos.symbol))

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
                await self._auto_close(pos, price, "take_profit", price_age=price_times.get(pos.symbol))

            # Trailing stop: price retraced from high-water mark
            elif pnl_pct > 0 and pos_id in self._trailing_highs:
                hwm = self._trailing_highs[pos_id]
                if pos.side == "BUY":
                    retrace = (hwm - price) / hwm if hwm > 0 else 0.0
                else:
                    retrace = (price - hwm) / hwm if hwm > 0 else 0.0

                if retrace >= self._trailing_pct:
                    event = StopLossEvent(
                        reason=StopReason.TRAILING_STOP,
                        symbol=pos.symbol,
                        position_id=pos_id,
                        trigger_price=price,
                        entry_price=entry,
                        loss_pct=pnl_pct,
                        message=(
                            f"{pos.symbol} position {pos_id} trailing stop: "
                            f"retraced {retrace:.2%} from peak {hwm:.4f} (limit: {self._trailing_pct:.2%})"
                        ),
                    )
                    new_events.append(event)
                    logger.warning("[StopLoss] TRAILING STOP: %s", event.message)
                    await self._auto_close(pos, price, "trailing_stop", price_age=price_times.get(pos.symbol))
                    del self._trailing_highs[pos_id]  # Clean up after close

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
                "trailing_stop_pct": self._trailing_pct,
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
