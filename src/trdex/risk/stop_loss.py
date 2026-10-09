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
from typing import Any

logger = logging.getLogger(__name__)


class StopReason(StrEnum):
    POSITION_STOP_LOSS = "position_stop_loss"    # single position hit SL %
    POSITION_TAKE_PROFIT = "position_take_profit"  # single position hit TP %
    TRAILING_STOP = "trailing_stop"              # price retraced from high-water mark
    DAILY_DRAWDOWN = "daily_drawdown"             # equity loss since start of UTC day exceeded
    OPEN_POSITIONS_LOSS = "open_positions_loss"   # unrealised loss / cost of the open book exceeded
    MAX_DRAWDOWN = "max_drawdown"                 # mark-to-market peak-to-trough exceeded limit
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


def _notify_kill_switch(reason: str) -> None:
    """Push the activation to the operator (never raises)."""
    try:
        from trdex.notify import Event, notify_background

        notify_background(
            Event.KILL_SWITCH,
            "Kill switch ACTIVATED — trading halted",
            f"Reason: {reason}\nNo new orders until it is reset from the dashboard.",
        )
    except Exception:
        logger.exception("[KillSwitch] activation notification failed")


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
                _notify_kill_switch(reason)

    def activate(self, reason: str) -> None:
        """Synchronous activate for use outside async context (e.g. startup)."""
        if not self._active:
            self._active = True
            self._reason = reason
            self._activated_at = datetime.now(tz=timezone.utc)
            logger.critical("[KillSwitch] ACTIVATED — %s", reason)
            _notify_kill_switch(reason)

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


# Multipliers: how many CVs above the base threshold.
# 2.5× CV means the adaptive SL sits at ~2.5 standard deviations
# of recent price movement — wide enough to avoid noise, tight
# enough to cut real drawdowns. TP uses 5× CV (let winners run
# further on volatile coins). Trailing uses 1.5× CV (tighter
# than SL to lock in profits once they exist).
_SL_CV_MULT = 2.5
_TP_CV_MULT = 5.0
_TRAIL_CV_MULT = 1.5


