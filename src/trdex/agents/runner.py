"""AgentRunner: assembles MarketSnapshot from DB + feed, then runs the agent cycle."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from trdex.agents.graph import run_agent_cycle
from trdex.agents.intent import Intent
from trdex.agents.state import AgentState, MarketSnapshot, PortfolioContext
from trdex.market.manager import PriceFeedManager
from trdex.storage.agent_run_models import AgentRunRecord
from trdex.storage.ohlcv_repo import OHLCVRepository
from trdex.storage.balance_repo import BalanceRepository
from trdex.storage.portfolio_repo import PortfolioRepository

logger = logging.getLogger(__name__)

_DEFAULT_TIMEFRAME = "1h"
_DEFAULT_CANDLES = 100


class AgentRunner:
    """Wires market data (OHLCV DB + live feed) into `run_agent_cycle()`.

    Usage:
        runner = AgentRunner(session, feed_manager)
        state = await runner.run("BTC/USDT")
    """

    def __init__(
        self,
        session: AsyncSession,
        feed_manager: PriceFeedManager,
        session_factory=None,
        gateway=None,
        memory_loader=None,
    ) -> None:
        self._session = session
        self._feeds = feed_manager
        self._ohlcv_repo = OHLCVRepository(session)
        self._session_factory = session_factory
        self._gateway = gateway
        self._memory_loader = memory_loader

    async def _load_portfolio_context(self) -> PortfolioContext:
        """Load live portfolio state from DB for risk gate decisions."""
        try:
            pos_repo = PortfolioRepository(self._session)
            bal_repo = BalanceRepository(self._session)

            open_positions = await pos_repo.get_open_positions()
            open_symbols = [p.symbol for p in open_positions]
            # D21: subset restricted to agent-sourced positions, so the
            # translator and Gate 4 never touch Telegram-opened ones.
            open_symbols_by_agent = [
                p.symbol for p in open_positions if p.source == "agent"
            ]

            unrealized_pnl = sum(
                (float(p.exit_price or 0) - float(p.entry_price)) * float(p.amount)
                if p.side == "BUY"
                else (float(p.entry_price) - float(p.exit_price or 0)) * float(p.amount)
                for p in open_positions
            )

            # Cash balance from ledger (authoritative source)
            balance = float(await bal_repo.current_balance())
            peak_balance = float(await bal_repo.peak_balance())
            equity = balance + unrealized_pnl
            peak_equity = peak_balance  # peak is tracked via ledger entries at fill time
            drawdown_pct = max(0.0, (peak_equity - equity) / peak_equity) if peak_equity > 0 else 0.0

            return PortfolioContext(
                equity=equity,
                open_position_symbols=open_symbols,
                open_position_symbols_by_agent=open_symbols_by_agent,
                unrealized_pnl=unrealized_pnl,
                realized_pnl=balance - peak_balance,  # net change from peak
                drawdown_pct=drawdown_pct,
            )
        except Exception:
            logger.exception("[runner] failed to load portfolio context — using empty defaults")
            return PortfolioContext()

    async def run(
        self,
        symbol: str,
        timeframe: str = _DEFAULT_TIMEFRAME,
        candle_limit: int = _DEFAULT_CANDLES,
    ) -> AgentState:
        """Build MarketSnapshot and run one full agent cycle.

        Data priority:
        1. OHLCV candles from TimescaleDB (fastest, no rate-limit)
        2. Falls back to live feed if DB has no data for the symbol
        3. Current price always fetched live for accuracy
        """
        # 1. Fetch current price — aggregated across selected feeds for
        #    robustness against single-exchange flash spikes. The user
        #    selects which feeds to query via the dashboard.
        try:
            from trdex.market.manager import get_selected_feeds
            ticker = await self._feeds.get_ticker_aggregated(
                symbol, feed_names=get_selected_feeds()
            )
            current_price = float(ticker.price)
        except Exception:
            logger.exception("[runner] failed to fetch aggregated ticker for %s", symbol)
            current_price = 0.0

        # 2. Fetch OHLCV — prefer DB, fallback to live feed
        candles_raw: list[tuple[datetime, float, float, float, float, float]] = []
        try:
            records = await self._ohlcv_repo.fetch(symbol, timeframe, limit=candle_limit)
            if records:
                candles_raw = [
                    (r.timestamp, float(r.open), float(r.high), float(r.low),
                     float(r.close), float(r.volume))
                    for r in records
                ]
                logger.debug("[runner] loaded %d candles from DB for %s", len(candles_raw), symbol)
        except Exception:
            logger.exception("[runner] DB candle fetch failed for %s", symbol)

        if not candles_raw:
            try:
                live_candles = await self._feeds.get_ohlcv(symbol, timeframe, limit=candle_limit)
                candles_raw = [
                    (c.timestamp, float(c.open), float(c.high), float(c.low),
                     float(c.close), float(c.volume))
                    for c in live_candles
                ]
                logger.debug("[runner] loaded %d candles from live feed for %s", len(candles_raw), symbol)
            except Exception:
                logger.exception("[runner] live candle fetch also failed for %s", symbol)

        snapshot = MarketSnapshot(
            symbol=symbol,
            price=current_price,
            timestamp=datetime.now(tz=timezone.utc),
            candles=candles_raw,
        )

        # 3. Load portfolio context for risk gate decisions
        portfolio_ctx = await self._load_portfolio_context()

        # 4. Run agent cycle
        state = await run_agent_cycle(
            symbol=symbol,
            market_snapshot=snapshot,
            portfolio_context=portfolio_ctx,
            session_factory=self._session_factory,
            gateway=self._gateway,
            memory_loader=self._memory_loader,
        )

        # 5. Persist the agent run row (audit trail)
        await self._persist(state)

        # 6. Dispatch the fill side effect to the portfolio persistence
        # layer. OPEN intents create a new position row; CLOSE intents
        # update the existing one and write a trade_fill ledger entry.
        await self._dispatch_fill(state)

        return state

    async def _dispatch_fill(self, state: AgentState) -> None:
        """Persist the portfolio-side effect of a successful fill.

        D9: single switch on ``state.analysis.intent`` replaces the old
        "persist_open" special-case, making the two paths explicit and
        symmetric.

        D13: the CLOSE path re-reads the live DB to find the position,
        protecting against a TOCTOU race with the StopLossMonitor that
        may have closed the position between cycle start and dispatch.

        D14: if the CLOSE path cannot find a matching agent-owned
        position, it logs a structured ``fill_orphan_warning`` and
        returns — it does not write anything.

        Best-effort: any failure here is logged and swallowed so it
        cannot break the cycle return value.

        Residual risk (D15): in live mode, if persistence fails AFTER
        the exchange has filled the order, local DB and exchange state
        diverge until the future ``fill_reconciliation`` table is
        built. Accepted until Phase 2 observation data justifies
        building it.
        """
        if state.order.status != "filled":
            return
        if not state.risk.approved:
            # Defensive: the executor should not be called on a blocked
            # run, but if it happens we don't want to persist the effect.
            return
        if state.order.filled_price is None or state.order.filled_qty is None:
            logger.warning(
                "[runner] filled order missing price/qty for %s — skipping dispatch",
                state.symbol,
            )
            return

        intent = state.analysis.intent
        try:
            if intent == Intent.OPEN_LONG:
                await self._record_open_long(state)
            elif intent == Intent.CLOSE_LONG:
                await self._record_close_long(state)
            else:
                # OPEN_SHORT / CLOSE_SHORT are reserved vocabulary and
                # the Risk gate should never let them reach here today;
                # HOLD never reaches the executor at all. Log+skip.
                logger.warning(
                    "[runner] _dispatch_fill: unsupported intent %s for %s — skipping",
                    intent.value, state.symbol,
                )
        except Exception:
            logger.exception(
                "[runner] _dispatch_fill failed for %s (intent=%s) — cycle result unaffected",
                state.symbol, intent.value,
            )

    async def _record_open_long(self, state: AgentState) -> None:
        """Persist an OPEN_LONG fill as a new position row."""
        from decimal import Decimal

        from trdex.portfolio.service import PortfolioService

        repo = PortfolioRepository(self._session)
        service = PortfolioService(repo, self._feeds)

        filled_price_dec = Decimal(str(state.order.filled_price))
        filled_qty_dec = Decimal(str(state.order.filled_qty))
        budget = filled_price_dec * filled_qty_dec
        fee = state.order.fee if state.order.fee is not None else Decimal("0")

        await service.record_open_fill(
            symbol=state.symbol,
            side="BUY",
            amount=filled_qty_dec,
            entry_price=filled_price_dec,
            budget=budget,
            fee=fee,
            source="agent",
            signal_id=state.run_id,
        )

    async def _record_close_long(self, state: AgentState) -> None:
        """Persist a CLOSE_LONG fill as an update to the existing position
        plus a ``trade_fill`` row in the balance ledger.

        D13: re-reads the live DB for the agent-owned open position on
        ``state.symbol``. D14: if none is found, writes a structured
        warning and returns without mutating anything.
        """
        from decimal import Decimal

        from trdex.portfolio.service import PortfolioService

        repo = PortfolioRepository(self._session)
        positions = await repo.get_open_positions()
        match = next(
            (
                p for p in positions
                if p.symbol == state.symbol and p.source == "agent"
            ),
            None,
        )
        if match is None:
            logger.warning(
                "[runner] fill_orphan_warning: CLOSE_LONG filled for %s "
                "(run_id=%s) but no open agent position found — possibly "
                "closed by StopLossMonitor mid-cycle. Ledger not written.",
                state.symbol, state.run_id,
            )
            return

        service = PortfolioService(repo, self._feeds)
        filled_price_dec = Decimal(str(state.order.filled_price))
        fee = state.order.fee if state.order.fee is not None else Decimal("0")
        await service.record_close_fill(
            position=match,
            exit_price=filled_price_dec,
            fee=fee,
            closed_by="agent_signal",
        )

    async def _persist(self, state: AgentState) -> None:
        """Save agent run result to agent_runs table.

        Historical note (D11 rev, D24): the DB column is still named
        ``signal`` but carries Intent string values (``open_long``,
        ``close_long``, ``hold``, …) since the 2026-04-08 refactor. No
        migration was applied — the column rename would be churn for a
        3-row dataset. See brainstorm-2026-04-07-intent-enum.md.
        """
        try:
            ran_at = (state.completed_at or datetime.now(tz=timezone.utc)).replace(tzinfo=None)
            intent_value = state.analysis.intent.value
            record = AgentRunRecord(
                run_id=state.run_id,
                symbol=state.symbol,
                ran_at=ran_at,
                signal=intent_value,  # historical column name, now stores Intent
                confidence=state.analysis.confidence,
                reasoning=state.analysis.reasoning,
                indicators=state.analysis.indicators,
                risk_approved=state.risk.approved,
                risk_reason=state.risk.reason,
                position_size=state.risk.position_size,
                stop_loss_pct=state.risk.stop_loss_pct,
                take_profit_pct=state.risk.take_profit_pct,
                order_status=state.order.status,
                filled_price=state.order.filled_price,
                filled_qty=state.order.filled_qty,
                order_message=state.order.message,
                error=state.error,
            )
            self._session.add(record)
            await self._session.commit()
            logger.info("[runner] persisted run_id=%s intent=%s order=%s",
                        state.run_id, intent_value, state.order.status)
        except Exception:
            logger.exception("[runner] failed to persist agent run for %s", state.symbol)