def effective_thresholds(
    pos: Any,
    override: Any,
    cv: float,
    *,
    base_sl: float,
    base_tp: float,
    base_trail: float,
) -> tuple[float, float, float]:
    """Return (stop_loss, take_profit, trailing) fractions for one position.

    Priority, highest first:

    1. Per-symbol operator override (``symbol_config`` row) — the operator
       always has the last word.
    2. Per-position values stored at open:
       - Telegram positions keep the signal's own stop as-is (it is the
         strategy being followed; the stop-distance gate bounds it).
       - Agent positions: the LLM-suggested stop can only WIDEN the
         adaptive floor, never tighten it below ``max(base, 2.5×CV)``.
       - Take-profit is used as stored.
    3. Adaptive floor ``max(base, k×CV)`` from operator config + volatility.
    """
    floor_sl = max(base_sl, _SL_CV_MULT * cv)
    floor_tp = max(base_tp, _TP_CV_MULT * cv)
    floor_trail = max(base_trail, _TRAIL_CV_MULT * cv)

    pos_sl = getattr(pos, "stop_loss_pct", None)
    pos_tp = getattr(pos, "take_profit_pct", None)
    is_telegram = getattr(pos, "source", None) == "telegram"

    if override is not None and override.sl_pct is not None:
        sl = override.sl_pct
    elif pos_sl is not None:
        sl = pos_sl if is_telegram else max(floor_sl, pos_sl)
    else:
        sl = floor_sl

    if override is not None and override.tp_pct is not None:
        tp = override.tp_pct
    elif pos_tp is not None:
        tp = pos_tp
    else:
        tp = floor_tp

    if override is not None and override.trailing_pct is not None:
        trail = override.trailing_pct
    else:
        trail = floor_trail

    return sl, tp, trail


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
        daily_drawdown_pct: float = 0.10,    # equity loss since UTC midnight → kill switch
        max_drawdown_pct: float = 0.20,      # 20% mark-to-market drawdown → kill switch
        open_positions_loss_pct: float = 0.10,  # unrealised loss / open-book cost → kill switch
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
        self._open_loss_pct = open_positions_loss_pct
        self._task: asyncio.Task[None] | None = None
        self._callbacks: list = []
        # Rolling cache of the last 50 events — hydrated from the
        # stop_loss_events table on start() and kept in sync by
        # _persist_event(). Lets recent_events stay a sync property
        # while the underlying log is persistent across restarts.
        self._events: list[StopLossEvent] = []
        # Cumulative count since the table was created, read from DB
        # at start and incremented on each successful _persist_event.
        # Shown in /v1/risk/status.events_fired so the number survives
        # a container cycle even though the cache is bounded.
        self._events_fired_total: int = 0
        self._persist_failures: int = 0  # consecutive DB write failures
        self._peak_equity: float | None = None  # loaded from DB on first check
        self._last_check: datetime | None = None
        self._trailing_highs: dict[int, float] = {}  # position_id → high-water mark price

    def on_event(self, callback) -> None:
        """Register an async callback fired on every StopLossEvent."""
        self._callbacks.append(callback)

    async def start(self) -> None:
        # Rehydrate the in-memory cache from the persistent event log
        # so /v1/risk/events returns real history right after a restart
        # instead of an empty list.
        await self._hydrate_events_from_db()
        self._task = asyncio.create_task(self._loop(), name="stoploss-monitor")
        logger.info(
            "[StopLoss] monitor started — interval=%.0fs sl=%.1f%% tp=%.1f%% trailing=%.1f%% daily_dd=%.1f%% max_dd=%.1f%% hydrated_events=%d total_fired=%d",
            self._interval, self._sl_pct * 100, self._tp_pct * 100,
            self._trailing_pct * 100, self._daily_dd_pct * 100, self._max_dd_pct * 100,
            len(self._events), self._events_fired_total,
        )

    async def _hydrate_events_from_db(self) -> None:
        """Load the most recent events from the persistent log into
        the in-memory cache. Swallows DB errors so a transient
        database hiccup at startup does not crash the monitor —
        the cache stays empty in that case.
        """
        try:
            from trdex.storage.stop_loss_event_repo import StopLossEventRepository
            async with self._session_factory() as session:
                repo = StopLossEventRepository(session)
                records = await repo.recent(limit=50)
                total = await repo.count()
        except Exception:
            logger.exception("[StopLoss] failed to hydrate events from DB")
            return

        self._events_fired_total = total
        # records come newest-first from repo.recent(); _events is
        # kept oldest-first to match the historical slice semantics
        # of `self._events[-50:]` in recent_events.
        self._events = [
            StopLossEvent(
                reason=StopReason(r.reason),
                symbol=r.symbol,
                position_id=r.position_id,
                trigger_price=float(r.trigger_price) if r.trigger_price is not None else None,
                entry_price=float(r.entry_price) if r.entry_price is not None else None,
                loss_pct=r.loss_pct,
                fired_at=r.fired_at.replace(tzinfo=timezone.utc) if r.fired_at and r.fired_at.tzinfo is None else r.fired_at,
                message=r.message or "",
            )
            for r in reversed(records)
        ]

    async def _persist_event(self, event: StopLossEvent) -> None:
        """Write a single event to the persistent log. Best-effort:
        failures are logged but do not interrupt the check cycle —
        the risk monitor's primary job is to protect capital, and a
        DB write failure must never block a stop-loss execution.
        """
        try:
            from trdex.storage.stop_loss_event_repo import StopLossEventRepository
            async with self._session_factory() as session:
                repo = StopLossEventRepository(session)
                await repo.save(
                    reason=str(event.reason),
                    symbol=event.symbol,
                    position_id=event.position_id,
                    trigger_price=event.trigger_price,
                    entry_price=event.entry_price,
                    loss_pct=event.loss_pct,
                    message=event.message,
                    fired_at=event.fired_at,
                )
            self._events_fired_total += 1
            self._persist_failures = 0  # reset on success
        except Exception:
            self._persist_failures += 1
            logger.exception(
                "[StopLoss] failed to persist event reason=%s symbol=%s "
                "(consecutive failures: %d)",
                event.reason, event.symbol, self._persist_failures,
            )
            if self._persist_failures >= 3:
                logger.critical(
                    "[StopLoss] AUDIT TRAIL AT RISK: %d consecutive "
                    "persist failures — DB may be down. Stop-loss events "
                    "are firing but NOT being recorded. Check DB connectivity.",
                    self._persist_failures,
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
                    ticker = await self._feeds.get_ticker(position.symbol, source="binance")
                    fresh_price = float(ticker.price)
                    logger.info(
                        "[StopLoss] refetched stale price for %s: %.4f → %.4f (was %.0fs old)",
                        position.symbol, price, fresh_price, age_seconds,
                    )
                    price = fresh_price
                except Exception:
                    logger.warning("[StopLoss] could not refetch Binance price for %s — using stale price", position.symbol)

        # Determine close direction: opposite of position side
        close_direction = "SELL" if position.side == "BUY" else "BUY"
        qty = float(position.amount)

        logger.info(
            "[StopLoss] auto-closing %s position %s: %s %.6f @ %.4f (%s)",
            position.symbol, position.id, close_direction, qty, price, reason,
        )
        try:
            # reduce_only: closes must go through even when the kill switch
            # is active, otherwise a tripped switch traps open positions.
            result = await self._gateway.place(
                symbol=position.symbol,
                direction=close_direction,
                qty=qty,
                price=price,
                idempotency_key=f"close:{position.id}",
                reduce_only=True,
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
                    # D20: map SL reason string to the ClosedBy enum
                    # literal so inspect_runs can break down closes by
                    # trigger subsystem.
                    closed_by_value = (
                        "stop_loss" if reason == "stop_loss"
                        else "take_profit" if reason == "take_profit"
                        else "trailing_stop" if reason == "trailing_stop"
                        else "kill_switch"
                    )
                    # Estimate close fee from fill: 0.1% taker (Binance standard).
                    # In simulation mode the Simulator uses the same rate; in
                    # live mode the LiveExecutor would return the real fee from
                    # the exchange response. We approximate here because
                    # _auto_close does not go through the Simulator — it
                    # closes the position directly via the gateway.
                    close_fee = fill_price * Decimal(str(float(position.amount))) * Decimal("0.001")
                    async with self._session_factory() as session:
                        repo = PortfolioRepository(session)
                        service = PortfolioService(repo, self._feeds)
                        await service.record_close_fill(
                            position=position,
                            exit_price=fill_price,
                            fee=close_fee,
                            closed_by=closed_by_value,
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

    async def _trip(self, events: list[StopLossEvent], reason: StopReason,
                    loss_pct: float, message: str) -> None:
        event = StopLossEvent(
            reason=reason, symbol=None, position_id=None,
            trigger_price=None, entry_price=None,
            loss_pct=loss_pct, message=message,
        )
        events.append(event)
        await _kill_switch.activate_async(message)
        logger.critical("[StopLoss] %s: %s", reason.value.upper(), message)

    async def _check_portfolio_limits(
        self,
        events: list[StopLossEvent],
        *,
        total_unrealized: float,
        total_cost: float,
        realised_balance: float | None,
        day_start_balance: float | None,
    ) -> None:
        """Portfolio-level limits that trip the kill switch.

        - Open-positions loss: unrealised loss as a fraction of the cost of
          the open book. This is what used to be called "daily drawdown";
          it is neither daily nor measured on equity, so it keeps its
          behaviour under an honest name.
        - Daily drawdown: equity now (realised balance + unrealised P&L)
          versus the realised balance at the start of the UTC day.
        - Max drawdown: mark-to-market equity versus its running peak.
          Equity is realised balance + unrealised P&L — NOT the cost of the
          open positions, which is what caused Bug 8 (2026-04-08).
        """
        if total_cost > 0:
            open_loss = total_unrealized / total_cost
            if open_loss <= -self._open_loss_pct:
                await self._trip(
                    events, StopReason.OPEN_POSITIONS_LOSS, open_loss,
                    f"Open positions loss {open_loss:.2%} of their cost exceeded limit "
                    f"{-self._open_loss_pct:.2%} — KILL SWITCH activated",
                )

        if realised_balance is None:
            return
        equity = realised_balance + total_unrealized

        if day_start_balance is not None and day_start_balance > 0:
            daily_loss = (day_start_balance - equity) / day_start_balance
            if daily_loss >= self._daily_dd_pct:
                await self._trip(
                    events, StopReason.DAILY_DRAWDOWN, -daily_loss,
                    f"Daily drawdown {daily_loss:.2%} of equity since 00:00 UTC exceeded "
                    f"limit {self._daily_dd_pct:.2%} — KILL SWITCH activated",
                )

        if self._peak_equity is None or equity > self._peak_equity:
            self._peak_equity = equity
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - equity) / self._peak_equity
            if drawdown >= self._max_dd_pct:
                await self._trip(
                    events, StopReason.MAX_DRAWDOWN, -drawdown,
                    f"Max drawdown {drawdown:.2%} exceeded limit "
                    f"{self._max_dd_pct:.2%} — KILL SWITCH activated",
                )

    async def check_now(self) -> list[StopLossEvent]:
        """Run a single check cycle. Returns any events fired."""
        new_events: list[StopLossEvent] = []

        # The kill switch halts NEW risk; it must not switch off protection
        # of positions already open. Per-position SL/TP/trailing always run
        # (their closes are reduce-only and pass the gateway). Portfolio-level
        # checks are skipped while the switch is already tripped, otherwise
        # they would re-fire and re-log the same event every cycle.
        kill_switch_was_active = _kill_switch.active

        # First run: initialise peak equity from DB rather than current positions
        if self._peak_equity is None:
            await self._init_peak_equity()

        from trdex.storage.balance_repo import BalanceRepository
        from trdex.storage.portfolio_repo import PortfolioRepository

        async with self._session_factory() as session:
            repo = PortfolioRepository(session)
            open_positions = await repo.get_open_positions()

        # Realised balance and the day-start baseline are read ONCE, before any
        # auto-close in this cycle: a close persisted mid-cycle would otherwise
        # be counted twice (as realised AND as the unrealised loss below).
        realised_balance: float | None = None
        day_start_balance: float | None = None
        if not kill_switch_was_active:
            try:
                async with self._session_factory() as session:
                    bal_repo = BalanceRepository(session)
                    realised_balance = float(await bal_repo.current_balance())
                    midnight = datetime.now(tz=timezone.utc).replace(
                        hour=0, minute=0, second=0, microsecond=0,
                    )
                    at_midnight = await bal_repo.balance_at(midnight)
                    # No ledger row before today (fresh deploy): use today's
                    # realised balance as the baseline.
                    day_start_balance = (
                        float(at_midnight) if at_midnight is not None else realised_balance
                    )
            except Exception:
                logger.exception("[StopLoss] could not read balance ledger — portfolio checks skipped this cycle")

        # Fetch current prices for all unique symbols (with timestamp for staleness check).
        # IMPORTANT: use Binance only (source="binance") to avoid cross-feed price
        # mismatch. If Binance fails for a symbol, skip it — never close a position
        # based on a price from a secondary feed that may diverge significantly.
        prices: dict[str, float] = {}
        price_times: dict[str, datetime] = {}
        now = datetime.now(tz=timezone.utc)
        for sym in {p.symbol for p in open_positions}:
            try:
                ticker = await self._feeds.get_ticker(sym, source="binance")
                prices[sym] = float(ticker.price)
                price_times[sym] = now
            except Exception:
                logger.warning("[StopLoss] could not fetch Binance price for %s — skipping SL check", sym)

        # Load per-symbol volatility CV from entity graph so that
        # SL/TP/trailing thresholds adapt to the coin's natural price
        # swings. A fixed 5% SL is fine for BTC (CV~0.4%) but suicidal
        # for ENJ (CV~13%) or meme coins (CV~20%): the price oscillates
        # more than ±5% even during a strong trend, causing repeated
        # whipsaw stop-outs. The adaptive formula uses
        #   adaptive = max(base_threshold, multiplier × CV)
        # so low-vol coins keep the configured floor and high-vol coins
        # get wider breathing room proportional to their volatility.
        #
        # CV source: written every tick by the Analyst agent to the
        # entity graph (subject_type="symbol", predicate="volatility_regime",
        # object_value={"regime": "low|medium|high", "cv": float}).
        symbol_cv: dict[str, float] = {}
        symbol_overrides: dict[str, object] = {}  # SymbolConfigRecord per symbol
        try:
            from trdex.storage.entity_graph_repo import EntityGraphRepository
            from trdex.storage.symbol_config_repo import SymbolConfigRepository
            async with self._session_factory() as session:
                eg_repo = EntityGraphRepository(session)
                for sym in {p.symbol for p in open_positions}:
                    val = await eg_repo.get_value("symbol", sym, "volatility_regime")
                    if val and isinstance(val, dict) and "cv" in val:
                        symbol_cv[sym] = float(val["cv"])
                # Load per-symbol overrides (from symbol_config table)
                sc_repo = SymbolConfigRepository(session)
                symbol_overrides = await sc_repo.get_map()
        except Exception:
            logger.warning("[StopLoss] could not load volatility CV / symbol_config — using base thresholds")

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

            # Compute effective thresholds for this position (see
            # effective_thresholds for the priority rules).
            cv = symbol_cv.get(pos.symbol, 0.0)
            eff_sl, eff_tp, eff_trail = effective_thresholds(
                pos,
                symbol_overrides.get(pos.symbol),
                cv,
                base_sl=self._sl_pct,
                base_tp=self._tp_pct,
                base_trail=self._trailing_pct,
            )

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

            # Per-position stop-loss (adaptive)
            if pnl_pct <= -eff_sl:
                event = StopLossEvent(
                    reason=StopReason.POSITION_STOP_LOSS,
                    symbol=pos.symbol,
                    position_id=pos.id,
                    trigger_price=price,
                    entry_price=entry,
                    loss_pct=pnl_pct,
                    message=(
                        f"{pos.symbol} position {pos.id} hit stop-loss: "
                        f"{pnl_pct:.2%} loss (limit: {-eff_sl:.2%}, cv={cv:.4f})"
                    ),
                )
                new_events.append(event)
                logger.warning("[StopLoss] POSITION SL: %s", event.message)
                await self._auto_close(pos, price, "stop_loss", price_age=price_times.get(pos.symbol))

            # Per-position take-profit (adaptive)
            elif pnl_pct >= eff_tp:
                event = StopLossEvent(
                    reason=StopReason.POSITION_TAKE_PROFIT,
                    symbol=pos.symbol,
                    position_id=pos.id,
                    trigger_price=price,
                    entry_price=entry,
                    loss_pct=pnl_pct,
                    message=(
                        f"{pos.symbol} position {pos.id} hit take-profit: "
                        f"{pnl_pct:.2%} gain (limit: {eff_tp:.2%}, cv={cv:.4f})"
                    ),
                )
                new_events.append(event)
                logger.info("[StopLoss] POSITION TP: %s", event.message)
                await self._auto_close(pos, price, "take_profit", price_age=price_times.get(pos.symbol))

            # Trailing stop: price retraced from high-water mark (adaptive)
            elif pnl_pct > 0 and pos_id in self._trailing_highs:
                hwm = self._trailing_highs[pos_id]
                if pos.side == "BUY":
                    retrace = (hwm - price) / hwm if hwm > 0 else 0.0
                else:
                    retrace = (price - hwm) / hwm if hwm > 0 else 0.0

                if retrace >= eff_trail:
                    event = StopLossEvent(
                        reason=StopReason.TRAILING_STOP,
                        symbol=pos.symbol,
                        position_id=pos_id,
                        trigger_price=price,
                        entry_price=entry,
                        loss_pct=pnl_pct,
                        message=(
                            f"{pos.symbol} position {pos_id} trailing stop: "
                            f"retraced {retrace:.2%} from peak {hwm:.4f} (limit: {eff_trail:.2%}, cv={cv:.4f})"
                        ),
                    )
                    new_events.append(event)
                    logger.warning("[StopLoss] TRAILING STOP: %s", event.message)
                    await self._auto_close(pos, price, "trailing_stop", price_age=price_times.get(pos.symbol))
                    del self._trailing_highs[pos_id]  # Clean up after close

        # Portfolio-level checks. Skipped while the kill switch is already
        # tripped (see top of check_now) or when the ledger could not be read.
        if not kill_switch_was_active:
            await self._check_portfolio_limits(
                new_events,
                total_unrealized=total_unrealized,
                total_cost=total_cost,
                realised_balance=realised_balance,
                day_start_balance=day_start_balance,
            )

        # Store and dispatch
        self._events.extend(new_events)
        self._last_check = datetime.now(tz=timezone.utc)

        # Persist each event to the log — best-effort, per-event,
        # so a single bad write cannot poison the whole batch.
        for event in new_events:
            await self._persist_event(event)

        # Trim the in-memory cache to the same window recent_events
        # exposes (last 50) to avoid unbounded growth on a busy day.
        if len(self._events) > 200:
            self._events = self._events[-100:]

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
            "events_fired": self._events_fired_total,
            "thresholds": {
                "position_sl_pct": self._sl_pct,
                "position_tp_pct": self._tp_pct,
                "trailing_stop_pct": self._trailing_pct,
                "daily_drawdown_pct": self._daily_dd_pct,
                "open_positions_loss_pct": self._open_loss_pct,
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
